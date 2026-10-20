"""M3a 质量审查 API：AI 建议与人工质检共用一套记录。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import PendingItem, QualityCheck, User
from ..schemas import QualityCheckRequest, QualityTargetRequest
from ..security import get_current_user
from ..services.ai.quality import (
    latest_checks,
    run_quality_check,
    serialize_quality_check,
)

router = APIRouter(tags=["quality"])


def _manual_issues(payload: QualityCheckRequest) -> list[dict]:
    return [issue.model_dump() for issue in payload.issues] if payload.issues else []


def _run(
    db: Session,
    target_type: str,
    target_id: int,
    payload: QualityCheckRequest,
) -> dict:
    row = run_quality_check(
        db,
        target_type,
        target_id,
        mode=payload.mode,
        manual_issues=_manual_issues(payload),
        overall_risk=payload.overall_risk,
        summary=payload.summary,
    )
    return serialize_quality_check(row)


@router.post("/pending/{item_id}/quality-check")
def quality_check_pending(
    item_id: int,
    payload: QualityCheckRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if db.get(PendingItem, item_id) is None:
        raise ApiError(404, "NOT_FOUND", "待审项不存在")
    return ok(_run(db, "pending", item_id, payload), "质检完成")


@router.post("/quality/check")
def quality_check_target(
    payload: QualityTargetRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(_run(db, payload.target_type, payload.target_id, payload), "质检完成")


@router.get("/quality-checks")
def list_quality_checks(
    target_type: str | None = None,
    target_id: int | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(QualityCheck)
    if target_type:
        if target_type not in ("question", "knowledge", "pending"):
            raise ApiError(400, "VALIDATION_ERROR", "target_type 不合法")
        stmt = stmt.where(QualityCheck.target_type == target_type)
    if target_id is not None:
        stmt = stmt.where(QualityCheck.target_id == target_id)
    if status:
        if status not in ("success", "failed"):
            raise ApiError(400, "VALIDATION_ERROR", "status 不合法")
        stmt = stmt.where(QualityCheck.status == status)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(QualityCheck.created_at.desc(), QualityCheck.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        {
            "items": [serialize_quality_check(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/quality-checks/{target_type}/{target_id}")
def quality_check_history(
    target_type: str,
    target_id: int,
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if target_type not in ("question", "knowledge", "pending"):
        raise ApiError(400, "VALIDATION_ERROR", "target_type 不合法")
    rows = latest_checks(db, target_type, target_id, limit=limit)
    return ok([serialize_quality_check(row) for row in rows])


@router.post("/quality-checks/{check_id}/retry")
def retry_quality_check(
    check_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    row = db.get(QualityCheck, check_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "质检记录不存在")
    if row.status != "failed" or row.model == "manual":
        raise ApiError(409, "CONFLICT", "只有失败的 AI 质检记录可以重试")
    new_row = run_quality_check(db, row.target_type, row.target_id, mode="ai")
    return ok(serialize_quality_check(new_row), "重试完成")
