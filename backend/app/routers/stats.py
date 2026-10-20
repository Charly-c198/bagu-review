"""统计复盘路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ok
from ..models import User
from ..security import get_current_user
from ..services.review import (
    dashboard_stats,
    knowledge_coverage,
    mastery_distribution,
    unfamiliar_distribution,
)

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard")
def dashboard(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(dashboard_stats(db, category_id))


@router.get("/mastery-distribution")
def mastery(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(mastery_distribution(db, category_id))


@router.get("/knowledge-coverage")
def coverage(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(knowledge_coverage(db))


@router.get("/unfamiliar-distribution")
def unfamiliar(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(unfamiliar_distribution(db, category_id))
