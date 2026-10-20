"""统一评分入口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import Question, User
from ..schemas import RatingRequest
from ..security import get_current_user
from ..services.review import apply_rating

router = APIRouter(prefix="/ratings", tags=["ratings"])


@router.post("")
def rate(
    payload: RatingRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    question = db.get(Question, payload.question_id)
    if question is None or question.is_deleted:
        raise ApiError(404, "NOT_FOUND", "题目不存在")
    if question.status != "active":
        raise ApiError(409, "CONFLICT", "只能评分正式题目")
    try:
        result = apply_rating(
            db, question, payload.q, payload.mode, sprint=payload.sprint
        )
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc
    db.commit()
    return ok(result)
