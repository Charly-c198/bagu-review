"""今日复习队列与摘要。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ok
from ..models import User
from ..security import get_current_user
from ..services.review import review_payload, review_summary

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/today")
def today(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(review_payload(db, category_id))


@router.get("/summary")
def summary(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(review_summary(db, category_id))
