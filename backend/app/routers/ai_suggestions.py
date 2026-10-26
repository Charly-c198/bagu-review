"""M3a Slice 2/3 API：AI 打标建议、错题解析、答案润色与题库生产。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import AiSuggestion, User
from ..schemas import AiSuggestionRequest, QuestionGenerateRequest
from ..security import get_current_user
from ..services.ai.generation import generate_questions
from ..services.ai.suggestions import (
    KINDS,
    apply_suggestion,
    latest_suggestions,
    run_suggestion,
    serialize_suggestion,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/suggestions")
def create_suggestion(
    payload: AiSuggestionRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    row = run_suggestion(
        db,
        kind=payload.kind,
        target_type=payload.target_type,
        target_id=payload.target_id,
        user_answer=payload.user_answer,
        consent=payload.consent,
    )
    return ok(serialize_suggestion(row), "AI 建议已生成")


@router.get("/suggestions")
def list_suggestions(
    kind: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if kind and kind not in KINDS:
        raise ApiError(400, "VALIDATION_ERROR", "kind 不合法")
    if target_type and target_type not in ("pending", "question", "knowledge"):
        raise ApiError(400, "VALIDATION_ERROR", "target_type 不合法")
    rows = latest_suggestions(
        db,
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        limit=limit,
    )
    return ok({"items": [serialize_suggestion(row) for row in rows], "total": len(rows)})


@router.post("/suggestions/{suggestion_id}/apply")
def apply_suggestion_endpoint(
    suggestion_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    row = db.get(AiSuggestion, suggestion_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "AI 建议不存在")
    return ok(apply_suggestion(db, row), "建议已应用")


@router.post("/generate-questions")
def generate_question_endpoint(
    payload: QuestionGenerateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = generate_questions(
        db,
        knowledge_id=payload.knowledge_id,
        topic=payload.topic,
        category_path_value=payload.category_path,
        count=payload.count,
        difficulty=payload.difficulty,
    )
    message = (
        f"已生成 {result['generated']} 道题，进入待审区"
        if result["generated"]
        else "未生成新题目（可能全部重复）"
    )
    return ok(result, message)
