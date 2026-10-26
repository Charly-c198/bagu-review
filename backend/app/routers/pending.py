"""统一待审区：编辑、通过、拒绝、合并、批量通过。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import (
    KnowledgePoint,
    PendingItem,
    Question,
    QuestionKnowledge,
    ReviewSchedule,
    User,
)
from ..schemas import ApproveRequest, MergeRequest, PendingUpdate, RejectRequest
from ..security import get_current_user
from ..services.ai.quality import (
    latest_checks,
    quality_summaries,
    quality_summary,
    serialize_quality_check,
)
from ..services.ai.suggestions import latest_suggestions, serialize_suggestion
from ..services.audit import audit
from ..services.categories import (
    category_map,
    category_path,
    descendant_ids,
    get_or_create_category_path,
)
from ..services.dedupe import (
    find_exact_knowledge,
    find_exact_question,
    find_near_knowledge,
    find_near_pending,
    find_near_questions,
)
from ..services.ingest import (
    _add_knowledge_origin,
    _add_question_origin,
)
from ..services.knowledge_extract import build_keypoints_candidate
from ..services.serializers import (
    json_list,
    json_obj,
    serialize_knowledge,
    serialize_pending,
    serialize_question,
)
from ..services.settings_service import get_settings
from ..services.taxonomy import set_question_taxonomy
from ..utils.text import knowledge_hash, question_hash, simhash64
from ..utils.timeutil import utcnow

router = APIRouter(prefix="/pending", tags=["pending"])


class BulkApproveRequest(BaseModel):
    ids: list[int]


def _get_pending(db: Session, item_id: int) -> PendingItem:
    item = db.get(PendingItem, item_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "待审项不存在")
    return item


def _similar_items(db: Session, item: PendingItem) -> list[dict]:
    settings = get_settings(db)
    threshold = int(settings.get("dedupe.simhash_threshold", 3))
    result: list[dict] = []
    if item.item_type == "question":
        if item.content_hash:
            exact = find_exact_question(db, item.content_hash)
            if exact:
                result.append(
                    {
                        "type": "question",
                        "id": exact.id,
                        "title": exact.stem,
                        "distance": 0,
                        "exact": True,
                    }
                )
        for question, distance in find_near_questions(
            db, item.simhash or "", threshold=threshold
        ):
            result.append(
                {
                    "type": "question",
                    "id": question.id,
                    "title": question.stem,
                    "distance": distance,
                    "exact": False,
                }
            )
    else:
        if item.content_hash:
            exact = find_exact_knowledge(db, item.content_hash)
            if exact:
                result.append(
                    {
                        "type": "knowledge",
                        "id": exact.id,
                        "title": exact.title,
                        "distance": 0,
                        "exact": True,
                    }
                )
        for knowledge, distance in find_near_knowledge(
            db, item.simhash or "", threshold=threshold
        ):
            result.append(
                {
                    "type": "knowledge",
                    "id": knowledge.id,
                    "title": knowledge.title,
                    "distance": distance,
                    "exact": False,
                }
            )
    for pending, distance in find_near_pending(
        db, item.simhash or "", item.item_type, threshold=threshold
    ):
        if pending.id == item.id:
            continue
        result.append(
            {
                "type": "pending",
                "id": pending.id,
                "title": pending.stem or pending.knowledge_title or "",
                "distance": distance,
                "exact": False,
            }
        )
    return result[:10]


def _suggested_knowledge(db: Session, item: PendingItem) -> list[dict]:
    """根据建议分类/标签给题目推荐已有知识，供审核人勾选关联。"""
    meta = json_obj(item.suggested_meta)
    conditions = []
    category_id = meta.get("category_id")
    if category_id:
        ids = descendant_ids(db, int(category_id))
        if ids:
            conditions.append(KnowledgePoint.category_id.in_(ids))
    for tag in (meta.get("tags") or [])[:3]:
        pattern = f"%{tag}%"
        conditions.append(KnowledgePoint.title.like(pattern))
        conditions.append(KnowledgePoint.content.like(pattern))
    if not conditions:
        return []
    stmt = select(KnowledgePoint).where(
        KnowledgePoint.status == "active",
        KnowledgePoint.is_deleted == 0,
        or_(*conditions),
    )
    rows = db.scalars(stmt.order_by(KnowledgePoint.id).limit(8)).all()
    mapping = category_map(db)
    return [
        {
            "id": row.id,
            "title": row.title,
            "kind": row.kind,
            "category_path": category_path(row.category_id, mapping),
            "relation_type": "related",
        }
        for row in rows[:5]
    ]


@router.get("")
def list_pending(
    item_type: str | None = None,
    source_type: str | None = None,
    status: str = "pending",
    q: str | None = None,
    low_confidence: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(PendingItem)
    if item_type and item_type != "all":
        if item_type not in ("question", "knowledge"):
            raise ApiError(400, "VALIDATION_ERROR", "item_type 不合法")
        stmt = stmt.where(PendingItem.item_type == item_type)
    if source_type and source_type != "all":
        stmt = stmt.where(PendingItem.source_type == source_type)
    if status and status != "all":
        if status not in ("pending", "approved", "rejected", "merged"):
            raise ApiError(400, "VALIDATION_ERROR", "status 不合法")
        stmt = stmt.where(PendingItem.status == status)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                PendingItem.stem.like(pattern),
                PendingItem.knowledge_title.like(pattern),
                PendingItem.origin_ref.like(pattern),
            )
        )
    if low_confidence:
        stmt = stmt.where(
            or_(PendingItem.parse_confidence.is_(None), PendingItem.parse_confidence < 0.6)
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(
            (PendingItem.status != "pending"),
            func.coalesce(PendingItem.parse_confidence, 1.0).asc(),
            PendingItem.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    counts = {
        "question": int(
            db.scalar(
                select(func.count(PendingItem.id)).where(
                    PendingItem.status == "pending",
                    PendingItem.item_type == "question",
                )
            )
            or 0
        ),
        "knowledge": int(
            db.scalar(
                select(func.count(PendingItem.id)).where(
                    PendingItem.status == "pending",
                    PendingItem.item_type == "knowledge",
                )
            )
            or 0
        ),
    }
    counts["total"] = counts["question"] + counts["knowledge"]
    quality = quality_summaries(db, "pending", [row.id for row in rows])
    items = []
    for row in rows:
        data = serialize_pending(db, row)
        data["quality"] = quality[row.id]
        items.append(data)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "counts": counts,
        }
    )


@router.get("/{item_id}")
def get_pending(
    item_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    item = _get_pending(db, item_id)
    data = serialize_pending(db, item)
    data["similar"] = _similar_items(db, item)
    data["quality"] = quality_summary(db, "pending", item_id)
    data["quality_checks"] = [
        serialize_quality_check(row)
        for row in latest_checks(db, "pending", item_id)
    ]
    data["ai_suggestions"] = [
        serialize_suggestion(row)
        for row in latest_suggestions(
            db, target_type="pending", target_id=item_id, limit=10
        )
    ]
    if item.item_type == "question":
        data["suggested_knowledge"] = _suggested_knowledge(db, item)
    return ok(data)


@router.patch("/{item_id}")
def update_pending(
    item_id: int,
    payload: PendingUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    item = _get_pending(db, item_id)
    if item.status != "pending":
        raise ApiError(409, "CONFLICT", "只能编辑待审中的条目")
    fields = payload.model_fields_set
    if "stem" in fields:
        item.stem = payload.stem
    if "answer" in fields:
        item.answer = payload.answer
    if "knowledge_title" in fields:
        item.knowledge_title = payload.knowledge_title
    if "knowledge_content" in fields:
        item.knowledge_content = payload.knowledge_content
    if "suggested_meta" in fields and payload.suggested_meta is not None:
        item.suggested_meta = json.dumps(payload.suggested_meta, ensure_ascii=False)
    if "reviewer_note" in fields:
        item.reviewer_note = payload.reviewer_note
    if item.item_type == "question" and item.stem:
        item.content_hash = question_hash(item.stem)
        item.simhash = simhash64(item.stem)
    elif item.item_type == "knowledge" and item.knowledge_title and item.knowledge_content:
        item.content_hash = knowledge_hash(item.knowledge_title, item.knowledge_content)
        item.simhash = simhash64(
            f"{item.knowledge_title}\n{item.knowledge_content}"
        )
    audit(db, "pending_update", "pending", item.id, sorted(fields))
    db.commit()
    return ok(serialize_pending(db, item), "已保存")


def _resolve_links(db: Session, batch_id: int | None) -> int:
    if not batch_id:
        return 0
    items = db.scalars(
        select(PendingItem).where(
            PendingItem.import_batch_id == batch_id,
            PendingItem.status.in_(("approved", "merged")),
        )
    ).all()
    question_refs: dict[str, int] = {}
    knowledge_refs: dict[str, int] = {}
    for item in items:
        meta = json_obj(item.suggested_meta)
        if item.item_type == "question" and item.created_question_id:
            ref = meta.get("question_ref")
            if ref:
                question_refs[str(ref)] = item.created_question_id
        if item.item_type == "knowledge" and item.created_knowledge_id:
            ref = meta.get("knowledge_ref")
            if ref:
                knowledge_refs[str(ref)] = item.created_knowledge_id
    created = 0
    seen: set[tuple[int, int, str]] = set()
    for item in items:
        meta = json_obj(item.suggested_meta)
        if item.item_type == "question" and item.created_question_id:
            for link in meta.get("link_knowledge_refs", []) or []:
                knowledge_id = knowledge_refs.get(str(link.get("ref")))
                relation = link.get("relation_type", "related")
                if relation not in ("related", "prerequisite", "derived_from"):
                    relation = "related"
                key = (item.created_question_id, knowledge_id, relation)
                if (
                    knowledge_id
                    and key not in seen
                    and db.get(QuestionKnowledge, key) is None
                ):
                    seen.add(key)
                    db.add(
                        QuestionKnowledge(
                            question_id=item.created_question_id,
                            knowledge_id=knowledge_id,
                            relation_type=relation,
                        )
                    )
                    created += 1
        if item.item_type == "knowledge" and item.created_knowledge_id:
            for link in meta.get("link_question_refs", []) or []:
                question_id = question_refs.get(str(link.get("ref")))
                relation = link.get("relation_type", "related")
                if relation not in ("related", "prerequisite", "derived_from"):
                    relation = "related"
                key = (question_id, item.created_knowledge_id, relation)
                if (
                    question_id
                    and key not in seen
                    and db.get(QuestionKnowledge, key) is None
                ):
                    seen.add(key)
                    db.add(
                        QuestionKnowledge(
                            question_id=question_id,
                            knowledge_id=item.created_knowledge_id,
                            relation_type=relation,
                        )
                    )
                    created += 1
    return created


def _approve_question(db: Session, item: PendingItem, payload: ApproveRequest) -> Question:
    meta = json_obj(item.suggested_meta)
    stem = (payload.stem if payload.stem is not None else item.stem) or ""
    stem = stem.strip()
    if not stem:
        raise ApiError(400, "VALIDATION_ERROR", "题干不能为空")
    content_hash = question_hash(stem)
    duplicate = db.scalar(
        select(Question).where(
            Question.content_hash == content_hash, Question.is_deleted == 0
        )
    )
    if duplicate:
        raise ApiError(
            409,
            "CONFLICT",
            f"题库中已存在相同题干（题目 #{duplicate.id}），请使用合并",
            {"question_id": duplicate.id},
        )
    answer = payload.answer if payload.answer is not None else item.answer
    key_points = (
        payload.key_points
        if payload.key_points is not None
        else json_list(json.dumps(meta.get("key_points", [])))
        if meta.get("key_points")
        else []
    )
    notes = payload.notes if payload.notes is not None else meta.get("notes")
    difficulty = (
        payload.difficulty if payload.difficulty is not None else meta.get("difficulty")
    )
    frequency = (
        payload.frequency if payload.frequency is not None else meta.get("frequency")
    )
    question = Question(
        stem=stem,
        answer=answer,
        key_points=json.dumps(key_points, ensure_ascii=False) if key_points else None,
        notes=notes,
        difficulty=difficulty,
        frequency=frequency,
        status="active",
        source_type=item.source_type,
        content_hash=content_hash,
        simhash=simhash64(stem),
    )
    db.add(question)
    db.flush()

    category_ids: list[int] = []
    category_path = payload.category_path
    if payload.category_id:
        category_ids.append(payload.category_id)
    elif category_path:
        category_ids.append(get_or_create_category_path(db, category_path.split("/")).id)
    elif meta.get("category_id"):
        category_ids.append(int(meta["category_id"]))
    elif meta.get("category_path"):
        category_ids.append(
            get_or_create_category_path(db, str(meta["category_path"]).split("/")).id
        )
    tags = payload.tags if payload.tags is not None else meta.get("tags", [])
    tag_ids = payload.tag_ids if payload.tag_ids is not None else meta.get("tag_ids", [])
    companies = (
        payload.companies if payload.companies is not None else meta.get("companies", [])
    )
    set_question_taxonomy(
        db,
        question.id,
        category_ids=category_ids,
        tags=tags,
        tag_ids=tag_ids,
        companies=companies,
        replace=True,
    )
    db.add(ReviewSchedule(question_id=question.id))
    origin_ref = item.origin_ref or f"pending:{item.id}"
    _add_question_origin(
        db,
        question.id,
        item.source_type,
        origin_ref=origin_ref,
        raw_snapshot=item.raw_text,
        content_hash=content_hash,
        import_batch_id=item.import_batch_id,
        crawl_task_id=item.crawl_task_id,
    )
    item.status = "approved"
    item.created_question_id = question.id
    item.reviewed_at = utcnow()
    audit(db, "pending_approve", "question", question.id, {"pending_id": item.id})

    for knowledge_id in dict.fromkeys(payload.knowledge_ids):
        knowledge = db.get(KnowledgePoint, knowledge_id)
        if knowledge is None or knowledge.is_deleted or knowledge.status != "active":
            continue
        key = (question.id, knowledge_id, payload.relation_type)
        if db.get(QuestionKnowledge, key) is None:
            db.add(
                QuestionKnowledge(
                    question_id=question.id,
                    knowledge_id=knowledge_id,
                    relation_type=payload.relation_type,
                )
            )

    # 从结构化要点生成知识候选，仍进入待审区。
    candidate = build_keypoints_candidate(stem, key_points, answer)
    if candidate:
        candidate_hash = knowledge_hash(candidate.title, candidate.content)
        exists = find_exact_knowledge(db, candidate_hash)
        if exists is None:
            candidate_meta = {
                "item_type": "knowledge",
                "knowledge_category_id": category_ids[0] if category_ids else None,
                "confidence": 0.4,
            }
            db.add(
                PendingItem(
                    item_type="knowledge",
                    source_type=item.source_type,
                    import_batch_id=item.import_batch_id,
                    crawl_task_id=item.crawl_task_id,
                    origin_ref=f"{origin_ref}#keypoints",
                    raw_text=candidate.raw,
                    knowledge_title=candidate.title,
                    knowledge_content=candidate.content,
                    suggested_meta=json.dumps(candidate_meta, ensure_ascii=False),
                    parse_confidence=0.4,
                    content_hash=candidate_hash,
                    simhash=simhash64(f"{candidate.title}\n{candidate.content}"),
                    status="pending",
                )
            )
    return question


def _approve_knowledge(
    db: Session, item: PendingItem, payload: ApproveRequest
) -> KnowledgePoint:
    meta = json_obj(item.suggested_meta)
    title = (
        payload.knowledge_title
        if payload.knowledge_title is not None
        else item.knowledge_title
    ) or ""
    content = (
        payload.knowledge_content
        if payload.knowledge_content is not None
        else item.knowledge_content
    ) or ""
    if not title.strip() or not content.strip():
        raise ApiError(400, "VALIDATION_ERROR", "知识标题和内容不能为空")
    content_hash = knowledge_hash(title, content)
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
            f"知识库中已存在相同条目（#{duplicate.id}），请使用合并",
            {"knowledge_id": duplicate.id},
        )
    category_id = payload.category_id
    if payload.category_path:
        category_id = get_or_create_category_path(
            db, payload.category_path.split("/")
        ).id
    elif category_id is None and meta.get("knowledge_category_id"):
        category_id = int(meta["knowledge_category_id"])
    elif category_id is None and meta.get("category_path"):
        category_id = get_or_create_category_path(
            db, str(meta["category_path"]).split("/")
        ).id
    aliases = payload.aliases if payload.aliases is not None else meta.get("aliases", [])
    knowledge = KnowledgePoint(
        title=title.strip(),
        content=content.strip(),
        kind=payload.kind or meta.get("kind") or "concept",
        category_id=category_id,
        aliases=json.dumps(aliases, ensure_ascii=False) if aliases else None,
        status="active",
        source_type=item.source_type,
        content_hash=content_hash,
        simhash=simhash64(f"{title}\n{content}"),
    )
    db.add(knowledge)
    db.flush()
    origin_ref = item.origin_ref or f"pending:{item.id}"
    _add_knowledge_origin(
        db,
        knowledge.id,
        item.source_type,
        origin_ref=origin_ref,
        raw_snapshot=item.raw_text,
        content_hash=content_hash,
        import_batch_id=item.import_batch_id,
        crawl_task_id=item.crawl_task_id,
    )
    item.status = "approved"
    item.created_knowledge_id = knowledge.id
    item.reviewed_at = utcnow()
    audit(db, "pending_approve", "knowledge", knowledge.id, {"pending_id": item.id})
    return knowledge


@router.post("/{item_id}/approve")
def approve_pending(
    item_id: int,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    item = _get_pending(db, item_id)
    if item.status != "pending":
        raise ApiError(409, "CONFLICT", "该条目已处理，不能重复通过")
    if item.item_type == "question":
        question = _approve_question(db, item, payload)
        db.flush()
        _resolve_links(db, item.import_batch_id)
        db.commit()
        db.refresh(question)
        return ok(serialize_question(db, question, detail=True), "已通过并写入题库")
    knowledge = _approve_knowledge(db, item, payload)
    db.flush()
    _resolve_links(db, item.import_batch_id)
    db.commit()
    db.refresh(knowledge)
    return ok(serialize_knowledge(db, knowledge, detail=True), "已通过并写入知识库")


@router.post("/{item_id}/reject")
def reject_pending(
    item_id: int,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    item = _get_pending(db, item_id)
    if item.status != "pending":
        raise ApiError(409, "CONFLICT", "该条目已处理")
    item.status = "rejected"
    item.reviewer_note = payload.reviewer_note
    item.reviewed_at = utcnow()
    audit(db, "pending_reject", "pending", item.id, payload.reviewer_note)
    db.commit()
    return ok(serialize_pending(db, item), "已拒绝，保留审计记录")


@router.post("/{item_id}/merge")
def merge_pending(
    item_id: int,
    payload: MergeRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    item = _get_pending(db, item_id)
    if item.status != "pending":
        raise ApiError(409, "CONFLICT", "该条目已处理")
    if payload.target_type == "question":
        if item.item_type != "question":
            raise ApiError(400, "VALIDATION_ERROR", "知识条目不能合并到题目")
        target = db.get(Question, payload.target_id)
        if target is None or target.is_deleted:
            raise ApiError(404, "NOT_FOUND", "目标题目不存在")
        _add_question_origin(
            db,
            target.id,
            item.source_type,
            origin_ref=item.origin_ref or f"pending:{item.id}",
            raw_snapshot=item.raw_text,
            content_hash=item.content_hash,
            import_batch_id=item.import_batch_id,
            crawl_task_id=item.crawl_task_id,
        )
        item.dup_of = target.id
        item.created_question_id = target.id
    elif payload.target_type == "knowledge":
        if item.item_type != "knowledge":
            raise ApiError(400, "VALIDATION_ERROR", "题目不能合并到知识条目")
        target = db.get(KnowledgePoint, payload.target_id)
        if target is None or target.is_deleted:
            raise ApiError(404, "NOT_FOUND", "目标知识不存在")
        _add_knowledge_origin(
            db,
            target.id,
            item.source_type,
            origin_ref=item.origin_ref or f"pending:{item.id}",
            raw_snapshot=item.raw_text,
            content_hash=item.content_hash,
            import_batch_id=item.import_batch_id,
            crawl_task_id=item.crawl_task_id,
        )
        item.dup_of_knowledge_id = target.id
        item.created_knowledge_id = target.id
    else:
        target = db.get(PendingItem, payload.target_id)
        if target is None or target.status != "pending":
            raise ApiError(404, "NOT_FOUND", "目标待审项不存在或已处理")
        if target.item_type != item.item_type:
            raise ApiError(400, "VALIDATION_ERROR", "只能合并同类型待审项")
        item.dup_of_pending_id = target.id
    item.status = "merged"
    item.reviewer_note = payload.reviewer_note
    item.reviewed_at = utcnow()
    audit(
        db,
        "pending_merge",
        "pending",
        item.id,
        {"target_type": payload.target_type, "target_id": payload.target_id},
    )
    db.commit()
    return ok(serialize_pending(db, item), "已合并，来源已保留")


@router.post("/bulk-approve")
def bulk_approve(
    payload: BulkApproveRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    results = []
    for item_id in payload.ids:
        try:
            item = _get_pending(db, item_id)
            if item.status != "pending":
                results.append({"id": item_id, "ok": False, "message": "已处理"})
                continue
            empty = ApproveRequest()
            if item.item_type == "question":
                question = _approve_question(db, item, empty)
                db.flush()
                _resolve_links(db, item.import_batch_id)
                db.commit()
                results.append({"id": item_id, "ok": True, "question_id": question.id})
            else:
                knowledge = _approve_knowledge(db, item, empty)
                db.flush()
                _resolve_links(db, item.import_batch_id)
                db.commit()
                results.append(
                    {"id": item_id, "ok": True, "knowledge_id": knowledge.id}
                )
        except ApiError as exc:
            db.rollback()
            results.append({"id": item_id, "ok": False, "message": exc.message})
    db.commit()
    return ok({"results": results}, "批量审核完成")
