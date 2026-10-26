"""M3b 周学习报告：统计本周数据 → AI 或确定性基础报告。

AI 失败或未配置时返回基础报告，不阻塞功能；报告只含统计与题目文本，
不含个人笔记或作答原文。
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import (
    InterviewReport,
    InterviewSession,
    MasteryRecord,
    MistakeBook,
    Question,
    QuestionCategory,
    ReviewSchedule,
    WeeklyReport,
)
from ..utils.timeutil import (
    local_date_str,
    local_day_bounds_utc,
    local_today,
    utcnow,
)
from .ai.common import fit_payload
from .ai.gateway import get_ai_gateway
from .ai.prompts import (
    WEEKLY_REPORT,
    get_or_create_prompt_version,
    load_prompt,
    render_system_prompt,
)
from .audit import audit
from .categories import category_map, category_path
from .review import review_summary

logger = logging.getLogger("bajiu.weekly")


class WeakPoint(BaseModel):
    label: str = ""
    reason: str = ""
    suggestion: str = ""


class WeeklyReportOutput(BaseModel):
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    weak_points: list[WeakPoint] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)


def normalize_week_start(value: date | None = None) -> date:
    anchor = value or local_today()
    return anchor - timedelta(days=anchor.weekday())


def _category_labels(db: Session, question_ids: list[int]) -> dict[int, str]:
    if not question_ids:
        return {}
    mapping = category_map(db)
    rows = db.execute(
        select(QuestionCategory.question_id, QuestionCategory.category_id)
        .where(QuestionCategory.question_id.in_(question_ids))
        .order_by(QuestionCategory.question_id, QuestionCategory.category_id)
    ).all()
    primary: dict[int, int] = {}
    for question_id, category_id in rows:
        primary.setdefault(question_id, category_id)
    labels: dict[int, str] = {}
    for question_id, category_id in primary.items():
        path = category_path(category_id, mapping)
        parts = [part for part in path.split("/") if part]
        labels[question_id] = parts[1] if len(parts) >= 2 else (parts[0] if parts else "未分类")
    return labels


def _stats(db: Session, week_start: date) -> dict[str, Any]:
    week_end = week_start + timedelta(days=6)
    start_utc, _ = local_day_bounds_utc(week_start)
    end_utc, _ = local_day_bounds_utc(week_end + timedelta(days=1))
    records = list(
        db.scalars(
            select(MasteryRecord).where(
                MasteryRecord.created_at >= start_utc,
                MasteryRecord.created_at < end_utc,
            )
        ).all()
    )
    reviews = len(records)
    correct = sum(1 for record in records if record.q >= 3)
    accuracy = round(correct / reviews * 100, 1) if reviews else None
    active_days = len({local_date_str(record.created_at) for record in records})
    mastered = len({record.question_id for record in records if record.q == 5})
    reviewed_ids = sorted({record.question_id for record in records})

    new_learned = int(
        db.scalar(
            select(func.count(ReviewSchedule.question_id)).where(
                ReviewSchedule.first_reviewed_at.is_not(None),
                ReviewSchedule.first_reviewed_at >= week_start.isoformat(),
                ReviewSchedule.first_reviewed_at <= week_end.isoformat(),
            )
        )
        or 0
    )

    mistake_rows = list(
        db.scalars(
            select(MistakeBook).where(
                MistakeBook.action == "added",
                MistakeBook.created_at >= start_utc,
                MistakeBook.created_at < end_utc,
            )
        ).all()
    )
    mistake_ids: list[int] = []
    for row in mistake_rows:
        if row.question_id not in mistake_ids:
            mistake_ids.append(row.question_id)
    samples = []
    for question_id in mistake_ids[:5]:
        question = db.get(Question, question_id)
        if question is not None and not question.is_deleted:
            samples.append(question.stem[:120])

    labels = _category_labels(db, reviewed_ids)
    grouped: dict[str, dict[str, int]] = {}
    for record in records:
        label = labels.get(record.question_id, "未分类")
        bucket = grouped.setdefault(label, {"reviews": 0, "correct": 0})
        bucket["reviews"] += 1
        if record.q >= 3:
            bucket["correct"] += 1
    categories = []
    for label, bucket in grouped.items():
        value = round(bucket["correct"] / bucket["reviews"] * 100, 1)
        categories.append(
            {"label": label, "reviews": bucket["reviews"], "accuracy": value}
        )
    categories.sort(key=lambda item: (-item["reviews"], item["label"]))
    weak_categories = [
        item for item in categories if item["reviews"] >= 3 and item["accuracy"] < 60
    ][:4]
    strong_categories = sorted(
        [item for item in categories if item["reviews"] >= 3 and item["accuracy"] >= 80],
        key=lambda item: (-item["accuracy"], -item["reviews"]),
    )[:3]

    summary = review_summary(db)
    sessions = db.execute(
        select(InterviewReport.total_score)
        .join(
            InterviewSession,
            InterviewSession.id == InterviewReport.session_id,
        )
        .where(
            InterviewSession.status == "finished",
            InterviewSession.finished_at >= start_utc,
            InterviewSession.finished_at < end_utc,
        )
    ).all()
    scores = [float(row[0]) for row in sessions if row[0] is not None]

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "days": 7,
        "reviews": reviews,
        "correct": correct,
        "accuracy": accuracy,
        "active_days": active_days,
        "new_learned": new_learned,
        "mastered": mastered,
        "mistakes_added": len(mistake_rows),
        "mistake_samples": samples,
        "categories": categories[:10],
        "weak_categories": weak_categories,
        "strong_categories": strong_categories,
        "due_total": summary["due_total"],
        "backlog": summary["backlog"],
        "interviews": {
            "count": len(scores),
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
        },
    }


def _basic_report(stats: dict[str, Any], error_code: str | None) -> dict[str, Any]:
    reviews = stats["reviews"]
    accuracy = stats["accuracy"]
    active_days = stats["active_days"]
    highlights = []
    if accuracy is not None and accuracy >= 80:
        highlights.append(f"本周正确率 {accuracy}%，掌握度保持得不错。")
    if active_days >= 5:
        highlights.append(f"本周活跃 {active_days} 天，节奏稳定。")
    if stats["new_learned"]:
        highlights.append(f"新学 {stats['new_learned']} 道题。")
    if stats["interviews"]["count"]:
        highlights.append(
            f"完成 {stats['interviews']['count']} 次仿真面试，"
            f"平均 {stats['interviews']['average_score']} 分。"
        )
    if not highlights:
        highlights = ["本周已开始积累复习数据，继续保持。"]

    weak_points = [
        {
            "label": item["label"],
            "reason": f"本周复练 {item['reviews']} 次，正确率仅 {item['accuracy']}%。",
            "suggestion": "优先重练该分类下的错题，并补充对应知识条目。",
        }
        for item in stats["weak_categories"]
    ]
    if stats["mistakes_added"]:
        weak_points.append(
            {
                "label": "错题复练",
                "reason": f"本周新增 {stats['mistakes_added']} 道错题。",
                "suggestion": "在错题本中按分类逐组重练，全部达到“熟悉”后再移出。",
            }
        )

    plan = []
    if stats["due_total"]:
        plan.append(f"优先清理 {stats['due_total']} 道到期题，避免积压。")
    if stats["mistakes_added"]:
        plan.append(f"重练本周新增的 {stats['mistakes_added']} 道错题。")
    for item in stats["weak_categories"][:2]:
        plan.append(
            f"把「{item['label']}」正确率从 {item['accuracy']}% 提升到 70% 以上。"
        )
    if stats["interviews"]["count"] == 0:
        plan.append("安排 1 次 5 题仿真面试，检验本阶段掌握情况。")
    plan.append("保持每天至少 10 道复习题，维持 SM-2 节奏。")
    plan = plan[:5]

    if reviews:
        summary = (
            f"本周（{stats['week_start']} 至 {stats['week_end']}）完成 {reviews} 次自评，"
            f"正确率 {accuracy}%，活跃 {active_days} 天，新学 {stats['new_learned']} 道题。"
            + ("整体状态稳定，下周重点放在薄弱分类与错题复练。" if not stats["weak_categories"]
               else "部分分类正确率偏低，下周优先补强。")
        )
    else:
        summary = (
            f"本周（{stats['week_start']} 至 {stats['week_end']}）暂无复习记录。"
            "建议从今日到期队列开始，恢复每日复习节奏。"
        )
    return {
        "summary": summary,
        "highlights": highlights[:4],
        "weak_points": weak_points[:4],
        "plan": plan,
        "ai_error_code": error_code,
    }


def _sanitize_ai_report(
    result: dict[str, Any], error_code: str | None
) -> dict[str, Any]:
    def _strings(value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()][:limit]

    weak_points = []
    for raw in result.get("weak_points", []) or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        weak_points.append(
            {
                "label": label,
                "reason": str(raw.get("reason") or ""),
                "suggestion": str(raw.get("suggestion") or ""),
            }
        )
    return {
        "summary": str(result.get("summary") or ""),
        "highlights": _strings(result.get("highlights"), 5),
        "weak_points": weak_points[:6],
        "plan": _strings(result.get("plan"), 8),
        "ai_error_code": error_code,
    }


def serialize_weekly(row: WeeklyReport) -> dict[str, Any]:
    try:
        report = json.loads(row.report_json)
    except (TypeError, ValueError):
        report = {}
    return {
        "id": row.id,
        "week_start": row.week_start,
        "generated_by": row.generated_by,
        "created_at": row.created_at.isoformat(),
        **(report if isinstance(report, dict) else {}),
    }


def generate_weekly_report(
    db: Session,
    *,
    week_start: date | None = None,
    mode: Literal["auto", "basic"] = "auto",
) -> WeeklyReport:
    start = normalize_week_start(week_start)
    stats = _stats(db, start)
    generated_by = "basic"
    error_code: str | None = None
    report: dict[str, Any]

    if mode == "basic":
        report = _basic_report(stats, None)
    else:
        spec = load_prompt(*WEEKLY_REPORT)
        prompt_row = get_or_create_prompt_version(db, spec)
        db.commit()
        try:
            result = get_ai_gateway(db).complete_json(
                purpose="weekly_report",
                system_prompt=render_system_prompt(spec),
                payload=fit_payload(stats, max(2000, 8000)),
                schema_model=WeeklyReportOutput,
                prompt_version_id=prompt_row.id,
                cache_input=stats,
            )
            report = _sanitize_ai_report(result, None)
            generated_by = "ai"
        except ApiError as exc:
            error_code = exc.code
            report = _basic_report(stats, error_code)

    payload = {**stats, **report, "generated_by": generated_by}
    row = db.scalar(
        select(WeeklyReport).where(WeeklyReport.week_start == start.isoformat())
    )
    if row is None:
        row = WeeklyReport(
            week_start=start.isoformat(),
            report_json=json.dumps(payload, ensure_ascii=False),
            generated_by=generated_by,
        )
        db.add(row)
        db.flush()
    else:
        row.report_json = json.dumps(payload, ensure_ascii=False)
        row.generated_by = generated_by
        row.created_at = utcnow()
    audit(
        db,
        "weekly_report_generate",
        "weekly_report",
        row.id,
        {"week_start": start.isoformat(), "generated_by": generated_by},
    )
    db.commit()
    db.refresh(row)
    return row


def list_weekly(db: Session, limit: int = 12) -> list[WeeklyReport]:
    return list(
        db.scalars(
            select(WeeklyReport)
            .order_by(WeeklyReport.week_start.desc())
            .limit(max(1, min(limit, 52)))
        ).all()
    )


def get_weekly(db: Session, report_id: int) -> WeeklyReport:
    row = db.get(WeeklyReport, report_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "周报告不存在")
    return row
