"""运行设置与规则打标管理路由。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import Category, Tag, TagRule, User
from ..schemas import TagRuleCreate, TagRuleUpdate
from ..security import get_current_user
from ..services.audit import audit
from ..services.categories import category_map, category_path
from ..services.settings_service import get_settings, update_settings

router = APIRouter(tags=["settings"])


@router.get("/settings")
def read_settings(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(get_settings(db))


@router.patch("/settings")
def patch_settings(
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    values = update_settings(db, payload)
    audit(db, "settings_update", "settings", None, sorted(payload.keys()))
    db.commit()
    return ok(values, "设置已保存")


def _validate_rule(payload: TagRuleCreate | TagRuleUpdate, db: Session) -> None:
    if payload.match_type == "regex" and payload.keyword:
        try:
            re.compile(payload.keyword)
        except re.error as exc:
            raise ApiError(400, "VALIDATION_ERROR", f"正则表达式无效：{exc}") from exc
    if getattr(payload, "tag_id", None):
        if db.get(Tag, payload.tag_id) is None:
            raise ApiError(404, "NOT_FOUND", "标签不存在")
    if getattr(payload, "tag_ids", None):
        for tag_id in payload.tag_ids:
            if db.get(Tag, tag_id) is None:
                raise ApiError(404, "NOT_FOUND", f"标签 #{tag_id} 不存在")
    if payload.category_id and db.get(Category, payload.category_id) is None:
        raise ApiError(404, "NOT_FOUND", "分类不存在")


def _serialize_rule(db: Session, rule: TagRule, mapping: dict[int, Category]) -> dict:
    tag = db.get(Tag, rule.tag_id) if rule.tag_id else None
    return {
        "id": rule.id,
        "keyword": rule.keyword,
        "match_type": rule.match_type,
        "tag_id": rule.tag_id,
        "tag_name": tag.name if tag else None,
        "category_id": rule.category_id,
        "category_path": category_path(rule.category_id, mapping),
        "difficulty": rule.difficulty,
        "frequency": rule.frequency,
        "weight": rule.weight,
        "enabled": bool(rule.enabled),
        "created_at": rule.created_at.isoformat(),
    }


@router.get("/tag-rules")
def list_tag_rules(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    mapping = category_map(db)
    rules = db.scalars(select(TagRule).order_by(TagRule.id)).all()
    return ok([_serialize_rule(db, rule, mapping) for rule in rules])


@router.post("/tag-rules")
def create_tag_rule(
    payload: TagRuleCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _validate_rule(payload, db)
    created = []
    tag_ids = payload.tag_ids or [None]
    for tag_id in tag_ids:
        rule = TagRule(
            keyword=payload.keyword,
            match_type=payload.match_type,
            tag_id=tag_id,
            category_id=payload.category_id,
            difficulty=payload.difficulty,
            frequency=payload.frequency,
            weight=payload.weight,
            enabled=1 if payload.enabled else 0,
        )
        db.add(rule)
        db.flush()
        created.append(rule.id)
    audit(db, "tag_rule_create", "tag_rule", created[0], {"ids": created})
    db.commit()
    return ok({"ids": created}, "规则已创建")


@router.patch("/tag-rules/{rule_id}")
def update_tag_rule(
    rule_id: int,
    payload: TagRuleUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rule = db.get(TagRule, rule_id)
    if rule is None:
        raise ApiError(404, "NOT_FOUND", "规则不存在")
    merged = TagRuleUpdate(
        keyword=payload.keyword if payload.keyword is not None else rule.keyword,
        match_type=payload.match_type if payload.match_type is not None else rule.match_type,
        category_id=payload.category_id if payload.category_id is not None else rule.category_id,
        difficulty=payload.difficulty if payload.difficulty is not None else rule.difficulty,
        frequency=payload.frequency if payload.frequency is not None else rule.frequency,
        weight=payload.weight if payload.weight is not None else rule.weight,
        enabled=payload.enabled if payload.enabled is not None else bool(rule.enabled),
    )
    if payload.tag_id is not None:
        merged.tag_id = payload.tag_id
    _validate_rule(merged, db)
    fields = payload.model_fields_set
    if "keyword" in fields:
        rule.keyword = payload.keyword
    if "match_type" in fields:
        rule.match_type = payload.match_type
    if "tag_id" in fields:
        rule.tag_id = payload.tag_id
    if "category_id" in fields:
        rule.category_id = payload.category_id
    if "difficulty" in fields:
        rule.difficulty = payload.difficulty
    if "frequency" in fields:
        rule.frequency = payload.frequency
    if "weight" in fields:
        rule.weight = payload.weight
    if "enabled" in fields:
        rule.enabled = 1 if payload.enabled else 0
    audit(db, "tag_rule_update", "tag_rule", rule.id, sorted(fields))
    db.commit()
    mapping = category_map(db)
    return ok(_serialize_rule(db, rule, mapping), "规则已保存")


@router.delete("/tag-rules/{rule_id}")
def delete_tag_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rule = db.get(TagRule, rule_id)
    if rule is None:
        raise ApiError(404, "NOT_FOUND", "规则不存在")
    audit(db, "tag_rule_delete", "tag_rule", rule.id, {"keyword": rule.keyword})
    db.delete(rule)
    db.commit()
    return ok(None, "规则已删除")
