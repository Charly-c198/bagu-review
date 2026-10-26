"""M3 AI 增强共用工具：输入裁剪、分类/标签上下文、题目上下文（不含私人笔记）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Category, Question, QuestionCategory, QuestionTag, Tag
from ...services.categories import category_map, category_path
from ...services.serializers import json_list


def fit_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    """按字符数粗略裁剪最长的字符串字段，避免超出发送上限。"""
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


def taxonomy_context(
    db: Session, *, max_paths: int = 120, max_tags: int = 120
) -> dict[str, Any]:
    """现有分类路径与标签，帮助模型沿用既有体系而不是另造一套。"""
    mapping = category_map(db)
    paths = sorted(
        {
            path
            for category_id in mapping
            if (path := category_path(category_id, mapping))
        }
    )
    tags = list(
        db.scalars(select(Tag.name).order_by(Tag.name).limit(max_tags)).all()
    )
    return {
        "category_paths": paths[-max_paths:],
        "tags": tags,
    }


def question_context(
    db: Session,
    question: Question,
    *,
    include_answer: bool = True,
) -> dict[str, Any]:
    """题目上下文：只含题目内容、分类与标签；绝不包含 notes 或个人答题原文。"""
    mapping = category_map(db)
    category_ids = list(
        db.scalars(
            select(QuestionCategory.category_id).where(
                QuestionCategory.question_id == question.id
            )
        ).all()
    )
    tags = list(
        db.scalars(
            select(Tag.name)
            .join(QuestionTag, QuestionTag.tag_id == Tag.id)
            .where(QuestionTag.question_id == question.id)
            .order_by(Tag.name)
        ).all()
    )
    payload: dict[str, Any] = {
        "stem": question.stem,
        "categories": [category_path(cid, mapping) for cid in category_ids],
        "tags": tags,
        "difficulty": question.difficulty,
        "frequency": question.frequency,
    }
    if include_answer:
        payload["answer"] = question.answer or ""
        payload["key_points"] = json_list(question.key_points)
    return payload


def category_lookup(db: Session) -> dict[str, Category]:
    mapping = category_map(db)
    return {
        path: mapping[category_id]
        for category_id in mapping
        if (path := category_path(category_id, mapping))
    }
