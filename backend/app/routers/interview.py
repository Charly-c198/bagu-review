"""M3b 文字仿真面试 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ok
from ..models import User
from ..schemas import (
    InterviewAnswerRequest,
    InterviewCreateRequest,
    InterviewFollowUpRequest,
    InterviewScoreRequest,
)
from ..security import get_current_user
from ..services.interview import (
    abort_session,
    create_session,
    finish_session,
    get_session,
    get_turn,
    list_sessions,
    score_turn_manual,
    serialize_report,
    serialize_session,
    serialize_turn,
    submit_answer,
    submit_follow_up,
)

router = APIRouter(prefix="/interview", tags=["interview"])


@router.post("/sessions")
def create(
    payload: InterviewCreateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    session = create_session(
        db,
        count=payload.count,
        duration_min=payload.duration_min,
        category_ids=payload.category_ids,
        difficulties=payload.difficulties,
        frequencies=payload.frequencies,
        ai_consent=payload.ai_consent,
    )
    return ok(serialize_session(db, session, detail=True), "面试已开始")


@router.get("/sessions")
def list_all(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    items = list_sessions(db, limit=limit)
    return ok({"items": items, "total": len(items)})


@router.get("/sessions/{session_id}")
def detail(
    session_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return ok(serialize_session(db, get_session(db, session_id), detail=True))


@router.post("/sessions/{session_id}/answers")
def answer(
    session_id: int,
    payload: InterviewAnswerRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    session = get_session(db, session_id)
    turn = submit_answer(
        db,
        session,
        question_id=payload.question_id,
        answer_text=payload.answer_text,
    )
    return ok(serialize_turn(db, turn), "作答已保存")


@router.patch("/sessions/{session_id}/turns/{turn_id}")
def manual_score(
    session_id: int,
    turn_id: int,
    payload: InterviewScoreRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    session = get_session(db, session_id)
    turn = get_turn(db, session, turn_id)
    turn = score_turn_manual(
        db, session, turn, score=payload.score, feedback=payload.feedback
    )
    return ok(serialize_turn(db, turn), "评分已保存")


@router.post("/sessions/{session_id}/turns/{turn_id}/follow-up")
def follow_up(
    session_id: int,
    turn_id: int,
    payload: InterviewFollowUpRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    session = get_session(db, session_id)
    turn = get_turn(db, session, turn_id)
    turn = submit_follow_up(db, session, turn, answer_text=payload.answer_text)
    return ok(serialize_turn(db, turn), "追问作答已保存")


@router.post("/sessions/{session_id}/finish")
def finish(
    session_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    session = get_session(db, session_id)
    report = finish_session(db, session)
    return ok(
        {
            "report": serialize_report(report),
            "session": serialize_session(db, session, detail=True),
        },
        "面试复盘已生成",
    )


@router.post("/sessions/{session_id}/abort")
def abort(
    session_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    session = get_session(db, session_id)
    session = abort_session(db, session)
    return ok(serialize_session(db, session, include_questions=False), "面试已中止")
