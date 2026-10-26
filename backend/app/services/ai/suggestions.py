"""M3a Slice 2/3：AI 打标建议、错题解析与答案润色。

所有输出先落 `ai_suggestions`，只有用户显式“应用”后才修改待审项的
suggested_meta 或正式题目；失败也落一条记录，便于前端提示与重试。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import config as app_config
from ...errors import ApiError
from ...models import AiSuggestion, PendingItem, Question
from ...utils.timeutil import utcnow
from ..audit import audit
from ..serializers import json_obj, serialize_pending, serialize_question
from .common import category_lookup, fit_payload, question_context, taxonomy_context
from .gateway import AIConfig, get_ai_gateway
from .prompts import (
    ANSWER_POLISH,
    MISTAKE_ANALYSIS,
    TAG_SUGGEST,
    get_or_create_prompt_version,
    load_prompt,
    render_system_prompt,
)

logger = logging.getLogger("bajiu.ai.suggestions")

Kind = Literal["tagging", "mistake_analysis", "answer_polish"]
TargetType = Literal["pending", "question", "knowledge"]
Frequency = Literal["high", "mid", "low"]

KINDS = ("tagging", "mistake_analysis", "answer_polish")


class TagSuggestionOutput(BaseModel):
    category_path: str = ""
    tags: list[str] = Field(default_factory=list)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str = ""


class RelatedKnowledge(BaseModel):
    title: str = ""
    why: str = ""


class MistakeAnalysisOutput(BaseModel):
    explanation: str = ""
    pitfalls: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    related_knowledge: list[RelatedKnowledge] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class AnswerPolishOutput(BaseModel):
    polished_answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


def _parse_result(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def serialize_suggestion(row: AiSuggestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "status": row.status,
        "result": _parse_result(row.result_json),
        "model": row.model,
        "prompt_version_id": row.prompt_version_id,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat(),
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def latest_suggestions(
    db: Session,
    *,
    kind: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    limit: int = 20,
) -> list[AiSuggestion]:
    stmt = select(AiSuggestion)
    if kind:
        stmt = stmt.where(AiSuggestion.kind == kind)
    if target_type:
        stmt = stmt.where(AiSuggestion.target_type == target_type)
    if target_id is not None:
        stmt = stmt.where(AiSuggestion.target_id == target_id)
    return list(
        db.scalars(
            stmt.order_by(AiSuggestion.created_at.desc(), AiSuggestion.id.desc()).limit(
                limit
            )
        ).all()
    )


# ---- 输入构造 -----------------------------------------------------------


def _tag_payload(db: Session, target_type: str, target_id: int) -> dict[str, Any]:
    if target_type != "pending":
        raise ApiError(400, "VALIDATION_ERROR", "打标建议目前只支持待审项")
    item = db.get(PendingItem, target_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "待审项不存在")
    if item.status != "pending":
        raise ApiError(409, "CONFLICT", "只能为待审中的条目生成打标建议")
    if item.item_type == "question":
        payload: dict[str, Any] = {
            "item_type": "question",
            "stem": item.stem or "",
            "answer": item.answer or "",
        }
    else:
        payload = {
            "item_type": "knowledge",
            "title": item.knowledge_title or "",
            "content": item.knowledge_content or "",
        }
    payload.update(taxonomy_context(db))
    return fit_payload(payload, max(1000, app_config.AI_MAX_INPUT_CHARS))


def _require_question(db: Session, question_id: int) -> Question:
    question = db.get(Question, question_id)
    if question is None or question.is_deleted:
        raise ApiError(404, "NOT_FOUND", "题目不存在")
    if question.status != "active":
        raise ApiError(409, "CONFLICT", "只能对正式题目使用 AI 增强")
    return question


def _mistake_payload(
    db: Session,
    question_id: int,
    *,
    user_answer: str | None,
    consent: bool,
) -> dict[str, Any]:
    question = _require_question(db, question_id)
    payload = question_context(db, question)
    payload.update(taxonomy_context(db, max_paths=40, max_tags=60))
    # 默认不发送任何用户作答原文；只有显式同意且确实提供时才附带。
    if consent and user_answer and user_answer.strip():
        payload["user_answer"] = user_answer.strip()[:4000]
    return fit_payload(payload, max(1000, app_config.AI_MAX_INPUT_CHARS))


def _polish_payload(db: Session, question_id: int) -> dict[str, Any]:
    question = _require_question(db, question_id)
    if not (question.answer or "").strip() and not (question.key_points or "").strip():
        raise ApiError(400, "VALIDATION_ERROR", "题目暂无答案或要点，无法润色")
    return fit_payload(
        question_context(db, question), max(1000, app_config.AI_MAX_INPUT_CHARS)
    )


def _dispatch(
    db: Session,
    kind: str,
    target_type: str,
    target_id: int,
    *,
    user_answer: str | None,
    consent: bool,
) -> tuple[Any, type[BaseModel], dict[str, Any], str]:
    if kind == "tagging":
        return (
            load_prompt(*TAG_SUGGEST),
            TagSuggestionOutput,
            _tag_payload(db, target_type, target_id),
            "tag_suggest",
        )
    if kind == "mistake_analysis":
        if target_type != "question":
            raise ApiError(400, "VALIDATION_ERROR", "错题解析只支持正式题目")
        return (
            load_prompt(*MISTAKE_ANALYSIS),
            MistakeAnalysisOutput,
            _mistake_payload(db, target_id, user_answer=user_answer, consent=consent),
            "mistake_analysis",
        )
    if kind == "answer_polish":
        if target_type != "question":
            raise ApiError(400, "VALIDATION_ERROR", "答案润色只支持正式题目")
        return (
            load_prompt(*ANSWER_POLISH),
            AnswerPolishOutput,
            _polish_payload(db, target_id),
            "answer_polish",
        )
    raise ApiError(400, "VALIDATION_ERROR", "kind 不合法")


# ---- 生成建议 -----------------------------------------------------------


def run_suggestion(
    db: Session,
    *,
    kind: str,
    target_type: str,
    target_id: int,
    user_answer: str | None = None,
    consent: bool = False,
) -> AiSuggestion:
    spec, schema_model, payload, purpose = _dispatch(
        db,
        kind,
        target_type,
        target_id,
        user_answer=user_answer,
        consent=consent,
    )
    prompt_row = get_or_create_prompt_version(db, spec)
    # 先提交 prompt 版本与本请求的读事务，再发起外部调用。
    db.commit()

    config = AIConfig.from_env()
    try:
        result = get_ai_gateway(db).complete_json(
            purpose=purpose,
            system_prompt=render_system_prompt(spec),
            payload=payload,
            schema_model=schema_model,
            prompt_version_id=prompt_row.id,
            cache_input=payload,
        )
    except ApiError as exc:
        row = AiSuggestion(
            kind=kind,
            target_type=target_type,
            target_id=target_id,
            status="failed",
            result_json=None,
            model=config.model or "",
            prompt_version_id=prompt_row.id,
            error_code=exc.code,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        exc.data = {
            **(exc.data if isinstance(exc.data, dict) else {}),
            "suggestion": serialize_suggestion(row),
        }
        raise

    row = AiSuggestion(
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        status="success",
        result_json=json.dumps(result, ensure_ascii=False),
        model=config.model or "ai",
        prompt_version_id=prompt_row.id,
    )
    db.add(row)
    audit(db, f"ai_{kind}", target_type, target_id, {"suggestion_id": row.id})
    db.commit()
    db.refresh(row)
    return row


# ---- 应用建议 -----------------------------------------------------------


def _merge_tags(existing: list[str], suggested: list[str]) -> list[str]:
    merged = [str(tag).strip() for tag in existing if str(tag).strip()]
    lowered = {tag.lower() for tag in merged}
    for tag in suggested:
        text = str(tag).strip()
        if text and text.lower() not in lowered:
            merged.append(text)
            lowered.add(text.lower())
    return merged[:12]


def _apply_tagging(db: Session, row: AiSuggestion) -> dict[str, Any]:
    if row.target_type != "pending":
        raise ApiError(400, "VALIDATION_ERROR", "打标建议只能应用到待审项")
    item = db.get(PendingItem, row.target_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "待审项不存在")
    if item.status != "pending":
        raise ApiError(409, "CONFLICT", "只能应用到待审中的条目")
    result = _parse_result(row.result_json) or {}
    meta = json_obj(item.suggested_meta)
    meta["tags"] = _merge_tags(
        [str(tag) for tag in meta.get("tags", []) or []],
        [str(tag) for tag in result.get("tags", []) or []],
    )
    path = str(result.get("category_path") or "").strip().strip("/")
    if path:
        category = category_lookup(db).get(path)
        meta["category_path"] = path
        if category is not None:
            if item.item_type == "knowledge":
                meta["knowledge_category_id"] = category.id
            else:
                meta["category_id"] = category.id
        else:
            meta.pop("category_id", None)
            meta.pop("knowledge_category_id", None)
    if result.get("difficulty") is not None:
        meta["difficulty"] = int(result["difficulty"])
    if result.get("frequency") in ("high", "mid", "low"):
        meta["frequency"] = result["frequency"]
    meta["ai_tagging"] = {
        "suggestion_id": row.id,
        "applied_at": utcnow().isoformat(),
        "confidence": result.get("confidence"),
        "rationale": result.get("rationale") or "",
    }
    item.suggested_meta = json.dumps(meta, ensure_ascii=False)
    row.applied_at = utcnow()
    audit(db, "ai_suggestion_apply", "pending", item.id, {"kind": row.kind, "suggestion_id": row.id})
    db.commit()
    return {
        "suggestion": serialize_suggestion(row),
        "target_type": "pending",
        "target": serialize_pending(db, item),
    }


def _apply_answer_polish(db: Session, row: AiSuggestion) -> dict[str, Any]:
    if row.target_type != "question":
        raise ApiError(400, "VALIDATION_ERROR", "答案润色只能应用到题目")
    question = db.get(Question, row.target_id)
    if question is None or question.is_deleted:
        raise ApiError(404, "NOT_FOUND", "题目不存在")
    result = _parse_result(row.result_json) or {}
    answer = str(result.get("polished_answer") or "").strip()
    if not answer:
        raise ApiError(502, "AI_SCHEMA_INVALID", "润色结果为空，无法应用")
    question.answer = answer
    key_points = [
        str(point).strip()
        for point in result.get("key_points", []) or []
        if str(point).strip()
    ]
    if key_points:
        question.key_points = json.dumps(key_points[:8], ensure_ascii=False)
    question.updated_at = utcnow()
    row.applied_at = utcnow()
    audit(
        db,
        "ai_suggestion_apply",
        "question",
        question.id,
        {"kind": row.kind, "suggestion_id": row.id},
    )
    db.commit()
    return {
        "suggestion": serialize_suggestion(row),
        "target_type": "question",
        "target": serialize_question(db, question, detail=True),
    }


def apply_suggestion(db: Session, row: AiSuggestion) -> dict[str, Any]:
    if row.status != "success":
        raise ApiError(409, "CONFLICT", "失败的 AI 建议不能应用，请重新生成")
    if row.applied_at is not None:
        raise ApiError(409, "CONFLICT", "该建议已应用")
    if row.kind == "tagging":
        return _apply_tagging(db, row)
    if row.kind == "answer_polish":
        return _apply_answer_polish(db, row)
    if row.kind == "mistake_analysis":
        raise ApiError(400, "VALIDATION_ERROR", "错题解析只作参考，无需应用")
    raise ApiError(400, "VALIDATION_ERROR", "kind 不合法")
