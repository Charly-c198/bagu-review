"""列表批量加载：一次查询取齐标签/公司/分类/排程/收藏/错题，避免逐题 N+1。

`serialize_question` 支持传入预加载结果；不传时保持原逐条查询行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Bookmark,
    Category,
    Company,
    KnowledgePoint,
    MistakeBook,
    QuestionCategory,
    QuestionCompany,
    QuestionKnowledge,
    QuestionTag,
    ReviewSchedule,
    Tag,
)
from .categories import category_map, category_path


@dataclass
class QuestionListContext:
    """一批题目的附属数据。所有 key 都是 question_id。"""

    cat_map: dict[int, Category] = field(default_factory=dict)
    schedules: dict[int, ReviewSchedule | None] = field(default_factory=dict)
    tags: dict[int, list[Tag]] = field(default_factory=dict)
    companies: dict[int, list[Company]] = field(default_factory=dict)
    categories: dict[int, list[int]] = field(default_factory=dict)
    bookmarked: set[int] = field(default_factory=set)
    mistake_added: dict[int, bool] = field(default_factory=dict)


def load_question_context(
    db: Session,
    question_ids: list[int],
    *,
    with_taxonomy: bool = True,
) -> QuestionListContext:
    """按题目 id 批量加载序列化所需附属数据。空列表不发起查询。"""
    ids = list(dict.fromkeys(int(qid) for qid in question_ids))
    ctx = QuestionListContext()
    if not ids:
        return ctx

    ctx.cat_map = category_map(db)

    schedules = db.scalars(
        select(ReviewSchedule).where(ReviewSchedule.question_id.in_(ids))
    ).all()
    ctx.schedules = {s.question_id: s for s in schedules}

    ctx.bookmarked = set(
        db.scalars(select(Bookmark.question_id).where(Bookmark.question_id.in_(ids))).all()
    )

    latest: dict[int, MistakeBook] = {}
    for row in db.scalars(
        select(MistakeBook)
        .where(MistakeBook.question_id.in_(ids))
        .order_by(MistakeBook.id.desc())
    ).all():
        latest.setdefault(row.question_id, row)
    ctx.mistake_added = {qid: row.action == "added" for qid, row in latest.items()}

    if with_taxonomy:
        for tag, qid in db.execute(
            select(Tag, QuestionTag.question_id)
            .join(QuestionTag, QuestionTag.tag_id == Tag.id)
            .where(QuestionTag.question_id.in_(ids))
            .order_by(Tag.name)
        ).all():
            ctx.tags.setdefault(qid, []).append(tag)
        for company, qid in db.execute(
            select(Company, QuestionCompany.question_id)
            .join(QuestionCompany, QuestionCompany.company_id == Company.id)
            .where(QuestionCompany.question_id.in_(ids))
            .order_by(Company.name)
        ).all():
            ctx.companies.setdefault(qid, []).append(company)
        for cid, qid in db.execute(
            select(QuestionCategory.category_id, QuestionCategory.question_id)
            .where(QuestionCategory.question_id.in_(ids))
            .order_by(QuestionCategory.category_id)
        ).all():
            ctx.categories.setdefault(qid, []).append(cid)

    return ctx


def serialize_question_list(
    db: Session,
    questions: list[Any],
    *,
    quiz: bool = False,
    with_taxonomy: bool = True,
) -> list[dict[str, Any]]:
    from .serializers import serialize_question

    if not questions:
        return []
    ctx = load_question_context(
        db, [q.id for q in questions], with_taxonomy=with_taxonomy
    )
    return [
        serialize_question(db, q, quiz=quiz, list_ctx=ctx) for q in questions
    ]


@dataclass
class KnowledgeListContext:
    cat_map: dict[int, Category] = field(default_factory=dict)
    question_counts: dict[int, int] = field(default_factory=dict)


def load_knowledge_context(
    db: Session, knowledge_ids: list[int]
) -> KnowledgeListContext:
    ids = list(dict.fromkeys(int(kid) for kid in knowledge_ids))
    ctx = KnowledgeListContext(cat_map=category_map(db))
    if not ids:
        return ctx
    rows = db.execute(
        select(QuestionKnowledge.knowledge_id, QuestionKnowledge.question_id).where(
            QuestionKnowledge.knowledge_id.in_(ids)
        )
    ).all()
    for knowledge_id, _question_id in rows:
        ctx.question_counts[knowledge_id] = ctx.question_counts.get(knowledge_id, 0) + 1
    return ctx


def serialize_knowledge_list(db: Session, rows: list[Any]) -> list[dict[str, Any]]:
    from .serializers import serialize_knowledge

    if not rows:
        return []
    ctx = load_knowledge_context(db, [row.id for row in rows])
    return [serialize_knowledge(db, row, list_ctx=ctx) for row in rows]


def knowledge_items_for_questions(
    db: Session, question_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """题-知识关联（详情用），一次查询。"""
    if not question_ids:
        return {}
    cmap = category_map(db)
    result: dict[int, list[dict[str, Any]]] = {}
    for question_id, kp, relation in db.execute(
        select(
            QuestionKnowledge.question_id, KnowledgePoint, QuestionKnowledge.relation_type
        )
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKnowledge.knowledge_id)
        .where(
            QuestionKnowledge.question_id.in_(question_ids),
            KnowledgePoint.is_deleted == 0,
        )
        .order_by(KnowledgePoint.id)
    ).all():
        result.setdefault(question_id, []).append(
            {
                "id": kp.id,
                "title": kp.title,
                "kind": kp.kind,
                "relation_type": relation,
                "category_path": category_path(kp.category_id, cmap),
            }
        )
    return result