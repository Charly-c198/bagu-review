"""知识条目库路由。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import KnowledgeOrigin, KnowledgePoint, PendingItem, User
from ..schemas import KnowledgeCreate, KnowledgeUpdate
from ..security import get_current_user
from ..services.audit import audit
from ..services.batch_loader import serialize_knowledge_list
from ..services.categories import (
    category_map,
    category_path,
    descendant_ids,
    get_or_create_category_path,
)
from ..services.filters import parse_int_list, parse_str_list
from ..services.fts import search_knowledge_ids
from ..services.serializers import serialize_knowledge, serialize_pending
from ..services.tagging import suggest_meta
from ..utils.text import knowledge_hash, normalize_text, simhash64, truncate

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _get_knowledge(db: Session, knowledge_id: int) -> KnowledgePoint:
    knowledge = db.get(KnowledgePoint, knowledge_id)
    if knowledge is None:
        raise ApiError(404, "NOT_FOUND", "知识条目不存在")
    return knowledge


@router.get("")
def list_knowledge(
    q: str | None = None,
    category_id: int | None = None,
    kind: str | None = None,
    category_ids: str | None = None,
    kinds: str | None = None,
    status: str = "active",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(KnowledgePoint).where(KnowledgePoint.is_deleted == 0)
    if status != "all":
        if status not in ("draft", "active", "archived"):
            raise ApiError(400, "VALIDATION_ERROR", "status 不合法")
        stmt = stmt.where(KnowledgePoint.status == status)
    if kind:
        stmt = stmt.where(KnowledgePoint.kind == kind)
    kind_values = parse_str_list(kinds)
    if kind_values:
        stmt = stmt.where(KnowledgePoint.kind.in_(kind_values))
    if category_id:
        ids = descendant_ids(db, category_id)
        if not ids:
            stmt = stmt.where(KnowledgePoint.id == -1)
        else:
            stmt = stmt.where(KnowledgePoint.category_id.in_(ids))
    selected_categories = parse_int_list(category_ids)
    if selected_categories:
        ids = []
        for selected in selected_categories:
            ids.extend(descendant_ids(db, selected))
        ids = list(dict.fromkeys(ids))
        if not ids:
            stmt = stmt.where(KnowledgePoint.id == -1)
        else:
            stmt = stmt.where(KnowledgePoint.category_id.in_(ids))
    if q:
        pattern = f"%{q}%"
        fts_ids = search_knowledge_ids(db, q)
        if fts_ids is None:
            stmt = stmt.where(
                or_(
                    KnowledgePoint.title.like(pattern),
                    KnowledgePoint.content.like(pattern),
                    KnowledgePoint.aliases.like(pattern),
                )
            )
        else:
            stmt = stmt.where(KnowledgePoint.id.in_(fts_ids))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(KnowledgePoint.updated_at.desc(), KnowledgePoint.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        {
            "items": serialize_knowledge_list(db, list(rows)),
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("")
def create_knowledge(
    payload: KnowledgeCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    content_hash = knowledge_hash(payload.title, payload.content)
    title = normalize_text(payload.title)
    content = normalize_text(payload.content)
    duplicate = db.scalar(
        select(KnowledgePoint).where(
            KnowledgePoint.content_hash == content_hash,
            KnowledgePoint.is_deleted == 0,
        )
    )
    if duplicate:
        raise ApiError(
            409,
            "CONFLICT",
            f"知识库中已存在相同条目（#{duplicate.id}）",
            {"knowledge_id": duplicate.id},
        )
    category_id = payload.category_id
    if payload.category_path:
        category_id = get_or_create_category_path(
            db, payload.category_path.split("/")
        ).id
    aliases = payload.aliases
    if payload.send_to_pending:
        meta = suggest_meta(db, f"{title}\n{content}", item_type="knowledge")
        meta["kind"] = payload.kind
        meta["aliases"] = aliases
        if category_id:
            meta["knowledge_category_id"] = category_id
            meta["category_path"] = category_path(category_id, category_map(db))
        pending = PendingItem(
            item_type="knowledge",
            source_type="manual",
            origin_ref="manual",
            raw_text=content,
            knowledge_title=title,
            knowledge_content=content,
            suggested_meta=json.dumps(meta, ensure_ascii=False),
            parse_confidence=1.0,
            content_hash=content_hash,
            simhash=simhash64(f"{title}\n{content}"),
            status="pending",
        )
        db.add(pending)
        audit(db, "knowledge_create_pending", "pending", None, {"title": truncate(title, 80)})
        db.commit()
        db.refresh(pending)
        return ok(
            {"pending": True, "item": serialize_pending(db, pending)},
            "已进入待审区",
        )
    knowledge = KnowledgePoint(
        title=title,
        content=content,
        kind=payload.kind,
        category_id=category_id,
        aliases=json.dumps(payload.aliases, ensure_ascii=False) if payload.aliases else None,
        status=payload.status,
        source_type="manual",
        content_hash=content_hash,
        simhash=simhash64(f"{title}\n{content}"),
    )
    db.add(knowledge)
    db.flush()
    db.add(
        KnowledgeOrigin(
            knowledge_id=knowledge.id,
            source_type="manual",
            origin_ref="manual",
            raw_snapshot=payload.content,
            content_hash=content_hash,
        )
    )
    audit(
        db,
        "knowledge_create",
        "knowledge",
        knowledge.id,
        {"title": truncate(payload.title, 80)},
    )
    db.commit()
    db.refresh(knowledge)
    return ok(serialize_knowledge(db, knowledge, detail=True), "已创建")


@router.get("/{knowledge_id}")
def get_knowledge(
    knowledge_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    knowledge = _get_knowledge(db, knowledge_id)
    return ok(serialize_knowledge(db, knowledge, detail=True))


@router.patch("/{knowledge_id}")
def update_knowledge(
    knowledge_id: int,
    payload: KnowledgeUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    knowledge = _get_knowledge(db, knowledge_id)
    fields = payload.model_fields_set
    new_title = normalize_text(payload.title) if payload.title is not None else knowledge.title
    new_content = (
        normalize_text(payload.content) if payload.content is not None else knowledge.content
    )
    if new_title != knowledge.title or new_content != knowledge.content:
        content_hash = knowledge_hash(new_title, new_content)
        duplicate = db.scalar(
            select(KnowledgePoint).where(
                KnowledgePoint.content_hash == content_hash,
                KnowledgePoint.is_deleted == 0,
                KnowledgePoint.id != knowledge.id,
            )
        )
        if duplicate:
            raise ApiError(
                409,
                "CONFLICT",
                f"知识库中已存在相同条目（#{duplicate.id}）",
                {"knowledge_id": duplicate.id},
            )
        knowledge.content_hash = content_hash
        knowledge.simhash = simhash64(f"{new_title}\n{new_content}")
    if "title" in fields:
        knowledge.title = new_title
    if "content" in fields:
        knowledge.content = new_content
    if "kind" in fields:
        knowledge.kind = payload.kind
    if "aliases" in fields:
        knowledge.aliases = (
            json.dumps(payload.aliases, ensure_ascii=False) if payload.aliases else None
        )
    if payload.status is not None:
        knowledge.status = payload.status
    if "category_path" in fields and payload.category_path:
        knowledge.category_id = get_or_create_category_path(
            db, payload.category_path.split("/")
        ).id
    elif "category_id" in fields:
        knowledge.category_id = payload.category_id
    audit(db, "knowledge_update", "knowledge", knowledge.id, sorted(fields))
    db.commit()
    db.refresh(knowledge)
    return ok(serialize_knowledge(db, knowledge, detail=True), "已保存")


@router.delete("/{knowledge_id}")
def delete_knowledge(
    knowledge_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    knowledge = _get_knowledge(db, knowledge_id)
    knowledge.is_deleted = 1
    audit(db, "knowledge_delete", "knowledge", knowledge.id)
    db.commit()
    return ok(None, "已软删除")


@router.post("/{knowledge_id}/archive")
def archive_knowledge(
    knowledge_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    knowledge = _get_knowledge(db, knowledge_id)
    knowledge.status = "archived"
    audit(db, "knowledge_archive", "knowledge", knowledge.id)
    db.commit()
    return ok(serialize_knowledge(db, knowledge), "已归档")


@router.post("/{knowledge_id}/restore")
def restore_knowledge(
    knowledge_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    knowledge = _get_knowledge(db, knowledge_id)
    knowledge.status = "active"
    knowledge.is_deleted = 0
    audit(db, "knowledge_restore", "knowledge", knowledge.id)
    db.commit()
    return ok(serialize_knowledge(db, knowledge), "已恢复")


@router.get("/{knowledge_id}/history")
def knowledge_history(
    knowledge_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    knowledge = _get_knowledge(db, knowledge_id)
    detail = serialize_knowledge(db, knowledge, detail=True)
    return ok(
        {
            "origins": detail.get("origins", []),
            "questions": detail.get("questions", []),
        }
    )
