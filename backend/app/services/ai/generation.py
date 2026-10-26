"""M3b 题库生产：围绕知识点生成题目，一律进入待审区，绝不直接写正式题库。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import config as app_config
from ...errors import ApiError
from ...models import KnowledgePoint, PendingItem, Question
from ..audit import audit
from ..categories import category_map, category_path
from ..serializers import json_list, serialize_pending
from .common import category_lookup, fit_payload, taxonomy_context
from .gateway import get_ai_gateway
from .prompts import (
    QUESTION_GENERATE,
    get_or_create_prompt_version,
    load_prompt,
    render_system_prompt,
)

Frequency = Literal["high", "mid", "low"]


class GeneratedQuestion(BaseModel):
    stem: str = ""
    answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    category_path: str = ""
    tags: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class QuestionGenerateOutput(BaseModel):
    questions: list[GeneratedQuestion] = Field(default_factory=list, min_length=1, max_length=10)


def _build_payload(
    db: Session,
    *,
    knowledge_id: int | None,
    topic: str | None,
    category_path_value: str | None,
    count: int,
    difficulty: int | None,
) -> dict[str, Any]:
    if knowledge_id is not None:
        knowledge = db.get(KnowledgePoint, knowledge_id)
        if knowledge is None or knowledge.is_deleted or knowledge.status != "active":
            raise ApiError(404, "NOT_FOUND", "知识条目不存在或未启用")
        mapping = category_map(db)
        payload: dict[str, Any] = {
            "topic": knowledge.title,
            "knowledge_content": knowledge.content,
            "kind": knowledge.kind,
            "category_path": category_path(knowledge.category_id, mapping),
            "aliases": json_list(knowledge.aliases),
        }
    else:
        text = (topic or "").strip()
        if not text:
            raise ApiError(400, "VALIDATION_ERROR", "请指定知识点或主题")
        payload = {"topic": text, "category_path": category_path_value or ""}
    payload["count"] = count
    payload["difficulty"] = difficulty
    payload.update(taxonomy_context(db, max_paths=80, max_tags=80))
    return fit_payload(payload, max(1000, app_config.AI_MAX_INPUT_CHARS))


def generate_questions(
    db: Session,
    *,
    knowledge_id: int | None = None,
    topic: str | None = None,
    category_path_value: str | None = None,
    count: int = 3,
    difficulty: int | None = None,
) -> dict[str, Any]:
    count = max(1, min(count, 10))
    topic_text = (topic or "").strip()
    if knowledge_id is not None:
        knowledge = db.get(KnowledgePoint, knowledge_id)
        if knowledge is not None:
            topic_text = knowledge.title
    payload = _build_payload(
        db,
        knowledge_id=knowledge_id,
        topic=topic,
        category_path_value=category_path_value,
        count=count,
        difficulty=difficulty,
    )
    spec = load_prompt(*QUESTION_GENERATE)
    prompt_row = get_or_create_prompt_version(db, spec)
    db.commit()

    result = get_ai_gateway(db).complete_json(
        purpose="question_generate",
        system_prompt=render_system_prompt(spec),
        payload=payload,
        schema_model=QuestionGenerateOutput,
        prompt_version_id=prompt_row.id,
        cache_input=payload,
    )
    from ...utils.text import question_hash, simhash64

    lookup = category_lookup(db)
    origin_ref = (
        f"ai:generate:knowledge:{knowledge_id}"
        if knowledge_id is not None
        else f"ai:generate:topic:{topic_text[:60]}"
    )
    items: list[PendingItem] = []
    skipped = 0
    seen_hashes: set[str] = set()
    for raw in result.get("questions", [])[:count]:
        stem = str(raw.get("stem") or "").strip()
        if not stem:
            skipped += 1
            continue
        content_hash = question_hash(stem)
        if content_hash in seen_hashes:
            skipped += 1
            continue
        seen_hashes.add(content_hash)
        exists = db.scalar(
            select(Question.id).where(
                Question.content_hash == content_hash, Question.is_deleted == 0
            )
        ) or db.scalar(
            select(PendingItem.id).where(
                PendingItem.content_hash == content_hash,
                PendingItem.item_type == "question",
                PendingItem.status == "pending",
            )
        )
        if exists:
            skipped += 1
            continue

        tags = [
            str(tag).strip()
            for tag in raw.get("tags", []) or []
            if str(tag).strip()
        ][:5]
        generated_path = str(raw.get("category_path") or "").strip().strip("/")
        category = lookup.get(generated_path) if generated_path else None
        confidence = raw.get("confidence")
        meta: dict[str, Any] = {
            "item_type": "question",
            "tags": tags,
            "tag_ids": [],
            "category_path": generated_path or None,
            "category_id": category.id if category else None,
            "difficulty": raw.get("difficulty"),
            "frequency": raw.get("frequency"),
            "key_points": [
                str(point).strip()
                for point in raw.get("key_points", []) or []
                if str(point).strip()
            ][:8],
            "confidence": confidence,
            "matched_rules": [],
            "ai_generated": True,
        }
        item = PendingItem(
            item_type="question",
            source_type="ai",
            origin_ref=origin_ref,
            raw_text=json.dumps(raw, ensure_ascii=False),
            stem=stem,
            answer=str(raw.get("answer") or "").strip() or None,
            suggested_meta=json.dumps(meta, ensure_ascii=False),
            parse_confidence=(
                float(confidence)
                if isinstance(confidence, (int, float))
                else 0.7
            ),
            content_hash=content_hash,
            simhash=simhash64(stem),
            status="pending",
        )
        db.add(item)
        db.flush()
        audit(
            db,
            "ai_generate_question",
            "pending",
            item.id,
            {"topic": topic_text, "knowledge_id": knowledge_id},
        )
        items.append(item)
    db.commit()

    return {
        "requested": count,
        "generated": len(items),
        "skipped": skipped,
        "topic": topic_text,
        "knowledge_id": knowledge_id,
        "items": [serialize_pending(db, item) for item in items],
    }
