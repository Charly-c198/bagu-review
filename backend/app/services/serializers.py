"""资源序列化：统一前后端字段与掌握度口径。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Bookmark,
    Category,
    Company,
    CrawlSource,
    CrawlTask,
    CrawlTaskFile,
    ImportBatch,
    KnowledgeOrigin,
    KnowledgePoint,
    MasteryRecord,
    MistakeBook,
    PendingItem,
    Question,
    QuestionCategory,
    QuestionCompany,
    QuestionKnowledge,
    QuestionOrigin,
    QuestionTag,
    ReviewSchedule,
    Tag,
)
from ..utils.timeutil import local_date_str
from .categories import category_map, category_path, category_paths_from_ids

MASTERY_LABELS = {2: "unfamiliar", 4: "familiar", 5: "mastered"}


def json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except (TypeError, ValueError):
        pass
    return []


def json_obj(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass
    return {}


def mastery_from_q(q: int | None) -> str:
    if q is None:
        return "unlearned"
    if q >= 5:
        return "mastered"
    if q >= 3:
        return "familiar"
    return "unfamiliar"


def schedule_dict(schedule: ReviewSchedule | None) -> dict:
    if schedule is None:
        return {
            "reps": 0,
            "ef": 2.5,
            "interval_days": 0,
            "lapses": 0,
            "next_review_date": None,
            "last_q": None,
            "first_reviewed_at": None,
            "last_rated_at": None,
            "last_schedule_date": None,
            "is_new": True,
        }
    return {
        "reps": schedule.reps,
        "ef": round(schedule.ef, 2),
        "interval_days": schedule.interval_days,
        "lapses": schedule.lapses,
        "next_review_date": schedule.next_review_date,
        "last_q": schedule.last_q,
        "first_reviewed_at": schedule.first_reviewed_at,
        "last_rated_at": schedule.last_rated_at.isoformat() if schedule.last_rated_at else None,
        "last_schedule_date": schedule.last_schedule_date,
        "is_new": schedule.first_reviewed_at is None,
    }


def latest_mistake_action(db: Session, question_id: int) -> MistakeBook | None:
    return db.scalar(
        select(MistakeBook)
        .where(MistakeBook.question_id == question_id)
        .order_by(MistakeBook.id.desc())
        .limit(1)
    )


def question_tags(db: Session, question_id: int) -> list[Tag]:
    rows = db.execute(
        select(Tag)
        .join(QuestionTag, QuestionTag.tag_id == Tag.id)
        .where(QuestionTag.question_id == question_id)
        .order_by(Tag.name)
    ).scalars().all()
    return list(rows)


def question_companies(db: Session, question_id: int) -> list[Company]:
    rows = db.execute(
        select(Company)
        .join(QuestionCompany, QuestionCompany.company_id == Company.id)
        .where(QuestionCompany.question_id == question_id)
        .order_by(Company.name)
    ).scalars().all()
    return list(rows)


def serialize_question(
    db: Session,
    question: Question,
    *,
    detail: bool = False,
    quiz: bool = False,
    cat_map: dict[int, Category] | None = None,
    list_ctx: Any = None,
) -> dict[str, Any]:
    """list_ctx 为 batch_loader.QuestionListContext 时只读内存，不再查库。"""
    mapping = (list_ctx.cat_map if list_ctx else cat_map) or category_map(db)
    if list_ctx is not None:
        schedule = list_ctx.schedules.get(question.id)
        tags = list_ctx.tags.get(question.id, [])
        companies = list_ctx.companies.get(question.id, [])
        category_ids = list_ctx.categories.get(question.id, [])
        bookmarked = question.id in list_ctx.bookmarked
        in_mistake = list_ctx.mistake_added.get(question.id, False)
    else:
        schedule = db.get(ReviewSchedule, question.id)
        tags = question_tags(db, question.id)
        companies = question_companies(db, question.id)
        category_ids = list(
            db.scalars(
                select(QuestionCategory.category_id)
                .where(QuestionCategory.question_id == question.id)
                .order_by(QuestionCategory.category_id)
            ).all()
        )
        bookmarked = (
            db.scalar(select(Bookmark.id).where(Bookmark.question_id == question.id))
            is not None
        )
        mistake = latest_mistake_action(db, question.id)
        in_mistake = bool(mistake and mistake.action == "added")
    mastery = mastery_from_q(schedule.last_q if schedule else None)
    paths = category_paths_from_ids(category_ids, mapping)
    primary_path = (
        max(paths, key=lambda item: (item["level"], len(item["path"]))) if paths else None
    )

    data: dict[str, Any] = {
        "id": question.id,
        "stem": question.stem,
        "difficulty": question.difficulty,
        "frequency": question.frequency,
        "status": question.status,
        "source_type": question.source_type,
        "is_deleted": bool(question.is_deleted),
        "mastery": mastery,
        "schedule": schedule_dict(schedule),
        "tags": [{"id": t.id, "name": t.name} for t in tags],
        "companies": [{"id": c.id, "name": c.name} for c in companies],
        "categories": paths,
        "category_path": primary_path["path"] if primary_path else "",
        "bookmarked": bookmarked,
        "in_mistake": in_mistake,
        "created_at": question.created_at.isoformat(),
        "updated_at": question.updated_at.isoformat(),
    }
    if quiz:
        return data

    data["answer"] = question.answer
    data["key_points"] = json_list(question.key_points)
    data["notes"] = question.notes

    if detail:
        origins = db.scalars(
            select(QuestionOrigin)
            .where(QuestionOrigin.question_id == question.id)
            .order_by(QuestionOrigin.id.desc())
        ).all()
        data["origins"] = [
            {
                "id": o.id,
                "source_type": o.source_type,
                "origin_ref": o.origin_ref,
                "import_batch_id": o.import_batch_id,
                "crawl_task_id": o.crawl_task_id,
                "content_hash": o.content_hash,
                "created_at": o.created_at.isoformat(),
            }
            for o in origins
        ]
        history = db.scalars(
            select(MasteryRecord)
            .where(MasteryRecord.question_id == question.id)
            .order_by(MasteryRecord.id.desc())
            .limit(50)
        ).all()
        data["history"] = [
            {
                "id": h.id,
                "q": h.q,
                "mode": h.mode,
                "created_at": h.created_at.isoformat(),
                "local_date": local_date_str(h.created_at),
            }
            for h in history
        ]
        links = db.execute(
            select(KnowledgePoint, QuestionKnowledge.relation_type)
            .join(
                QuestionKnowledge,
                QuestionKnowledge.knowledge_id == KnowledgePoint.id,
            )
            .where(
                QuestionKnowledge.question_id == question.id,
                KnowledgePoint.is_deleted == 0,
            )
            .order_by(KnowledgePoint.id)
        ).all()
        data["knowledge"] = [
            {
                "id": kp.id,
                "title": kp.title,
                "kind": kp.kind,
                "relation_type": relation,
                "category_path": category_path(kp.category_id, mapping),
            }
            for kp, relation in links
        ]
    return data


def serialize_knowledge(
    db: Session,
    knowledge: KnowledgePoint,
    *,
    detail: bool = False,
    cat_map: dict[int, Category] | None = None,
    list_ctx: Any = None,
) -> dict[str, Any]:
    mapping = (list_ctx.cat_map if list_ctx else cat_map) or category_map(db)
    data: dict[str, Any] = {
        "id": knowledge.id,
        "title": knowledge.title,
        "content": knowledge.content,
        "kind": knowledge.kind,
        "aliases": json_list(knowledge.aliases),
        "status": knowledge.status,
        "source_type": knowledge.source_type,
        "is_deleted": bool(knowledge.is_deleted),
        "category_id": knowledge.category_id,
        "category_path": category_path(knowledge.category_id, mapping),
        "created_at": knowledge.created_at.isoformat(),
        "updated_at": knowledge.updated_at.isoformat(),
    }
    if detail:
        origins = db.scalars(
            select(KnowledgeOrigin)
            .where(KnowledgeOrigin.knowledge_id == knowledge.id)
            .order_by(KnowledgeOrigin.id.desc())
        ).all()
        data["origins"] = [
            {
                "id": o.id,
                "source_type": o.source_type,
                "origin_ref": o.origin_ref,
                "import_batch_id": o.import_batch_id,
                "crawl_task_id": o.crawl_task_id,
                "created_at": o.created_at.isoformat(),
            }
            for o in origins
        ]
        rows = db.execute(
            select(Question, QuestionKnowledge.relation_type)
            .join(
                QuestionKnowledge,
                QuestionKnowledge.question_id == Question.id,
            )
            .where(
                QuestionKnowledge.knowledge_id == knowledge.id,
                Question.is_deleted == 0,
            )
            .order_by(Question.id)
        ).all()
        data["questions"] = [
            {
                "id": q.id,
                "stem": q.stem,
                "relation_type": relation,
                "mastery": mastery_from_q(
                    (db.get(ReviewSchedule, q.id).last_q if db.get(ReviewSchedule, q.id) else None)
                ),
            }
            for q, relation in rows
        ]
    else:
        from sqlalchemy import func

        if list_ctx is not None:
            data["question_count"] = list_ctx.question_counts.get(knowledge.id, 0)
            return data
        data["question_count"] = int(
            db.scalar(
                select(func.count(QuestionKnowledge.question_id)).where(
                    QuestionKnowledge.knowledge_id == knowledge.id
                )
            )
            or 0
        )
    return data


def serialize_pending(db: Session, item: PendingItem, include_meta: bool = True) -> dict:
    data: dict[str, Any] = {
        "id": item.id,
        "item_type": item.item_type,
        "source_type": item.source_type,
        "status": item.status,
        "origin_ref": item.origin_ref,
        "raw_text": item.raw_text,
        "stem": item.stem,
        "answer": item.answer,
        "knowledge_title": item.knowledge_title,
        "knowledge_content": item.knowledge_content,
        "parse_confidence": item.parse_confidence,
        "content_hash": item.content_hash,
        "simhash": item.simhash,
        "dup_of": item.dup_of,
        "dup_of_pending_id": item.dup_of_pending_id,
        "dup_of_knowledge_id": item.dup_of_knowledge_id,
        "created_question_id": item.created_question_id,
        "created_knowledge_id": item.created_knowledge_id,
        "reviewer_note": item.reviewer_note,
        "import_batch_id": item.import_batch_id,
        "crawl_task_id": item.crawl_task_id,
        "created_at": item.created_at.isoformat(),
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
    }
    if include_meta:
        data["suggested_meta"] = json_obj(item.suggested_meta)
    return data


def serialize_batch(batch: ImportBatch) -> dict:
    return {
        "id": batch.id,
        "filename": batch.filename,
        "format": batch.format,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "ok_rows": batch.ok_rows,
        "fail_rows": batch.fail_rows,
        "file_hash": batch.file_hash,
        "operator": batch.operator,
        "created_at": batch.created_at.isoformat(),
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
    }


def serialize_source(source: CrawlSource) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "source_kind": source.source_kind,
        "url": source.url,
        "enabled": bool(source.enabled),
        "user_agent": source.user_agent,
        "interval_sec": source.interval_sec,
        "timeout_sec": source.timeout_sec,
        "max_retries": source.max_retries,
        "max_files_per_run": source.max_files_per_run,
        "last_run_at": source.last_run_at.isoformat() if source.last_run_at else None,
        "next_run_at": source.next_run_at.isoformat() if source.next_run_at else None,
        "created_at": source.created_at.isoformat(),
    }


def serialize_task(task: CrawlTask) -> dict:
    return {
        "id": task.id,
        "source_id": task.source_id,
        "parent_task_id": task.parent_task_id,
        "status": task.status,
        "attempt": task.attempt,
        "total_files": task.total_files,
        "success_files": task.success_files,
        "failed_files": task.failed_files,
        "log": task.log,
        "created_at": task.created_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def serialize_task_file(row: CrawlTaskFile) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "url": row.url,
        "status": row.status,
        "http_status": row.http_status,
        "parsed_count": row.parsed_count,
        "error": row.error,
        "cached_path": row.cached_path,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
    }
