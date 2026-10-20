"""题库路由：CRUD、筛选、搜索、笔记、归档、题-知识关联。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import (
    Company,
    KnowledgePoint,
    Question,
    QuestionCategory,
    QuestionCompany,
    QuestionKnowledge,
    QuestionOrigin,
    QuestionTag,
    ReviewSchedule,
    Tag,
    User,
)
from ..schemas import LinkCreate, QuestionCreate, QuestionUpdate
from ..security import get_current_user
from ..services.audit import audit
from ..services.batch_loader import serialize_question_list
from ..services.categories import (
    descendant_ids,
    get_or_create_category_path,
)
from ..services.filters import apply_multi_filters, parse_int_list, parse_str_list
from ..services.fts import search_question_ids
from ..services.serializers import serialize_pending, serialize_question
from ..services.settings_service import get_settings
from ..services.tagging import suggest_meta
from ..services.taxonomy import set_question_taxonomy
from ..utils.text import normalize_text, question_hash, simhash64, truncate

router = APIRouter(prefix="/questions", tags=["questions"])


def _get_question(db: Session, question_id: int) -> Question:
    question = db.get(Question, question_id)
    if question is None:
        raise ApiError(404, "NOT_FOUND", "题目不存在")
    return question


def _category_question_subquery(db: Session, category_id: int):
    ids = descendant_ids(db, category_id)
    if not ids:
        return None
    return select(QuestionCategory.question_id).where(
        QuestionCategory.category_id.in_(ids)
    )


def _apply_mastery_filter(stmt, mastery: str):
    learned = select(ReviewSchedule.question_id).where(
        ReviewSchedule.first_reviewed_at.is_not(None)
    )
    mastery = mastery.lower()
    if mastery in ("unlearned", "new", "待学", "未学"):
        return stmt.where(Question.id.not_in(learned))
    if mastery in ("unfamiliar", "不熟"):
        return stmt.where(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.last_q.is_not(None), ReviewSchedule.last_q < 3
                )
            )
        )
    if mastery in ("familiar", "熟悉"):
        return stmt.where(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.last_q >= 3, ReviewSchedule.last_q < 5
                )
            )
        )
    if mastery in ("mastered", "精通"):
        return stmt.where(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(ReviewSchedule.last_q == 5)
            )
        )
    return stmt


@router.get("")
def list_questions(
    q: str | None = None,
    category_id: int | None = None,
    tag: str | None = None,
    tag_id: int | None = None,
    company: str | None = None,
    company_id: int | None = None,
    difficulty: int | None = Query(default=None, ge=1, le=5),
    frequency: str | None = None,
    mastery: str | None = None,
    source_type: str | None = None,
    # M2 多维筛选：逗号分隔，维度间 AND、维度内 OR。
    category_ids: str | None = None,
    tag_ids: str | None = None,
    company_ids: str | None = None,
    difficulties: str | None = None,
    frequencies: str | None = None,
    sources: str | None = None,
    masteries: str | None = None,
    status: str = "active",
    include_deleted: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(Question)
    if status != "all":
        if status not in ("draft", "active", "archived"):
            raise ApiError(400, "VALIDATION_ERROR", "status 不合法")
        stmt = stmt.where(Question.status == status)
    if not include_deleted:
        stmt = stmt.where(Question.is_deleted == 0)
    if source_type:
        stmt = stmt.where(Question.source_type == source_type)
    if difficulty:
        stmt = stmt.where(Question.difficulty == difficulty)
    if frequency:
        stmt = stmt.where(Question.frequency == frequency)
    if category_id:
        sub = _category_question_subquery(db, category_id)
        if sub is None:
            stmt = stmt.where(Question.id == -1)
        else:
            stmt = stmt.where(Question.id.in_(sub))
    if tag_id:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionTag.question_id).where(QuestionTag.tag_id == tag_id)
            )
        )
    if tag:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionTag.question_id)
                .join(Tag, Tag.id == QuestionTag.tag_id)
                .where(Tag.name.like(f"%{tag}%"))
            )
        )
    if company_id:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCompany.question_id).where(
                    QuestionCompany.company_id == company_id
                )
            )
        )
    if company:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCompany.question_id)
                .join(Company, Company.id == QuestionCompany.company_id)
                .where(Company.name.like(f"%{company}%"))
            )
        )
    if q:
        pattern = f"%{q}%"
        tag_hits = (
            select(QuestionTag.question_id)
            .join(Tag, Tag.id == QuestionTag.tag_id)
            .where(Tag.name.like(pattern))
        )
        fts_ids = search_question_ids(db, q)
        if fts_ids is None:
            stmt = stmt.where(
                or_(
                    Question.stem.like(pattern),
                    Question.answer.like(pattern),
                    Question.notes.like(pattern),
                    Question.id.in_(tag_hits),
                )
            )
        else:
            stmt = stmt.where(
                or_(Question.id.in_(fts_ids), Question.id.in_(tag_hits))
            )
    if mastery:
        stmt = _apply_mastery_filter(stmt, mastery)

    stmt = apply_multi_filters(
        stmt,
        db,
        category_ids=parse_int_list(category_ids),
        tag_ids=parse_int_list(tag_ids),
        company_ids=parse_int_list(company_ids),
        difficulties=parse_int_list(difficulties),
        frequencies=parse_str_list(frequencies),
        sources=parse_str_list(sources),
        masteries=parse_str_list(masteries),
    )

    total = int(
        db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    )
    rows = db.scalars(
        stmt.order_by(Question.updated_at.desc(), Question.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        {
            "items": serialize_question_list(db, list(rows)),
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("")
def create_question(
    payload: QuestionCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    settings = get_settings(db)
    stem = normalize_text(payload.stem)
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
            f"题库中已存在相同题干（题目 #{duplicate.id}）",
            {"question_id": duplicate.id},
        )

    if settings.get("manual.new_to_pending"):
        meta = suggest_meta(db, f"{stem}\n{payload.answer or ''}")
        meta["tags"] = list(dict.fromkeys([*meta.get("tags", []), *payload.tags]))
        meta["tag_ids"] = list(dict.fromkeys([*meta.get("tag_ids", []), *payload.tag_ids]))
        if payload.difficulty:
            meta["difficulty"] = payload.difficulty
        if payload.frequency:
            meta["frequency"] = payload.frequency
        if payload.category_ids:
            meta["category_id"] = payload.category_ids[0]
        if payload.category_path:
            meta["category_id"] = get_or_create_category_path(
                db, payload.category_path.split("/")
            ).id
        from ..models import PendingItem

        pending = PendingItem(
            item_type="question",
            source_type="manual",
            origin_ref="manual",
            raw_text=stem,
            stem=stem,
            answer=payload.answer,
            suggested_meta=json.dumps(meta, ensure_ascii=False),
            parse_confidence=1.0,
            content_hash=content_hash,
            simhash=simhash64(stem),
            status="pending",
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        return ok(
            {"pending": True, "item": serialize_pending(db, pending)},
            "已进入待审区",
        )

    question = Question(
        stem=stem,
        answer=payload.answer,
        key_points=json.dumps(payload.key_points, ensure_ascii=False)
        if payload.key_points
        else None,
        notes=payload.notes,
        difficulty=payload.difficulty,
        frequency=payload.frequency,
        status=payload.status,
        source_type="manual",
        content_hash=content_hash,
        simhash=simhash64(stem),
    )
    db.add(question)
    db.flush()
    set_question_taxonomy(
        db,
        question.id,
        category_ids=payload.category_ids,
        category_path=payload.category_path,
        tags=payload.tags,
        tag_ids=payload.tag_ids,
        companies=payload.companies,
        replace=True,
    )
    db.add(ReviewSchedule(question_id=question.id))
    db.add(
        QuestionOrigin(
            question_id=question.id,
            source_type="manual",
            origin_ref="manual",
            raw_snapshot=payload.answer,
            content_hash=content_hash,
        )
    )
    audit(db, "question_create", "question", question.id, {"stem": truncate(payload.stem, 80)})
    db.commit()
    db.refresh(question)
    return ok(serialize_question(db, question, detail=True), "已创建")


@router.get("/{question_id}")
def get_question(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    question = _get_question(db, question_id)
    return ok(serialize_question(db, question, detail=True))


@router.patch("/{question_id}")
def update_question(
    question_id: int,
    payload: QuestionUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    question = _get_question(db, question_id)
    fields = payload.model_fields_set

    if payload.stem is not None and payload.stem != question.stem:
        normalized_stem = normalize_text(payload.stem)
        content_hash = question_hash(normalized_stem)
        duplicate = db.scalar(
            select(Question).where(
                Question.content_hash == content_hash,
                Question.is_deleted == 0,
                Question.id != question.id,
            )
        )
        if duplicate:
            raise ApiError(
                409,
                "CONFLICT",
                f"题库中已存在相同题干（题目 #{duplicate.id}）",
                {"question_id": duplicate.id},
            )
        question.stem = normalized_stem
        question.content_hash = content_hash
        question.simhash = simhash64(normalized_stem)
    if "answer" in fields:
        question.answer = payload.answer
    if "notes" in fields:
        question.notes = payload.notes
    if "key_points" in fields:
        question.key_points = (
            json.dumps(payload.key_points, ensure_ascii=False)
            if payload.key_points
            else None
        )
    if "difficulty" in fields:
        question.difficulty = payload.difficulty
    if "frequency" in fields:
        question.frequency = payload.frequency
    if payload.status is not None:
        question.status = payload.status

    taxonomy_fields = {"category_ids", "category_path", "tags", "tag_ids", "companies"}
    if taxonomy_fields & fields:
        current_category_ids = list(
            db.scalars(
                select(QuestionCategory.category_id).where(
                    QuestionCategory.question_id == question.id
                )
            ).all()
        )
        current_tags = list(
            db.scalars(
                select(Tag.name)
                .join(QuestionTag, QuestionTag.tag_id == Tag.id)
                .where(QuestionTag.question_id == question.id)
            ).all()
        )
        current_tag_ids = list(
            db.scalars(
                select(QuestionTag.tag_id).where(QuestionTag.question_id == question.id)
            ).all()
        )
        current_companies = list(
            db.scalars(
                select(Company.name)
                .join(QuestionCompany, QuestionCompany.company_id == Company.id)
                .where(QuestionCompany.question_id == question.id)
            ).all()
        )
        set_question_taxonomy(
            db,
            question.id,
            category_ids=payload.category_ids
            if "category_ids" in fields
            else current_category_ids,
            category_path=payload.category_path if "category_path" in fields else None,
            tags=payload.tags if "tags" in fields else current_tags,
            tag_ids=payload.tag_ids if "tag_ids" in fields else current_tag_ids,
            companies=payload.companies if "companies" in fields else current_companies,
            replace=True,
        )

    audit(db, "question_update", "question", question.id, sorted(fields))
    db.commit()
    db.refresh(question)
    return ok(serialize_question(db, question, detail=True), "已保存")


@router.delete("/{question_id}")
def delete_question(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    question = _get_question(db, question_id)
    question.is_deleted = 1
    audit(db, "question_delete", "question", question.id, {"stem": truncate(question.stem, 80)})
    db.commit()
    return ok(None, "已软删除，历史掌握记录保留")


@router.post("/{question_id}/archive")
def archive_question(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    question = _get_question(db, question_id)
    question.status = "archived"
    audit(db, "question_archive", "question", question.id)
    db.commit()
    return ok(serialize_question(db, question), "已归档")


@router.post("/{question_id}/restore")
def restore_question(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    question = _get_question(db, question_id)
    question.status = "active"
    question.is_deleted = 0
    audit(db, "question_restore", "question", question.id)
    db.commit()
    return ok(serialize_question(db, question), "已恢复")


@router.get("/{question_id}/history")
def question_history(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_question(db, question_id)
    detail = serialize_question(db, db.get(Question, question_id), detail=True)
    return ok(
        {
            "schedule": detail["schedule"],
            "history": detail.get("history", []),
            "origins": detail.get("origins", []),
        }
    )


@router.get("/{question_id}/knowledge")
def question_knowledge(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_question(db, question_id)
    rows = db.execute(
        select(KnowledgePoint, QuestionKnowledge.relation_type)
        .join(QuestionKnowledge, QuestionKnowledge.knowledge_id == KnowledgePoint.id)
        .where(
            QuestionKnowledge.question_id == question_id,
            KnowledgePoint.is_deleted == 0,
        )
        .order_by(KnowledgePoint.id)
    ).all()
    return ok(
        [
            {
                "id": kp.id,
                "title": kp.title,
                "kind": kp.kind,
                "relation_type": relation,
                "content": kp.content,
            }
            for kp, relation in rows
        ]
    )


@router.post("/{question_id}/knowledge")
def link_question_knowledge(
    question_id: int,
    payload: LinkCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_question(db, question_id)
    knowledge = db.get(KnowledgePoint, payload.knowledge_id)
    if knowledge is None or knowledge.is_deleted:
        raise ApiError(404, "NOT_FOUND", "知识条目不存在")
    key = (question_id, payload.knowledge_id, payload.relation_type)
    if db.get(QuestionKnowledge, key) is None:
        db.add(
            QuestionKnowledge(
                question_id=question_id,
                knowledge_id=payload.knowledge_id,
                relation_type=payload.relation_type,
            )
        )
        audit(
            db,
            "question_knowledge_link",
            "question",
            question_id,
            {"knowledge_id": payload.knowledge_id, "relation": payload.relation_type},
        )
        db.commit()
    return ok(None, "已建立关联")


@router.delete("/{question_id}/knowledge/{knowledge_id}")
def unlink_question_knowledge(
    question_id: int,
    knowledge_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_question(db, question_id)
    db.execute(
        delete(QuestionKnowledge).where(
            QuestionKnowledge.question_id == question_id,
            QuestionKnowledge.knowledge_id == knowledge_id,
        )
    )
    audit(
        db,
        "question_knowledge_unlink",
        "question",
        question_id,
        {"knowledge_id": knowledge_id},
    )
    db.commit()
    return ok(None, "已取消关联")
