"""爬虫源与任务路由。"""

from __future__ import annotations

import os
import threading

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import (
    CrawlSource,
    CrawlTask,
    CrawlTaskFile,
    KnowledgeOrigin,
    KnowledgePoint,
    PendingItem,
    Question,
    QuestionOrigin,
    User,
)
from ..schemas import SourceCreate, SourceUpdate
from ..security import get_current_user
from ..services.audit import audit
from ..services.crawler import run_task, validate_source_url
from ..services.nowcoder import validate_nowcoder_source
from ..services.serializers import serialize_source, serialize_task, serialize_task_file

router = APIRouter(prefix="/crawl", tags=["crawl"])


def _validate_source_url(kind: str, url: str) -> None:
    if kind == "github":
        validate_source_url(url)
    elif kind == "nowcoder":
        validate_nowcoder_source(url)
    else:
        raise ApiError(400, "VALIDATION_ERROR", "source_kind 仅支持 github / nowcoder")


@router.get("/sources")
def list_sources(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = db.scalars(select(CrawlSource).order_by(CrawlSource.id)).all()
    return ok([serialize_source(source) for source in rows])


@router.post("/sources")
def create_source(
    payload: SourceCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if payload.source_kind == "github":
        validate_source_url(payload.url)
    else:
        validate_nowcoder_source(payload.url)
    if db.scalar(select(CrawlSource).where(CrawlSource.url == payload.url)):
        raise ApiError(409, "CONFLICT", "该源 URL 已存在")
    source = CrawlSource(
        name=payload.name,
        source_kind=payload.source_kind,
        url=payload.url,
        enabled=1 if payload.enabled else 0,
        user_agent=payload.user_agent,
        interval_sec=payload.interval_sec,
        timeout_sec=payload.timeout_sec,
        max_retries=payload.max_retries,
        max_files_per_run=payload.max_files_per_run,
    )
    db.add(source)
    db.flush()
    audit(db, "crawl_source_create", "crawl_source", source.id, {"url": source.url})
    db.commit()
    db.refresh(source)
    return ok(serialize_source(source), "已创建")


@router.patch("/sources/{source_id}")
def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    source = db.get(CrawlSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "源不存在")
    fields = payload.model_fields_set
    if payload.url is not None and payload.url != source.url:
        _validate_source_url(source.source_kind, payload.url)
        if db.scalar(
            select(CrawlSource).where(
                CrawlSource.url == payload.url, CrawlSource.id != source.id
            )
        ):
            raise ApiError(409, "CONFLICT", "该源 URL 已存在")
        source.url = payload.url
    if payload.name is not None:
        source.name = payload.name
    if payload.enabled is not None:
        source.enabled = 1 if payload.enabled else 0
    if payload.user_agent is not None:
        source.user_agent = payload.user_agent
    if payload.interval_sec is not None:
        source.interval_sec = payload.interval_sec
    if payload.timeout_sec is not None:
        source.timeout_sec = payload.timeout_sec
    if payload.max_retries is not None:
        source.max_retries = payload.max_retries
    if payload.max_files_per_run is not None:
        source.max_files_per_run = payload.max_files_per_run
    audit(db, "crawl_source_update", "crawl_source", source.id, sorted(fields))
    db.commit()
    db.refresh(source)
    return ok(serialize_source(source), "已保存")


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    source = db.get(CrawlSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "源不存在")
    task_ids = list(
        db.scalars(
            select(CrawlTask.id).where(CrawlTask.source_id == source_id)
        ).all()
    )
    question_origin_cond = QuestionOrigin.source_id == source_id
    knowledge_origin_cond = KnowledgeOrigin.source_id == source_id
    if task_ids:
        question_origin_cond = or_(
            question_origin_cond, QuestionOrigin.crawl_task_id.in_(task_ids)
        )
        knowledge_origin_cond = or_(
            knowledge_origin_cond, KnowledgeOrigin.crawl_task_id.in_(task_ids)
        )
    question_ids = list(
        db.scalars(
            select(QuestionOrigin.question_id).where(question_origin_cond)
        ).all()
    )
    knowledge_ids = list(
        db.scalars(
            select(KnowledgeOrigin.knowledge_id).where(knowledge_origin_cond)
        ).all()
    )
    db.execute(delete(QuestionOrigin).where(question_origin_cond))
    db.execute(delete(KnowledgeOrigin).where(knowledge_origin_cond))
    archived_questions = 0
    archived_knowledge = 0
    for question_id in set(question_ids):
        if not db.scalar(
            select(QuestionOrigin.id).where(
                QuestionOrigin.question_id == question_id
            ).limit(1)
        ):
            question = db.get(Question, question_id)
            if question and not question.is_deleted:
                question.status = "archived"
                archived_questions += 1
    for knowledge_id in set(knowledge_ids):
        if not db.scalar(
            select(KnowledgeOrigin.id).where(
                KnowledgeOrigin.knowledge_id == knowledge_id
            ).limit(1)
        ):
            knowledge = db.get(KnowledgePoint, knowledge_id)
            if knowledge and not knowledge.is_deleted:
                knowledge.status = "archived"
                archived_knowledge += 1
    if task_ids:
        db.execute(delete(PendingItem).where(PendingItem.crawl_task_id.in_(task_ids)))
    audit(db, "crawl_source_delete", "crawl_source", source.id, {"url": source.url})
    db.delete(source)
    db.commit()
    return ok(
        {
            "archived_questions": archived_questions,
            "archived_knowledge": archived_knowledge,
        },
        "源及任务已删除，无来源内容已归档",
    )


def _launch(task_id: int) -> None:
    token = os.getenv("GITHUB_TOKEN")
    thread = threading.Thread(
        target=run_task, args=(task_id, token), daemon=True, name=f"crawl-{task_id}"
    )
    thread.start()


@router.post("/sources/{source_id}/run")
def run_source(
    source_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    source = db.get(CrawlSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "源不存在")
    if not source.enabled:
        raise ApiError(409, "CONFLICT", "该源已停用，请先启用")
    if source.source_kind not in ("github", "nowcoder"):
        raise ApiError(400, "VALIDATION_ERROR", "仅支持 GitHub / 牛客公开页采集")
    task = CrawlTask(source_id=source.id, status="pending")
    db.add(task)
    db.flush()
    audit(db, "crawl_run", "crawl_task", task.id, {"source_id": source.id})
    db.commit()
    db.refresh(task)
    _launch(task.id)
    return ok(serialize_task(task), "任务已提交，正在后台采集")


@router.get("/tasks")
def list_tasks(
    source_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(CrawlTask)
    if source_id:
        stmt = stmt.where(CrawlTask.source_id == source_id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(CrawlTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        {
            "items": [serialize_task(task) for task in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/tasks/{task_id}")
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    task = db.get(CrawlTask, task_id)
    if task is None:
        raise ApiError(404, "NOT_FOUND", "任务不存在")
    files = db.scalars(
        select(CrawlTaskFile)
        .where(CrawlTaskFile.task_id == task_id)
        .order_by(CrawlTaskFile.id)
    ).all()
    return ok(
        {
            "task": serialize_task(task),
            "files": [serialize_task_file(row) for row in files],
        }
    )


@router.get("/tasks/{task_id}/files")
def get_task_files(
    task_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    task = db.get(CrawlTask, task_id)
    if task is None:
        raise ApiError(404, "NOT_FOUND", "任务不存在")
    files = db.scalars(
        select(CrawlTaskFile)
        .where(CrawlTaskFile.task_id == task_id)
        .order_by(CrawlTaskFile.id)
    ).all()
    return ok([serialize_task_file(row) for row in files])


@router.post("/tasks/{task_id}/retry")
def retry_task(
    task_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    parent = db.get(CrawlTask, task_id)
    if parent is None:
        raise ApiError(404, "NOT_FOUND", "任务不存在")
    failed = db.scalars(
        select(CrawlTaskFile).where(
            CrawlTaskFile.task_id == task_id, CrawlTaskFile.status == "failed"
        )
    ).all()
    if not failed:
        raise ApiError(409, "CONFLICT", "该任务没有失败文件")
    child = CrawlTask(
        source_id=parent.source_id,
        parent_task_id=parent.id,
        status="pending",
        attempt=parent.attempt + 1,
        total_files=len(failed),
    )
    db.add(child)
    db.flush()
    for row in failed:
        db.add(
            CrawlTaskFile(
                task_id=child.id,
                url=row.url,
                status="pending",
            )
        )
    audit(db, "crawl_retry", "crawl_task", child.id, {"parent": parent.id})
    db.commit()
    db.refresh(child)
    _launch(child.id)
    return ok(serialize_task(child), f"已创建重试任务，仅处理 {len(failed)} 个失败文件")
