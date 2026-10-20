"""复习队列、评分排程、错题本与统计口径。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    KnowledgePoint,
    MasteryRecord,
    MistakeBook,
    Question,
    QuestionCategory,
    QuestionKnowledge,
    ReviewSchedule,
)
from ..utils.sm2 import Sm2State, apply_sm2
from ..utils.timeutil import (
    local_date_str,
    local_day_bounds_utc,
    local_today,
    today_str,
    utcnow,
)
from .batch_loader import serialize_question_list
from .categories import category_map, category_path, descendant_ids
from .serializers import mastery_from_q, schedule_dict
from .settings_service import get_settings

DEFINITIONS_VERSION = "V0.4-1.5"


def _category_question_ids(db: Session, category_id: int | None) -> list[int] | None:
    if not category_id:
        return None
    ids = descendant_ids(db, category_id)
    if not ids:
        return []
    return list(
        db.scalars(
            select(QuestionCategory.question_id).where(
                QuestionCategory.category_id.in_(ids)
            )
        ).all()
    )


def rated_question_ids_today(db: Session, category_id: int | None = None) -> set[int]:
    today = local_today()
    start, end = local_day_bounds_utc(today)
    stmt = select(MasteryRecord.question_id).where(
        MasteryRecord.created_at >= start,
        MasteryRecord.created_at < end,
    )
    qids = _category_question_ids(db, category_id)
    if qids is not None:
        stmt = stmt.where(MasteryRecord.question_id.in_(qids))
    return set(db.scalars(stmt).all())


def _base_question_query():
    return select(Question).where(
        Question.status == "active",
        Question.is_deleted == 0,
    )


def _apply_category_filter(stmt, qids: list[int] | None):
    if qids is not None:
        stmt = stmt.where(Question.id.in_(qids))
    return stmt


def due_questions(
    db: Session,
    *,
    category_id: int | None = None,
    limit: int | None = None,
    exclude_ids: set[int] | None = None,
) -> list[Question]:
    today = today_str()
    qids = _category_question_ids(db, category_id)
    stmt = (
        select(Question)
        .join(ReviewSchedule, ReviewSchedule.question_id == Question.id)
        .where(
            Question.status == "active",
            Question.is_deleted == 0,
            ReviewSchedule.first_reviewed_at.is_not(None),
            ReviewSchedule.next_review_date.is_not(None),
            ReviewSchedule.next_review_date <= today,
        )
    )
    stmt = _apply_category_filter(stmt, qids)
    if exclude_ids:
        stmt = stmt.where(Question.id.not_in(exclude_ids))
    stmt = stmt.order_by(ReviewSchedule.next_review_date, Question.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def new_questions(
    db: Session,
    *,
    category_id: int | None = None,
    limit: int | None = None,
    exclude_ids: set[int] | None = None,
) -> list[Question]:
    qids = _category_question_ids(db, category_id)
    stmt = (
        select(Question)
        .outerjoin(ReviewSchedule, ReviewSchedule.question_id == Question.id)
        .where(
            Question.status == "active",
            Question.is_deleted == 0,
            ReviewSchedule.first_reviewed_at.is_(None),
        )
    )
    stmt = _apply_category_filter(stmt, qids)
    if exclude_ids:
        stmt = stmt.where(Question.id.not_in(exclude_ids))
    stmt = stmt.order_by(Question.created_at.desc(), Question.id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def review_payload(db: Session, category_id: int | None = None) -> dict[str, Any]:
    settings = get_settings(db)
    rated = rated_question_ids_today(db, category_id)
    review_limit = int(settings["sm2.daily_review_limit"])
    new_limit = int(settings["sm2.daily_new_limit"])

    all_due = due_questions(
        db, category_id=category_id, exclude_ids=rated
    )
    due = all_due[:review_limit]
    new = new_questions(
        db,
        category_id=category_id,
        limit=new_limit,
        exclude_ids=rated,
    )
    backlog = max(0, len(all_due) - len(due))
    today = local_today()
    start, end = local_day_bounds_utc(today)
    completed_stmt = select(func.count(func.distinct(MasteryRecord.question_id))).where(
        MasteryRecord.created_at >= start,
        MasteryRecord.created_at < end,
    )
    qids = _category_question_ids(db, category_id)
    if qids is not None:
        completed_stmt = completed_stmt.where(MasteryRecord.question_id.in_(qids))
    completed = int(db.scalar(completed_stmt) or 0)

    return {
        "date": today.isoformat(),
        "due": serialize_question_list(db, list(due), quiz=True),
        "new": serialize_question_list(db, list(new), quiz=True),
        "counts": {
            "due_total": len(all_due),
            "due_returned": len(due),
            "new_total": len(
                new_questions(db, category_id=category_id, exclude_ids=rated)
            ),
            "new_returned": len(new),
            "backlog": backlog,
            "completed": completed,
        },
        "limits": {
            "daily_new_limit": new_limit,
            "daily_review_limit": review_limit,
        },
    }


def review_summary(db: Session, category_id: int | None = None) -> dict[str, Any]:
    payload = review_payload(db, category_id)
    return payload["counts"] | {"date": payload["date"]}


def _mistake_state(db: Session, question_id: int) -> str | None:
    row = db.scalar(
        select(MistakeBook)
        .where(MistakeBook.question_id == question_id)
        .order_by(MistakeBook.id.desc())
        .limit(1)
    )
    return row.action if row else None


def _add_mistake(db: Session, question_id: int, reason: str) -> bool:
    if _mistake_state(db, question_id) == "added":
        return False
    db.add(MistakeBook(question_id=question_id, action="added", reason=reason))
    return True


def _remove_mistake(db: Session, question_id: int, reason: str) -> bool:
    if _mistake_state(db, question_id) != "added":
        return False
    db.add(MistakeBook(question_id=question_id, action="removed", reason=reason))
    return True


def apply_rating(
    db: Session,
    question: Question,
    q: int,
    mode: str = "practice",
    *,
    sprint: bool = False,
) -> dict[str, Any]:
    if not 0 <= q <= 5:
        raise ValueError("q 必须在 0..5")
    settings = get_settings(db)
    schedule = db.get(ReviewSchedule, question.id)
    if schedule is None:
        schedule = ReviewSchedule(
            question_id=question.id, ef=float(settings["sm2.ef_initial"])
        )
        db.add(schedule)
        db.flush()
    elif schedule.first_reviewed_at is None and schedule.reps == 0:
        # 新题首次评分使用当前配置的 EF 初值。
        schedule.ef = float(settings["sm2.ef_initial"])

    today = local_today()
    today_s = today.isoformat()
    due = bool(
        schedule.next_review_date
        and schedule.next_review_date <= today_s
        and schedule.first_reviewed_at is not None
    )
    is_new = schedule.first_reviewed_at is None
    same_day = schedule.last_schedule_date == today_s
    early = bool(settings.get("review.early_advances"))

    state = Sm2State(
        reps=schedule.reps,
        ef=schedule.ef,
        interval_days=schedule.interval_days,
        lapses=schedule.lapses,
        next_review_date=schedule.next_review_date,
        first_reviewed_at=schedule.first_reviewed_at,
        last_schedule_date=schedule.last_schedule_date,
    )
    new_state, applied = apply_sm2(
        state,
        q,
        today,
        early_advances=early,
        interval_cap_days=int(settings["sm2.interval_cap_days"]),
        ef_min=float(settings["sm2.ef_min"]),
    )
    # 冲刺模式：未到期且未学过的题，自评熟悉/精通不推进排程。
    if sprint and is_new and not due and q >= 3 and not early:
        new_state = state
        applied = False

    schedule.last_q = q
    schedule.last_rated_at = utcnow()
    if applied:
        schedule.reps = new_state.reps
        schedule.ef = new_state.ef
        schedule.interval_days = new_state.interval_days
        schedule.lapses = new_state.lapses
        schedule.next_review_date = new_state.next_review_date
        schedule.first_reviewed_at = new_state.first_reviewed_at
        schedule.last_schedule_date = new_state.last_schedule_date

    record = MasteryRecord(question_id=question.id, q=q, mode=mode)
    db.add(record)
    db.flush()

    mistake_added = False
    mistake_removed = False
    if q < 3:
        mistake_added = _add_mistake(db, question.id, "unfamiliar")
    elif q >= 4:
        streak_target = int(settings.get("mistake.auto_remove_streak") or 0)
        if streak_target > 0 and _mistake_state(db, question.id) == "added":
            recent = db.scalars(
                select(MasteryRecord.q)
                .where(MasteryRecord.question_id == question.id)
                .order_by(MasteryRecord.id.desc())
                .limit(streak_target)
            ).all()
            if len(recent) >= streak_target and all(value >= 4 for value in recent):
                mistake_removed = _remove_mistake(
                    db, question.id, "auto_pass_twice"
                )

    from .audit import audit

    audit(
        db,
        "rating",
        "question",
        question.id,
        {
            "q": q,
            "mode": mode,
            "schedule_applied": applied,
            "same_day": same_day,
            "mistake_added": mistake_added,
            "mistake_removed": mistake_removed,
        },
    )
    db.flush()

    return {
        "question_id": question.id,
        "q": q,
        "mastery": mastery_from_q(q),
        "schedule_applied": applied,
        "schedule": schedule_dict(schedule),
        "mistake_added": mistake_added,
        "mistake_removed": mistake_removed,
    }


def mistake_questions(db: Session, category_id: int | None = None) -> list[dict[str, Any]]:
    rows = db.scalars(select(MistakeBook).order_by(MistakeBook.id.desc())).all()
    latest: dict[int, MistakeBook] = {}
    for row in rows:
        if row.question_id not in latest:
            latest[row.question_id] = row
    qids = _category_question_ids(db, category_id)
    selected: list[tuple[Question, MistakeBook]] = []
    for question_id, row in latest.items():
        if row.action != "added":
            continue
        if qids is not None and question_id not in qids:
            continue
        question = db.get(Question, question_id)
        if not question or question.is_deleted or question.status != "active":
            continue
        selected.append((question, row))
    selected.sort(key=lambda pair: pair[1].created_at, reverse=True)
    items = serialize_question_list(db, [q for q, _ in selected], quiz=True)
    for item, (_question, row) in zip(items, selected):
        item["added_at"] = row.created_at.isoformat()
        item["reason"] = row.reason
    return items


def remove_mistake(db: Session, question_id: int) -> bool:
    removed = _remove_mistake(db, question_id, "manual")
    if removed:
        from .audit import audit

        audit(db, "mistake_remove", "question", question_id)
    db.commit()
    return removed


def consecutive_streak(db: Session) -> int:
    rows = db.scalars(
        select(MasteryRecord.created_at).order_by(MasteryRecord.created_at.desc())
    ).all()
    days = {local_date_str(row) for row in rows}
    if not days:
        return 0
    today = local_today()
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _active_questions(db: Session, category_id: int | None) -> list[Question]:
    qids = _category_question_ids(db, category_id)
    stmt = _base_question_query()
    stmt = _apply_category_filter(stmt, qids)
    return list(db.scalars(stmt).all())


def dashboard_stats(db: Session, category_id: int | None = None) -> dict[str, Any]:
    questions = _active_questions(db, category_id)
    ids = [q.id for q in questions]
    schedules = {
        s.question_id: s
        for s in db.scalars(
            select(ReviewSchedule).where(ReviewSchedule.question_id.in_(ids))
        ).all()
    } if ids else {}
    today = today_str()

    learned = sum(
        1 for qid in ids if schedules.get(qid) and schedules[qid].first_reviewed_at
    )
    mastered = sum(1 for qid in ids if schedules.get(qid) and schedules[qid].last_q == 5)
    due = sum(
        1
        for qid in ids
        if schedules.get(qid)
        and schedules[qid].first_reviewed_at
        and schedules[qid].next_review_date
        and schedules[qid].next_review_date <= today
    )
    mistake_rows = db.scalars(
        select(MistakeBook).order_by(MistakeBook.id.desc())
    ).all()
    latest_mistake: dict[int, str] = {}
    for row in mistake_rows:
        latest_mistake.setdefault(row.question_id, row.action)
    mistakes = sum(
        1 for qid in ids if latest_mistake.get(qid) == "added"
    )
    knowledge_ids = db.scalars(
        select(KnowledgePoint.id).where(
            KnowledgePoint.status == "active", KnowledgePoint.is_deleted == 0
        )
    ).all()

    # 最近 7 天复习趋势（按本地日期）。
    trend = []
    for offset in range(6, -1, -1):
        day = local_today() - timedelta(days=offset)
        start, end = local_day_bounds_utc(day)
        stmt = select(MasteryRecord).where(
            MasteryRecord.created_at >= start,
            MasteryRecord.created_at < end,
        )
        if ids:
            stmt = stmt.where(MasteryRecord.question_id.in_(ids))
        else:
            stmt = stmt.where(MasteryRecord.id == -1)
        records = db.scalars(stmt).all()
        correct = sum(1 for r in records if r.q >= 3)
        trend.append(
            {
                "date": day.isoformat(),
                "label": f"{day.month}/{day.day}",
                "reviews": len(records),
                "accuracy": round(correct / len(records) * 100, 1) if records else None,
            }
        )

    return {
        "definitions_version": DEFINITIONS_VERSION,
        "total_questions": len(ids),
        "learned": learned,
        "unlearned": len(ids) - learned,
        "due": due,
        "mastered": mastered,
        "mistakes": mistakes,
        "streak": consecutive_streak(db),
        "knowledge_count": len(knowledge_ids),
        "trend": trend,
    }


def mastery_distribution(db: Session, category_id: int | None = None) -> dict[str, Any]:
    questions = _active_questions(db, category_id)
    ids = [q.id for q in questions]
    schedules = {
        s.question_id: s
        for s in db.scalars(
            select(ReviewSchedule).where(ReviewSchedule.question_id.in_(ids))
        ).all()
    } if ids else {}
    counts = {"mastered": 0, "familiar": 0, "unfamiliar": 0, "unlearned": 0}
    for qid in ids:
        mastery = mastery_from_q(
            schedules[qid].last_q if qid in schedules else None
        )
        counts[mastery] += 1
    return counts | {"total": len(ids), "definitions_version": DEFINITIONS_VERSION}


def knowledge_coverage(db: Session) -> dict[str, Any]:
    knowledge_count = int(
        db.scalar(
            select(func.count(KnowledgePoint.id)).where(
                KnowledgePoint.status == "active", KnowledgePoint.is_deleted == 0
            )
        )
        or 0
    )
    linked_questions = int(
        db.scalar(select(func.count(func.distinct(QuestionKnowledge.question_id)))) or 0
    )
    active_questions = int(
        db.scalar(
            select(func.count(Question.id)).where(
                Question.status == "active", Question.is_deleted == 0
            )
        )
        or 0
    )
    return {
        "knowledge_count": knowledge_count,
        "questions_linked": linked_questions,
        "questions_total": active_questions,
        "unlinked_questions": max(0, active_questions - linked_questions),
        "coverage": round(linked_questions / active_questions * 100, 1)
        if active_questions
        else 0.0,
        "definitions_version": DEFINITIONS_VERSION,
    }


def unfamiliar_distribution(db: Session, category_id: int | None = None) -> list[dict]:
    questions = _active_questions(db, category_id)
    ids = [q.id for q in questions]
    if not ids:
        return []
    schedules = {
        s.question_id: s
        for s in db.scalars(
            select(ReviewSchedule).where(
                ReviewSchedule.question_id.in_(ids),
                ReviewSchedule.last_q == 2,
            )
        ).all()
    }
    if not schedules:
        return []
    cmap = category_map(db)
    paths = {}
    for cid, cat in cmap.items():
        paths[cid] = category_path(cid, cmap)
    rows = db.execute(
        select(QuestionCategory.question_id, QuestionCategory.category_id).where(
            QuestionCategory.question_id.in_(list(schedules.keys()))
        )
    ).all()
    grouped: dict[str, int] = {}
    for question_id, category_id_value in rows:
        path = paths.get(category_id_value, "未分类")
        parts = path.split("/")
        label = parts[1] if len(parts) >= 2 else parts[0]
        grouped[label] = grouped.get(label, 0) + 1
    result = [{"label": k, "value": v} for k, v in grouped.items()]
    result.sort(key=lambda x: (-x["value"], x["label"]))
    return result
