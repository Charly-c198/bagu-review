"""主动刷题与考前冲刺组卷。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ok
from ..models import (
    Company,
    MistakeBook,
    Question,
    QuestionCategory,
    QuestionCompany,
    QuestionTag,
    ReviewSchedule,
    Tag,
    User,
)
from ..schemas import QuizRequest
from ..security import get_current_user
from ..services.batch_loader import serialize_question_list
from ..services.categories import descendant_ids
from ..services.filters import apply_multi_filters
from ..services.fts import search_question_ids
from ..utils.timeutil import today_str

router = APIRouter(prefix="/practice", tags=["practice"])


@router.post("/quiz")
def create_quiz(
    payload: QuizRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(Question).where(
        Question.status == "active", Question.is_deleted == 0
    )
    if payload.category_id:
        ids = descendant_ids(db, payload.category_id)
        if not ids:
            stmt = stmt.where(Question.id == -1)
        else:
            stmt = stmt.where(
                Question.id.in_(
                    select(QuestionCategory.question_id).where(
                        QuestionCategory.category_id.in_(ids)
                    )
                )
            )
    if payload.tag_id:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionTag.question_id).where(
                    QuestionTag.tag_id == payload.tag_id
                )
            )
        )
    if payload.tag:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionTag.question_id)
                .join(Tag, Tag.id == QuestionTag.tag_id)
                .where(Tag.name.like(f"%{payload.tag}%"))
            )
        )
    if payload.company_id:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCompany.question_id).where(
                    QuestionCompany.company_id == payload.company_id
                )
            )
        )
    if payload.company:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCompany.question_id)
                .join(Company, Company.id == QuestionCompany.company_id)
                .where(Company.name.like(f"%{payload.company}%"))
            )
        )
    if payload.difficulty:
        stmt = stmt.where(Question.difficulty == payload.difficulty)
    if payload.frequency:
        stmt = stmt.where(Question.frequency == payload.frequency)
    if payload.source_type:
        stmt = stmt.where(Question.source_type == payload.source_type)
    stmt = apply_multi_filters(
        stmt,
        db,
        category_ids=payload.category_ids,
        tag_ids=payload.tag_ids,
        company_ids=payload.company_ids,
        difficulties=payload.difficulties,
        frequencies=payload.frequencies,
        sources=payload.sources,
        masteries=payload.masteries,
    )
    if payload.q:
        fts_ids = search_question_ids(db, payload.q)
        if fts_ids is None:
            pattern = f"%{payload.q}%"
            stmt = stmt.where(
                or_(Question.stem.like(pattern), Question.answer.like(pattern))
            )
        else:
            stmt = stmt.where(Question.id.in_(fts_ids))
    if payload.mastery:
        if payload.mastery in ("unfamiliar", "不熟"):
            stmt = stmt.where(
                Question.id.in_(
                    select(ReviewSchedule.question_id).where(
                        ReviewSchedule.last_q.is_not(None), ReviewSchedule.last_q < 3
                    )
                )
            )
        elif payload.mastery in ("familiar", "熟悉"):
            stmt = stmt.where(
                Question.id.in_(
                    select(ReviewSchedule.question_id).where(
                        ReviewSchedule.last_q >= 3, ReviewSchedule.last_q < 5
                    )
                )
            )
        elif payload.mastery in ("mastered", "精通"):
            stmt = stmt.where(
                Question.id.in_(
                    select(ReviewSchedule.question_id).where(
                        ReviewSchedule.last_q == 5
                    )
                )
            )
        elif payload.mastery in ("unlearned", "new", "未学"):
            stmt = stmt.where(
                Question.id.not_in(
                    select(ReviewSchedule.question_id).where(
                        ReviewSchedule.first_reviewed_at.is_not(None)
                    )
                )
            )
    if payload.only_unfamiliar:
        stmt = stmt.where(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.last_q.is_not(None), ReviewSchedule.last_q < 3
                )
            )
        )
    if payload.exclude_mastered:
        stmt = stmt.where(
            Question.id.not_in(
                select(ReviewSchedule.question_id).where(ReviewSchedule.last_q == 5)
            )
        )
    if payload.only_mistakes:
        rows = db.scalars(
            select(MistakeBook).order_by(MistakeBook.id.desc())
        ).all()
        latest: dict[int, str] = {}
        for row in rows:
            latest.setdefault(row.question_id, row.action)
        mistake_ids = [qid for qid, action in latest.items() if action == "added"]
        stmt = stmt.where(Question.id.in_(mistake_ids) if mistake_ids else Question.id == -1)
    if payload.only_due:
        stmt = stmt.where(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.first_reviewed_at.is_not(None),
                    ReviewSchedule.next_review_date.is_not(None),
                    ReviewSchedule.next_review_date <= today_str(),
                )
            )
        )

    if payload.mode == "sprint":
        frequency_order = case(
            (Question.frequency == "high", 0),
            (Question.frequency == "mid", 1),
            else_=2,
        )
        stmt = stmt.order_by(frequency_order, func.random())
    else:
        stmt = stmt.order_by(func.random())
    rows = db.scalars(stmt.limit(payload.limit)).all()
    return ok(
        {
            "items": serialize_question_list(db, list(rows), quiz=True),
            "total": len(rows),
            "mode": payload.mode,
        }
    )
