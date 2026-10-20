"""本地导入与批次管理路由。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import MAX_IMPORT_BYTES, MAX_IMPORT_ROWS
from ..database import get_db
from ..errors import ApiError, ok
from ..models import (
    ImportBatch,
    KnowledgeOrigin,
    KnowledgePoint,
    PendingItem,
    Question,
    QuestionOrigin,
    User,
)
from ..security import get_current_user
from ..services.audit import audit
from ..services.cleaning import clean_source_text
from ..services.import_parsers import decode_bytes, parse_content
from ..services.ingest import ingest_parse_result
from ..services.serializers import serialize_batch
from ..services.settings_service import get_settings
from ..utils.text import sha256_bytes
from ..utils.timeutil import utcnow

router = APIRouter(prefix="/import", tags=["import"])


async def _run_import(
    db: Session,
    fmt: str,
    *,
    file: UploadFile | None,
    text: str | None,
    filename: str | None,
    username: str,
) -> dict[str, Any]:
    settings = get_settings(db)
    max_bytes = int(settings.get("import.max_bytes", MAX_IMPORT_BYTES))
    max_rows = int(settings.get("import.max_rows", MAX_IMPORT_ROWS))

    if file is not None:
        raw = await file.read()
        if len(raw) > max_bytes:
            raise ApiError(413, "VALIDATION_ERROR", "文件超过大小上限，请拆分后导入")
        if not raw:
            raise ApiError(400, "VALIDATION_ERROR", "文件为空")
        try:
            content = decode_bytes(raw)
        except ValueError as exc:
            raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc
        filename = filename or file.filename or f"upload.{fmt}"
        file_hash = sha256_bytes(raw)
    elif text and text.strip():
        content = text
        raw = content.encode("utf-8")
        filename = filename or f"paste.{fmt}"
        file_hash = sha256_bytes(raw)
        if len(raw) > max_bytes:
            raise ApiError(413, "VALIDATION_ERROR", "粘贴内容超过大小上限")
    else:
        raise ApiError(400, "VALIDATION_ERROR", "请上传文件或粘贴文本")

    previous = db.scalar(
        select(ImportBatch).where(ImportBatch.file_hash == file_hash).limit(1)
    )
    clean_warnings: list[dict] = []
    if fmt == "md":
        content, removed = clean_source_text(content)
        if removed:
            clean_warnings.append(
                {
                    "message": f"已清洗 {len(removed)} 行广告/水印/纯符号内容",
                    "lines": removed[:20],
                }
            )
    batch = ImportBatch(
        filename=filename,
        format=fmt,
        status="processing",
        operator=username,
        file_hash=file_hash,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    try:
        parsed = parse_content(fmt, content)
    except ValueError as exc:
        batch.status = "failed"
        batch.error_log = json.dumps(
            {"errors": [{"message": str(exc)}], "warnings": []}, ensure_ascii=False
        )
        batch.finished_at = utcnow()
        db.commit()
        return {
            "batch": serialize_batch(batch),
            "errors": [{"message": str(exc)}],
            "warnings": [],
        }

    if parsed.total_rows > max_rows:
        batch.status = "failed"
        batch.total_rows = parsed.total_rows
        batch.fail_rows = parsed.total_rows
        batch.error_log = json.dumps(
            {
                "errors": [
                    {
                        "message": f"行数 {parsed.total_rows} 超过上限 {max_rows}，请拆分文件"
                    }
                ],
                "warnings": [],
            },
            ensure_ascii=False,
        )
        batch.finished_at = utcnow()
        db.commit()
        raise ApiError(
            413,
            "VALIDATION_ERROR",
            f"行数超过上限 {max_rows}，请拆分文件",
            {"batch": serialize_batch(batch)},
        )

    try:
        outcome = ingest_parse_result(
            db,
            parsed,
            source_type="import",
            origin_prefix=filename,
            import_batch_id=batch.id,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        batch = db.get(ImportBatch, batch.id)
        if batch:
            batch.status = "failed"
            batch.error_log = json.dumps(
                {"errors": [{"message": f"导入失败：{exc}"}], "warnings": []},
                ensure_ascii=False,
            )
            batch.finished_at = utcnow()
            db.commit()
        raise ApiError(500, "INTERNAL_ERROR", "导入处理失败，请查看批次日志") from exc

    ok_rows = outcome.pending_created + outcome.questions_created + outcome.duplicates
    fail_rows = max(0, parsed.total_rows - ok_rows)
    warnings = list(parsed.warnings) + outcome.warnings + clean_warnings
    if previous:
        warnings.append(
            {
                "message": f"相同文件此前已导入过（批次 #{previous.id}），已按内容哈希去重"
            }
        )
    if fail_rows == 0 and not parsed.errors:
        status = "success"
    elif ok_rows > 0:
        status = "partial"
    else:
        status = "failed"

    batch.status = status
    batch.total_rows = parsed.total_rows
    batch.ok_rows = ok_rows
    batch.fail_rows = fail_rows
    batch.error_log = json.dumps(
        {"errors": parsed.errors, "warnings": warnings}, ensure_ascii=False
    )
    batch.finished_at = utcnow()
    audit(
        db,
        "import",
        "import_batch",
        batch.id,
        {
            "filename": filename,
            "format": fmt,
            "ok_rows": ok_rows,
            "fail_rows": fail_rows,
        },
    )
    db.commit()
    db.refresh(batch)
    return {
        "batch": serialize_batch(batch),
        "errors": parsed.errors,
        "warnings": warnings,
        "outcome": {
            "pending_created": outcome.pending_created,
            "questions_created": outcome.questions_created,
            "duplicates": outcome.duplicates,
        },
    }


@router.post("/markdown")
async def import_markdown(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(
        await _run_import(
            db, "md", file=file, text=text, filename=filename, username=user.username
        )
    )


@router.post("/paste")
async def import_paste(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(
        await _run_import(
            db, "md", file=file, text=text, filename=filename, username=user.username
        )
    )


@router.post("/csv")
async def import_csv(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(
        await _run_import(
            db, "csv", file=file, text=text, filename=filename, username=user.username
        )
    )


@router.post("/json")
async def import_json(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(
        await _run_import(
            db, "json", file=file, text=text, filename=filename, username=user.username
        )
    )


@router.get("/batches")
def list_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    total = int(db.scalar(select(func.count(ImportBatch.id))) or 0)
    rows = db.scalars(
        select(ImportBatch)
        .order_by(ImportBatch.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        {
            "items": [serialize_batch(batch) for batch in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise ApiError(404, "NOT_FOUND", "导入批次不存在")
    report = {"errors": [], "warnings": []}
    if batch.error_log:
        try:
            report = json.loads(batch.error_log)
        except (TypeError, ValueError):
            report = {"errors": [{"message": batch.error_log}], "warnings": []}
    pending_counts = dict(
        db.execute(
            select(PendingItem.status, func.count(PendingItem.id))
            .where(PendingItem.import_batch_id == batch_id)
            .group_by(PendingItem.status)
        ).all()
    )
    return ok(
        {
            "batch": serialize_batch(batch),
            "report": report,
            "pending_counts": {k: int(v) for k, v in pending_counts.items()},
        }
    )


@router.delete("/batches/{batch_id}")
def delete_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise ApiError(404, "NOT_FOUND", "导入批次不存在")

    question_ids = list(
        db.scalars(
            select(QuestionOrigin.question_id).where(
                QuestionOrigin.import_batch_id == batch_id
            )
        ).all()
    )
    knowledge_ids = list(
        db.scalars(
            select(KnowledgeOrigin.knowledge_id).where(
                KnowledgeOrigin.import_batch_id == batch_id
            )
        ).all()
    )
    db.execute(
        delete(QuestionOrigin).where(QuestionOrigin.import_batch_id == batch_id)
    )
    db.execute(
        delete(KnowledgeOrigin).where(KnowledgeOrigin.import_batch_id == batch_id)
    )
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
    db.execute(delete(PendingItem).where(PendingItem.import_batch_id == batch_id))
    audit(
        db,
        "import_batch_delete",
        "import_batch",
        batch.id,
        {
            "archived_questions": archived_questions,
            "archived_knowledge": archived_knowledge,
        },
    )
    db.delete(batch)
    db.commit()
    return ok(
        {
            "archived_questions": archived_questions,
            "archived_knowledge": archived_knowledge,
        },
        "批次来源已删除，无来源内容已归档",
    )
