"""规则打标：tag_rules 匹配 → suggested_meta。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, Tag, TagRule
from .categories import get_or_create_category_path

SEED_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "tag_rules.yaml"
logger = logging.getLogger("bajiu.tagging")


def _empty_meta(item_type: str = "question") -> dict[str, Any]:
    return {
        "item_type": item_type,
        "tags": [],
        "tag_ids": [],
        "category_id": None,
        "knowledge_category_id": None,
        "category_path": None,
        "difficulty": None,
        "frequency": None,
        "confidence": 0.0,
        "matched_rules": [],
    }


def suggest_meta(
    db: Session,
    text: str,
    *,
    item_type: str = "question",
    title: str | None = None,
) -> dict[str, Any]:
    meta = _empty_meta(item_type)
    haystack = f"{title or ''}\n{text or ''}"
    if not haystack.strip():
        return meta

    rules = db.scalars(
        select(TagRule).where(TagRule.enabled == 1).order_by(TagRule.id)
    ).all()
    tag_names: list[str] = []
    tag_ids: list[int] = []
    matched: list[int] = []
    best_category: tuple[float, int] | None = None
    best_difficulty: tuple[float, int] | None = None
    best_frequency: tuple[float, str] | None = None
    total_weight = 0.0

    for rule in rules:
        matched_rule = False
        if rule.match_type == "regex":
            try:
                matched_rule = re.search(rule.keyword, haystack, re.IGNORECASE) is not None
            except re.error:
                matched_rule = False
        else:
            matched_rule = rule.keyword.lower() in haystack.lower()
        if not matched_rule:
            continue

        matched.append(rule.id)
        total_weight += max(0.1, rule.weight)
        if rule.tag_id:
            tag = db.get(Tag, rule.tag_id)
            if tag and tag.name not in tag_names:
                tag_names.append(tag.name)
                tag_ids.append(tag.id)
        if rule.category_id:
            if best_category is None or rule.weight > best_category[0]:
                best_category = (rule.weight, rule.category_id)
        if rule.difficulty is not None:
            if best_difficulty is None or rule.weight > best_difficulty[0]:
                best_difficulty = (rule.weight, rule.difficulty)
        if rule.frequency:
            if best_frequency is None or rule.weight > best_frequency[0]:
                best_frequency = (rule.weight, rule.frequency)

    if not matched:
        return meta

    category = db.get(Category, best_category[1]) if best_category else None
    meta["tags"] = tag_names
    meta["tag_ids"] = tag_ids
    if category:
        path_parts: list[str] = []
        current: Category | None = category
        seen: set[int] = set()
        while current and current.id not in seen:
            seen.add(current.id)
            path_parts.append(current.name)
            current = db.get(Category, current.parent_id) if current.parent_id else None
        meta["category_path"] = "/".join(reversed(path_parts))
        if item_type == "knowledge":
            meta["knowledge_category_id"] = category.id
        else:
            meta["category_id"] = category.id
    if best_difficulty:
        meta["difficulty"] = best_difficulty[1]
    if best_frequency:
        meta["frequency"] = best_frequency[1]
    meta["confidence"] = round(min(0.95, 0.45 + 0.1 * len(matched)), 2)
    meta["matched_rules"] = matched
    return meta


def load_seed_rules(db: Session) -> int:
    """tag_rules 为空时从 YAML 加载种子规则，返回新增条数。"""
    if db.scalar(select(TagRule.id).limit(1)) is not None:
        return 0
    if not SEED_PATH.exists():
        return 0
    try:
        data = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        # 配置错误不能静默吞掉：否则打标规则整体失效却无任何提示。
        logger.warning("种子标签规则加载失败 %s：%s", SEED_PATH, exc)
        return 0
    rules = data.get("rules") or []
    created = 0
    for raw in rules:
        if not isinstance(raw, dict) or not raw.get("keyword"):
            continue
        category_id = None
        if raw.get("category_path"):
            parts = str(raw["category_path"]).split("/")
            category_id = get_or_create_category_path(db, parts).id
        tag_names = raw.get("tags") or []
        if isinstance(tag_names, str):
            tag_names = [x.strip() for x in tag_names.split(",") if x.strip()]
        if not tag_names:
            db.add(
                TagRule(
                    keyword=str(raw["keyword"]),
                    match_type=str(raw.get("match_type", "contains")),
                    tag_id=None,
                    category_id=category_id,
                    difficulty=raw.get("difficulty"),
                    frequency=raw.get("frequency"),
                    weight=float(raw.get("weight", 1.0)),
                    enabled=1,
                )
            )
            created += 1
        else:
            for name in tag_names:
                tag = db.scalar(select(Tag).where(Tag.name == str(name)))
                if tag is None:
                    tag = Tag(name=str(name))
                    db.add(tag)
                    db.flush()
                db.add(
                    TagRule(
                        keyword=str(raw["keyword"]),
                        match_type=str(raw.get("match_type", "contains")),
                        tag_id=tag.id,
                        category_id=category_id,
                        difficulty=raw.get("difficulty"),
                        frequency=raw.get("frequency"),
                        weight=float(raw.get("weight", 1.0)),
                        enabled=1,
                    )
                )
                created += 1
    db.commit()
    return created
