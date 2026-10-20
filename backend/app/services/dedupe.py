"""精确去重与 SimHash 近似去重。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgePoint, PendingItem, Question
from ..utils.text import hamming_hex


def find_exact_question(
    db: Session, content_hash: str, exclude_ids: set[int] | None = None
) -> Question | None:
    exclude_ids = exclude_ids or set()
    stmt = (
        select(Question)
        .where(
            Question.content_hash == content_hash,
            Question.is_deleted == 0,
            Question.status.in_(("draft", "active", "archived")),
        )
        .order_by(Question.id)
    )
    for question in db.scalars(stmt).all():
        if question.id not in exclude_ids:
            return question
    return None


def find_exact_knowledge(
    db: Session, content_hash: str, exclude_ids: set[int] | None = None
) -> KnowledgePoint | None:
    exclude_ids = exclude_ids or set()
    stmt = (
        select(KnowledgePoint)
        .where(
            KnowledgePoint.content_hash == content_hash,
            KnowledgePoint.is_deleted == 0,
            KnowledgePoint.status.in_(("draft", "active", "archived")),
        )
        .order_by(KnowledgePoint.id)
    )
    for knowledge in db.scalars(stmt).all():
        if knowledge.id not in exclude_ids:
            return knowledge
    return None


def find_exact_pending_question(
    db: Session, content_hash: str, batch_id: int | None = None
) -> PendingItem | None:
    stmt = select(PendingItem).where(
        PendingItem.item_type == "question",
        PendingItem.content_hash == content_hash,
        PendingItem.status.in_(("pending", "approved", "merged")),
    )
    if batch_id is not None:
        stmt = stmt.where(PendingItem.import_batch_id == batch_id)
    return db.scalar(stmt.order_by(PendingItem.id).limit(1))


def find_exact_pending_knowledge(
    db: Session, content_hash: str, batch_id: int | None = None
) -> PendingItem | None:
    stmt = select(PendingItem).where(
        PendingItem.item_type == "knowledge",
        PendingItem.content_hash == content_hash,
        PendingItem.status.in_(("pending", "approved", "merged")),
    )
    if batch_id is not None:
        stmt = stmt.where(PendingItem.import_batch_id == batch_id)
    return db.scalar(stmt.order_by(PendingItem.id).limit(1))


def find_near_questions(
    db: Session, simhash: str, threshold: int = 3, limit: int = 5
) -> list[tuple[Question, int]]:
    if not simhash:
        return []
    rows = db.scalars(
        select(Question).where(
            Question.simhash.is_not(None),
            Question.is_deleted == 0,
            Question.status.in_(("draft", "active", "archived")),
        )
    ).all()
    scored = []
    for question in rows:
        distance = hamming_hex(simhash, question.simhash)
        if distance <= threshold:
            scored.append((question, distance))
    scored.sort(key=lambda x: (x[1], x[0].id))
    return scored[:limit]


def find_near_knowledge(
    db: Session, simhash: str, threshold: int = 3, limit: int = 5
) -> list[tuple[KnowledgePoint, int]]:
    if not simhash:
        return []
    rows = db.scalars(
        select(KnowledgePoint).where(
            KnowledgePoint.simhash.is_not(None),
            KnowledgePoint.is_deleted == 0,
            KnowledgePoint.status.in_(("draft", "active", "archived")),
        )
    ).all()
    scored = []
    for knowledge in rows:
        distance = hamming_hex(simhash, knowledge.simhash)
        if distance <= threshold:
            scored.append((knowledge, distance))
    scored.sort(key=lambda x: (x[1], x[0].id))
    return scored[:limit]


def find_near_pending(
    db: Session,
    simhash: str,
    item_type: str,
    threshold: int = 3,
    limit: int = 5,
) -> list[tuple[PendingItem, int]]:
    if not simhash:
        return []
    rows = db.scalars(
        select(PendingItem).where(
            PendingItem.simhash.is_not(None),
            PendingItem.item_type == item_type,
            PendingItem.status == "pending",
        )
    ).all()
    scored = []
    for item in rows:
        distance = hamming_hex(simhash, item.simhash)
        if distance <= threshold:
            scored.append((item, distance))
    scored.sort(key=lambda x: (x[1], x[0].id))
    return scored[:limit]
