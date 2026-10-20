"""M3a 质量审查：AI 建议与人工质检共用一个记录模型。

AI 只写建议记录，不改变待审状态、不修改正式内容；AI 失败时落一条
status=failed 的记录，前端可据此引导人工质检。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import config as app_config
from ...errors import ApiError
from ...models import (
    KnowledgePoint,
    PendingItem,
    QualityCheck,
    Question,
)
from ...utils.timeutil import utcnow
from ..audit import audit
from ..serializers import json_list
from .gateway import AIConfig, get_ai_gateway
from .prompts import (
    QUALITY_CHECK,
    get_or_create_prompt_version,
    load_prompt,
    render_system_prompt,
)

logger = logging.getLogger("bajiu.ai.quality")

IssueType = Literal[
    "fact_error",
    "outdated",
    "ambiguous",
    "incomplete",
    "inconsistent",
    "duplicate",
    "other",
]
Risk = Literal["low", "medium", "high"]
TargetType = Literal["question", "knowledge", "pending"]

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


class QualityIssue(BaseModel):
    type: IssueType = "other"
    severity: Risk = "low"
    description: str = ""
    evidence: str = ""
    suggestion: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)


class QualityOutput(BaseModel):
    target_type: TargetType
    target_id: int
    issues: list[QualityIssue] = Field(default_factory=list)
    overall_risk: Risk = "low"
    summary: str = ""


def _require_target(db: Session, target_type: str, target_id: int) -> None:
    if target_type == "pending":
        if db.get(PendingItem, target_id) is None:
            raise ApiError(404, "NOT_FOUND", "待审项不存在")
        return
    if target_type == "question":
        question = db.get(Question, target_id)
        if question is None or question.is_deleted:
            raise ApiError(404, "NOT_FOUND", "题目不存在")
        return
    if target_type == "knowledge":
        knowledge = db.get(KnowledgePoint, target_id)
        if knowledge is None or knowledge.is_deleted:
            raise ApiError(404, "NOT_FOUND", "知识条目不存在")
        return
    raise ApiError(400, "VALIDATION_ERROR", "target_type 仅支持 question / knowledge / pending")


def _build_payload(db: Session, target_type: str, target_id: int) -> dict[str, Any]:
    _require_target(db, target_type, target_id)
    if target_type == "pending":
        item = db.get(PendingItem, target_id)
        if item.item_type == "question":
            payload: dict[str, Any] = {
                "target_type": "pending",
                "target_id": item.id,
                "item_type": "question",
                "stem": item.stem or "",
                "answer": item.answer or "",
            }
        else:
            payload = {
                "target_type": "pending",
                "target_id": item.id,
                "item_type": "knowledge",
                "title": item.knowledge_title or "",
                "content": item.knowledge_content or "",
            }
    elif target_type == "question":
        question = db.get(Question, target_id)
        payload = {
            "target_type": "question",
            "target_id": question.id,
            "stem": question.stem,
            "answer": question.answer or "",
            "key_points": json_list(question.key_points),
        }
    else:
        knowledge = db.get(KnowledgePoint, target_id)
        payload = {
            "target_type": "knowledge",
            "target_id": knowledge.id,
            "title": knowledge.title,
            "content": knowledge.content,
            "kind": knowledge.kind,
            "aliases": json_list(knowledge.aliases),
        }
    return _fit_payload(payload, max(1000, app_config.AI_MAX_INPUT_CHARS))


def _fit_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= limit:
        return payload
    string_keys = [key for key, value in payload.items() if isinstance(value, str)]
    for key in sorted(string_keys, key=lambda item: len(payload[item]), reverse=True):
        if len(text) <= limit:
            break
        excess = len(text) - limit
        value = payload[key]
        keep = max(200, len(value) - excess - 16)
        payload[key] = value[:keep] + "…（已截断）"
        text = json.dumps(payload, ensure_ascii=False)
    return payload


def risk_from_issues(issues: list[dict[str, Any]]) -> str:
    rank = max((_SEVERITY_RANK.get(str(issue.get("severity")), 1) for issue in issues), default=1)
    return {1: "low", 2: "medium", 3: "high"}[rank]


def _load_issues(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def serialize_quality_check(row: QualityCheck) -> dict[str, Any]:
    return {
        "id": row.id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "status": row.status,
        "issues": _load_issues(row.issues_json),
        "overall_risk": row.overall_risk,
        "summary": row.summary,
        "model": row.model,
        "prompt_version_id": row.prompt_version_id,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }


def run_quality_check(
    db: Session,
    target_type: str,
    target_id: int,
    *,
    mode: str = "ai",
    manual_issues: list[dict[str, Any]] | None = None,
    overall_risk: str | None = None,
    summary: str | None = None,
) -> QualityCheck:
    _require_target(db, target_type, target_id)
    if mode == "manual":
        issues = manual_issues or []
        risk = overall_risk or risk_from_issues(issues)
        row = QualityCheck(
            target_type=target_type,
            target_id=target_id,
            status="success",
            issues_json=json.dumps(issues, ensure_ascii=False),
            overall_risk=risk,
            summary=(summary or "")[:2000] or None,
            model="manual",
            prompt_version_id=None,
            reviewed_at=utcnow(),
        )
        db.add(row)
        audit(
            db,
            "quality_check_manual",
            target_type,
            target_id,
            {"issues": len(issues), "overall_risk": risk},
        )
        db.commit()
        db.refresh(row)
        return row

    spec = load_prompt(*QUALITY_CHECK)
    prompt_row = get_or_create_prompt_version(db, spec)
    payload = _build_payload(db, target_type, target_id)
    # 先提交 prompt 版本与本请求的读事务，再发起外部调用。
    db.commit()

    config = AIConfig.from_env()
    gateway = get_ai_gateway(db)
    try:
        result = gateway.complete_json(
            purpose="quality_check",
            system_prompt=render_system_prompt(spec),
            payload=payload,
            schema_model=QualityOutput,
            prompt_version_id=prompt_row.id,
            cache_input=payload,
        )
    except ApiError as exc:
        row = QualityCheck(
            target_type=target_type,
            target_id=target_id,
            status="failed",
            issues_json=None,
            overall_risk=None,
            summary=(exc.message or "")[:2000] or None,
            model=config.model or "",
            prompt_version_id=prompt_row.id,
            error_code=exc.code,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        exc.data = {**(exc.data if isinstance(exc.data, dict) else {}), "check": serialize_quality_check(row)}
        raise

    if result.get("target_type") != target_type or int(result.get("target_id", -1)) != target_id:
        row = QualityCheck(
            target_type=target_type,
            target_id=target_id,
            status="failed",
            issues_json=None,
            overall_risk=None,
            summary="AI 返回的目标与请求不一致",
            model=config.model or "",
            prompt_version_id=prompt_row.id,
            error_code="AI_SCHEMA_INVALID",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        raise ApiError(
            502,
            "AI_SCHEMA_INVALID",
            "AI 返回的目标与请求不一致，已记录为失败，可重试或转人工质检",
        )

    issues = result.get("issues") or []
    risk = result.get("overall_risk") or risk_from_issues(issues)
    row = QualityCheck(
        target_type=target_type,
        target_id=target_id,
        status="success",
        issues_json=json.dumps(issues, ensure_ascii=False),
        overall_risk=risk,
        summary=(result.get("summary") or "")[:2000] or None,
        model=config.model or "ai",
        prompt_version_id=prompt_row.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_checks(
    db: Session, target_type: str, target_id: int, limit: int = 10
) -> list[QualityCheck]:
    return list(
        db.scalars(
            select(QualityCheck)
            .where(
                QualityCheck.target_type == target_type,
                QualityCheck.target_id == target_id,
            )
            .order_by(QualityCheck.created_at.desc(), QualityCheck.id.desc())
            .limit(limit)
        ).all()
    )


def _summary_from_rows(rows: list[QualityCheck]) -> dict[str, Any]:
    latest_success = next((row for row in rows if row.status == "success"), None)
    latest_failed = next((row for row in rows if row.status == "failed"), None)
    if latest_success and (
        latest_failed is None
        or (latest_success.created_at, latest_success.id)
        >= (latest_failed.created_at, latest_failed.id)
    ):
        return {
            "status": "checked",
            "risk": latest_success.overall_risk,
            "source": "manual" if latest_success.model == "manual" else "ai",
            "model": latest_success.model,
            "checked_at": latest_success.created_at.isoformat(),
            "error_code": None,
            "summary": latest_success.summary,
        }
    if latest_failed:
        return {
            "status": "needs_manual",
            "risk": None,
            "source": "ai",
            "model": latest_failed.model,
            "checked_at": latest_failed.created_at.isoformat(),
            "error_code": latest_failed.error_code,
            "summary": latest_failed.summary,
        }
    return {
        "status": "unchecked",
        "risk": None,
        "source": None,
        "model": None,
        "checked_at": None,
        "error_code": None,
        "summary": None,
    }


def quality_summary(db: Session, target_type: str, target_id: int) -> dict[str, Any]:
    return _summary_from_rows(latest_checks(db, target_type, target_id))


def quality_summaries(
    db: Session, target_type: str, target_ids: list[int]
) -> dict[int, dict[str, Any]]:
    if not target_ids:
        return {}
    rows = db.scalars(
        select(QualityCheck)
        .where(
            QualityCheck.target_type == target_type,
            QualityCheck.target_id.in_(target_ids),
        )
        .order_by(QualityCheck.created_at.desc(), QualityCheck.id.desc())
    ).all()
    grouped: dict[int, list[QualityCheck]] = defaultdict(list)
    for row in rows:
        grouped[row.target_id].append(row)
    return {
        target_id: _summary_from_rows(grouped.get(target_id, []))
        for target_id in target_ids
    }
