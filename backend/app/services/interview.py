"""M3b 文字仿真面试：组卷、逐题作答、AI/人工评分、复盘报告与薄弱点回写。

隐私口径：默认不把用户作答原文发给 AI；只有会话创建时显式勾选同意
（config.ai_consent=true）才会调用 AI 评分。未同意或 AI 失败时，作答仍会
保存，可手动评分，报告自动降级为基础版。
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import (
    InterviewReport,
    InterviewSession,
    InterviewTurn,
    Question,
)
from ..utils.timeutil import utcnow
from .ai.common import fit_payload, question_context
from .ai.gateway import get_ai_gateway
from .ai.prompts import (
    INTERVIEW_REPORT,
    INTERVIEW_SCORE,
    get_or_create_prompt_version,
    load_prompt,
    render_system_prompt,
)
from .audit import audit
from .batch_loader import serialize_question_list
from .categories import descendant_ids
from .review import apply_rating
from .serializers import json_list, json_obj

logger = logging.getLogger("bajiu.interview")

MAX_ANSWER_CHARS = 20000


class InterviewScoreOutput(BaseModel):
    score: int = Field(ge=0, le=5)
    feedback: str = ""
    gaps: list[str] = Field(default_factory=list)
    follow_up: str = ""
    advice: str = ""


class InterviewReportOutput(BaseModel):
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    weak_question_ids: list[int] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


def _config(session: InterviewSession) -> dict[str, Any]:
    return json_obj(session.config_json)


def _gaps(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _question_order(session: InterviewSession) -> list[int]:
    return [int(qid) for qid in _config(session).get("question_ids", [])]


def _turns(db: Session, session_id: int) -> list[InterviewTurn]:
    return list(
        db.scalars(
            select(InterviewTurn)
            .where(InterviewTurn.session_id == session_id)
            .order_by(InterviewTurn.id)
        ).all()
    )


def serialize_turn(
    db: Session, turn: InterviewTurn, *, include_reference: bool = True
) -> dict[str, Any]:
    question = db.get(Question, turn.question_id)
    data: dict[str, Any] = {
        "id": turn.id,
        "session_id": turn.session_id,
        "question_id": turn.question_id,
        "question_stem": question.stem if question else "",
        "answer_text": turn.answer_text,
        "follow_up": turn.follow_up,
        "follow_up_answer": turn.follow_up_answer,
        "score": turn.score,
        "feedback": turn.feedback,
        "gaps": _gaps(turn.gaps_json),
        "scored_by": turn.scored_by,
        "created_at": turn.created_at.isoformat(),
        "scored_at": turn.scored_at.isoformat() if turn.scored_at else None,
    }
    if include_reference and question is not None:
        data["reference_answer"] = question.answer
        data["reference_key_points"] = json_list(question.key_points)
    return data


def serialize_report(row: InterviewReport) -> dict[str, Any]:
    try:
        report = json.loads(row.report_json)
    except (TypeError, ValueError):
        report = {}
    return {
        "id": row.id,
        "session_id": row.session_id,
        "total_score": row.total_score,
        "generated_by": row.generated_by,
        "created_at": row.created_at.isoformat(),
        **(report if isinstance(report, dict) else {}),
    }


def _report_for(db: Session, session_id: int) -> InterviewReport | None:
    return db.scalar(
        select(InterviewReport).where(InterviewReport.session_id == session_id)
    )


def serialize_session(
    db: Session,
    session: InterviewSession,
    *,
    detail: bool = False,
    include_questions: bool = True,
) -> dict[str, Any]:
    config = _config(session)
    question_ids = _question_order(session)
    index_by_id = {qid: index + 1 for index, qid in enumerate(question_ids)}
    turns = _turns(db, session.id)
    scored = [turn for turn in turns if turn.score is not None]
    data: dict[str, Any] = {
        "id": session.id,
        "status": session.status,
        "started_at": session.started_at.isoformat(),
        "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        "config": {
            "count": len(question_ids),
            "duration_min": config.get("duration_min", 30),
            "ai_consent": bool(config.get("ai_consent")),
            "category_ids": config.get("category_ids", []),
            "difficulties": config.get("difficulties", []),
            "frequencies": config.get("frequencies", []),
        },
        "progress": {
            "total": len(question_ids),
            "answered": len(turns),
            "scored": len(scored),
            "average_score": round(
                sum(turn.score for turn in scored) / len(scored), 2
            )
            if scored
            else None,
        },
    }
    if include_questions:
        questions = [db.get(Question, qid) for qid in question_ids]
        data["questions"] = serialize_question_list(
            db, [q for q in questions if q is not None], quiz=True
        )
    if detail:
        data["turns"] = [
            serialize_turn(db, turn) | {"index": index_by_id.get(turn.question_id)}
            for turn in turns
        ]
        report = _report_for(db, session.id)
        data["report"] = serialize_report(report) if report else None
    else:
        report = _report_for(db, session.id)
        data["total_score"] = report.total_score if report else None
    return data


# ---- 组卷 ---------------------------------------------------------------


def _candidate_ids(
    db: Session,
    *,
    category_ids: list[int],
    difficulties: list[int],
    frequencies: list[str],
) -> list[int]:
    stmt = select(Question.id).where(
        Question.status == "active", Question.is_deleted == 0
    )
    if category_ids:
        allowed: set[int] = set()
        for category_id in category_ids:
            allowed.update(descendant_ids(db, category_id))
        if not allowed:
            return []
        from ..models import QuestionCategory

        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCategory.question_id).where(
                    QuestionCategory.category_id.in_(allowed)
                )
            )
        )
    if difficulties:
        stmt = stmt.where(Question.difficulty.in_(difficulties))
    if frequencies:
        stmt = stmt.where(Question.frequency.in_(frequencies))
    return list(db.scalars(stmt).all())


def create_session(
    db: Session,
    *,
    count: int,
    duration_min: int,
    category_ids: list[int],
    difficulties: list[int],
    frequencies: list[str],
    ai_consent: bool,
) -> InterviewSession:
    count = max(1, min(count, 20))
    candidates = _candidate_ids(
        db,
        category_ids=category_ids,
        difficulties=difficulties,
        frequencies=frequencies,
    )
    if len(candidates) < count:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            f"可用题目不足：需要 {count} 道，当前只有 {len(candidates)} 道",
        )
    question_ids = random.sample(candidates, count)
    config = {
        "question_ids": question_ids,
        "duration_min": max(5, min(duration_min, 180)),
        "category_ids": category_ids,
        "difficulties": difficulties,
        "frequencies": frequencies,
        "ai_consent": bool(ai_consent),
    }
    session = InterviewSession(
        config_json=json.dumps(config, ensure_ascii=False),
        status="in_progress",
    )
    db.add(session)
    db.flush()
    audit(
        db,
        "interview_start",
        "interview",
        session.id,
        {"count": count, "ai_consent": bool(ai_consent)},
    )
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: int) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise ApiError(404, "NOT_FOUND", "面试会话不存在")
    return session


def abort_session(db: Session, session: InterviewSession) -> InterviewSession:
    if session.status != "in_progress":
        raise ApiError(409, "CONFLICT", "只有进行中的面试可以中止")
    session.status = "aborted"
    session.finished_at = utcnow()
    audit(db, "interview_abort", "interview", session.id)
    db.commit()
    return session


# ---- 作答与评分 ---------------------------------------------------------


def _score_payload(
    db: Session,
    session: InterviewSession,
    question: Question,
    answer_text: str,
) -> dict[str, Any]:
    order = _question_order(session)
    payload = question_context(db, question)
    payload.update(
        {
            "user_answer": answer_text[:MAX_ANSWER_CHARS],
            "question_index": order.index(question.id) + 1,
            "question_total": len(order),
        }
    )
    return fit_payload(payload, max(2000, 8000))


def submit_answer(
    db: Session,
    session: InterviewSession,
    *,
    question_id: int,
    answer_text: str,
) -> InterviewTurn:
    if session.status != "in_progress":
        raise ApiError(409, "CONFLICT", "面试已结束，不能继续作答")
    question_ids = _question_order(session)
    if question_id not in question_ids:
        raise ApiError(400, "VALIDATION_ERROR", "该题目不属于本次面试")
    text = (answer_text or "").strip()
    if not text:
        raise ApiError(400, "VALIDATION_ERROR", "作答内容不能为空")
    if len(text) > MAX_ANSWER_CHARS:
        raise ApiError(400, "VALIDATION_ERROR", "作答内容过长")
    existing = db.scalar(
        select(InterviewTurn).where(
            InterviewTurn.session_id == session.id,
            InterviewTurn.question_id == question_id,
        )
    )
    if existing is not None:
        raise ApiError(409, "CONFLICT", "该题已提交过作答")

    question = db.get(Question, question_id)
    if question is None or question.is_deleted:
        raise ApiError(404, "NOT_FOUND", "题目不存在")

    # 先保存作答，再调用外部服务；AI 失败也不会丢失学员输入。
    turn = InterviewTurn(
        session_id=session.id,
        question_id=question_id,
        answer_text=text,
        scored_by="none",
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)

    if not _config(session).get("ai_consent"):
        return turn

    spec = load_prompt(*INTERVIEW_SCORE)
    prompt_row = get_or_create_prompt_version(db, spec)
    payload = _score_payload(db, session, question, text)
    db.commit()
    try:
        result = get_ai_gateway(db).complete_json(
            purpose="interview_score",
            system_prompt=render_system_prompt(spec),
            payload=payload,
            schema_model=InterviewScoreOutput,
            prompt_version_id=prompt_row.id,
            cache_input=payload,
        )
    except ApiError as exc:
        db.refresh(turn)
        exc.data = {
            **(exc.data if isinstance(exc.data, dict) else {}),
            "turn": serialize_turn(db, turn, include_reference=False),
        }
        raise

    turn.score = max(0, min(5, int(result.get("score", 0))))
    turn.feedback = result.get("feedback") or ""
    turn.gaps_json = json.dumps(result.get("gaps") or [], ensure_ascii=False)
    turn.follow_up = result.get("follow_up") or ""
    turn.scored_by = "ai"
    turn.scored_at = utcnow()
    audit(
        db,
        "interview_answer",
        "interview",
        session.id,
        {"question_id": question_id, "score": turn.score, "scored_by": "ai"},
    )
    db.commit()
    db.refresh(turn)
    return turn


def score_turn_manual(
    db: Session,
    session: InterviewSession,
    turn: InterviewTurn,
    *,
    score: int,
    feedback: str | None,
) -> InterviewTurn:
    if session.status != "in_progress":
        raise ApiError(409, "CONFLICT", "面试已结束，不能修改评分")
    turn.score = max(0, min(5, int(score)))
    if feedback is not None:
        turn.feedback = feedback
    turn.scored_by = "manual"
    turn.scored_at = utcnow()
    audit(
        db,
        "interview_answer",
        "interview",
        session.id,
        {"question_id": turn.question_id, "score": turn.score, "scored_by": "manual"},
    )
    db.commit()
    db.refresh(turn)
    return turn


def submit_follow_up(
    db: Session,
    session: InterviewSession,
    turn: InterviewTurn,
    *,
    answer_text: str,
) -> InterviewTurn:
    if session.status != "in_progress":
        raise ApiError(409, "CONFLICT", "面试已结束，不能继续作答")
    text = (answer_text or "").strip()
    if not text:
        raise ApiError(400, "VALIDATION_ERROR", "追问作答不能为空")
    if not turn.follow_up:
        raise ApiError(409, "CONFLICT", "该题没有需要回答的追问")
    turn.follow_up_answer = text[:MAX_ANSWER_CHARS]
    db.commit()
    db.refresh(turn)
    return turn


def get_turn(
    db: Session, session: InterviewSession, turn_id: int
) -> InterviewTurn:
    turn = db.get(InterviewTurn, turn_id)
    if turn is None or turn.session_id != session.id:
        raise ApiError(404, "NOT_FOUND", "作答记录不存在")
    return turn


# ---- 复盘报告 -----------------------------------------------------------


def _ordered_turns(session: InterviewSession, turns: list[InterviewTurn]) -> list[InterviewTurn]:
    order = _question_order(session)
    index = {qid: i for i, qid in enumerate(order)}
    return sorted(turns, key=lambda turn: index.get(turn.question_id, 999))


def _basic_report(
    per_question: list[dict[str, Any]],
    total_score: float,
    average: float,
    scored_count: int,
    total_count: int,
    error_code: str | None,
) -> dict[str, Any]:
    weak = [row for row in per_question if row["score"] is not None and row["score"] < 3]
    strong = [row for row in per_question if row["score"] is not None and row["score"] >= 4]
    highlights = [
        f"第 {row['index']} 题得分 {row['score']}/5：{row['stem'][:40]}"
        for row in strong[:3]
    ] or ["已完成本次面试，作答过程本身有助于暴露薄弱点。"]
    gaps = []
    for row in weak:
        gaps.extend(row.get("gaps") or [])
    if not gaps and weak:
        gaps = [f"第 {row['index']} 题核心要点掌握不牢" for row in weak[:3]]
    if not gaps:
        gaps = ["暂无明显知识缺口，继续保持并尝试更高难度题目。"]
    advice = [
        "把本次得分低于 3 分的题目加入错题本，按 SM-2 计划复练。",
        "针对每个知识缺口补充一条知识条目，并关联到对应题目。",
        "下次作答先给结论，再按“原理—流程—边界”展开。",
    ]
    return {
        "summary": (
            f"本次面试共 {total_count} 题，完成并评分 {scored_count} 题，"
            f"平均 {average:.1f}/5（百分制 {total_score}）。"
            + ("整体表现扎实，重点是补全细节。" if average >= 4 else "建议优先复练低分题目与高频知识点。")
        ),
        "highlights": highlights,
        "gaps": gaps[:6],
        "advice": advice,
        "weak_question_ids": [row["question_id"] for row in weak],
        "next_steps": [
            "在错题本中重练本次薄弱题，并在复习队列中按期回顾。",
            "针对薄弱分类补充知识条目，并关联相关题目。",
        ],
        "ai_error_code": error_code,
    }


def _sanitize_ai_report(
    result: dict[str, Any],
    per_question: list[dict[str, Any]],
    error_code: str | None,
) -> dict[str, Any]:
    valid_ids = {row["question_id"] for row in per_question}
    weak_ids = []
    for value in result.get("weak_question_ids", []) or []:
        try:
            question_id = int(value)
        except (TypeError, ValueError):
            continue
        if question_id in valid_ids and question_id not in weak_ids:
            weak_ids.append(question_id)
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()][:8]

    return {
        "summary": str(result.get("summary") or ""),
        "highlights": _strings(result.get("highlights")),
        "gaps": _strings(result.get("gaps")),
        "advice": _strings(result.get("advice")),
        "weak_question_ids": weak_ids,
        "next_steps": _strings(result.get("next_steps")),
        "ai_error_code": error_code,
    }


def finish_session(db: Session, session: InterviewSession) -> InterviewReport:
    if session.status != "in_progress":
        raise ApiError(409, "CONFLICT", "该面试已结束")
    turns = _ordered_turns(session, _turns(db, session.id))
    scored = [turn for turn in turns if turn.score is not None]
    if not scored:
        raise ApiError(400, "VALIDATION_ERROR", "至少完成并评分一道题后才能结束面试")

    order = _question_order(session)
    index_by_id = {qid: i + 1 for i, qid in enumerate(order)}
    per_question = []
    for turn in turns:
        question = db.get(Question, turn.question_id)
        per_question.append(
            {
                "question_id": turn.question_id,
                "index": index_by_id.get(turn.question_id, 0),
                "stem": question.stem if question else "",
                "score": turn.score,
                "feedback": turn.feedback or "",
                "gaps": _gaps(turn.gaps_json),
                "scored_by": turn.scored_by,
                "follow_up": turn.follow_up,
                "follow_up_answered": bool(turn.follow_up_answer),
            }
        )
    average = round(sum(turn.score for turn in scored) / len(scored), 2)
    total_score = round(average / 5 * 100, 1)
    config = _config(session)

    payload = {
        "config": {
            "question_total": len(order),
            "answered": len(turns),
            "scored": len(scored),
            "duration_min": config.get("duration_min", 30),
            "average_score": average,
            "total_score": total_score,
        },
        "questions": per_question,
    }
    generated_by = "basic"
    error_code: str | None = None
    report_data: dict[str, Any]
    # 未同意发送作答文本的会话不调用 AI，直接生成基础报告；报告请求同样
    # 只含评分与反馈，不含作答原文。
    if not config.get("ai_consent"):
        report_data = _basic_report(
            per_question, total_score, average, len(scored), len(order), None
        )
    else:
        spec = load_prompt(*INTERVIEW_REPORT)
        prompt_row = get_or_create_prompt_version(db, spec)
        db.commit()
        try:
            result = get_ai_gateway(db).complete_json(
                purpose="interview_report",
                system_prompt=render_system_prompt(spec),
                payload=fit_payload(payload, max(2000, 8000)),
                schema_model=InterviewReportOutput,
                prompt_version_id=prompt_row.id,
                cache_input=payload,
            )
            report_data = _sanitize_ai_report(result, per_question, None)
            generated_by = "ai"
        except ApiError as exc:
            error_code = exc.code
            report_data = _basic_report(
                per_question, total_score, average, len(scored), len(order), error_code
            )

    report_data = {
        "total_score": total_score,
        "average_score": average,
        "answered": len(turns),
        "scored": len(scored),
        "total": len(order),
        "per_question": per_question,
        "generated_by": generated_by,
        **report_data,
    }
    report = InterviewReport(
        session_id=session.id,
        total_score=total_score,
        report_json=json.dumps(report_data, ensure_ascii=False),
        generated_by=generated_by,
    )
    db.add(report)

    # 回写薄弱点：评分写入掌握记录与 SM-2 排程；低分题自动进入错题本。
    for turn in scored:
        question = db.get(Question, turn.question_id)
        if question is not None and not question.is_deleted:
            apply_rating(db, question, turn.score, "interview")

    session.status = "finished"
    session.finished_at = utcnow()
    audit(
        db,
        "interview_finish",
        "interview",
        session.id,
        {
            "total_score": total_score,
            "scored": len(scored),
            "report_by": generated_by,
            "ai_error_code": error_code,
        },
    )
    db.commit()
    db.refresh(report)
    return report


def list_sessions(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    sessions = db.scalars(
        select(InterviewSession)
        .order_by(InterviewSession.started_at.desc(), InterviewSession.id.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return [
        serialize_session(db, session, include_questions=False)
        for session in sessions
    ]
