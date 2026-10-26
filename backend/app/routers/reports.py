"""M3b 周学习报告 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ok
from ..models import User
from ..schemas import WeeklyReportRequest
from ..security import get_current_user
from ..services.weekly import (
    generate_weekly_report,
    get_weekly,
    list_weekly,
    serialize_weekly,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/weekly")
def generate(
    payload: WeeklyReportRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    row = generate_weekly_report(
        db, week_start=payload.week_start, mode=payload.mode
    )
    message = "周报告已生成" if row.generated_by == "ai" else "已生成基础周报告"
    return ok(serialize_weekly(row), message)


@router.get("/weekly")
def list_all(
    limit: int = Query(default=12, ge=1, le=52),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = list_weekly(db, limit=limit)
    return ok({"items": [serialize_weekly(row) for row in rows], "total": len(rows)})


@router.get("/weekly/{report_id}")
def detail(
    report_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(serialize_weekly(get_weekly(db, report_id)))
