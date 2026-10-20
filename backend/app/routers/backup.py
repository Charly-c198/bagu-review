"""SQLite 备份与恢复。"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DATA_DIR, DB_PATH
from ..database import engine, get_db, init_db
from ..errors import ApiError, ok
from ..models import CrawlTask, User
from ..security import ensure_default_user, get_current_user
from ..services.audit import audit

router = APIRouter(prefix="/backup", tags=["backup"])
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
KEEP = 7


def _create_backup(prefix: str = "bajiu") -> Path:
    if not str(DB_PATH).endswith(".db") and not DB_PATH.exists():
        raise ApiError(400, "VALIDATION_ERROR", "当前不是 SQLite 数据库，无法备份")
    if not DB_PATH.exists():
        raise ApiError(404, "NOT_FOUND", "数据库文件不存在")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{prefix}-{stamp}.db"
    source_conn = sqlite3.connect(DB_PATH)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    backups = sorted(BACKUP_DIR.glob("bajiu-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[KEEP:]:
        old.unlink(missing_ok=True)
    return target


@router.post("/export")
def backup_export(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    target = _create_backup()
    audit(db, "backup_export", "backup", None, {"file": target.name})
    db.commit()
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=target.name,
    )


@router.get("/list")
def backup_list(_user: User = Depends(get_current_user)):
    files = sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return ok(
        [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).isoformat(),
            }
            for path in files
        ]
    )


@router.post("/import")
async def backup_import(
    file: UploadFile = File(...),
    confirm: bool = Form(default=False),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if not confirm:
        raise ApiError(400, "VALIDATION_ERROR", "恢复会覆盖当前数据库，请显式确认")
    running = db.scalar(
        select(CrawlTask.id).where(CrawlTask.status == "running").limit(1)
    )
    if running:
        raise ApiError(409, "CONFLICT", "有爬虫任务正在运行，请稍后再恢复")
    raw = await file.read()
    if not raw.startswith(b"SQLite format 3\x00"):
        raise ApiError(400, "VALIDATION_ERROR", "不是有效的 SQLite 数据库文件")
    temp = Path(tempfile.gettempdir()) / f"bajiu-restore-{datetime.now().timestamp()}.db"
    temp.write_bytes(raw)
    try:
        conn = sqlite3.connect(temp)
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise ApiError(400, "VALIDATION_ERROR", "备份文件完整性校验失败")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            required = {"users", "questions", "knowledge_points", "review_schedule"}
            if not required.issubset(tables):
                raise ApiError(400, "VALIDATION_ERROR", "备份文件缺少必要数据表")
        finally:
            conn.close()

        safety = None
        if DB_PATH.exists():
            safety = _create_backup("pre-restore")
        db.close()
        engine.dispose()
        for suffix in ("-wal", "-shm"):
            Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
        try:
            shutil.copyfile(temp, DB_PATH)
            init_db()
        except Exception:
            if safety:
                shutil.copyfile(safety, DB_PATH)
                init_db()
            raise
        ensure_default_user()
        return ok(
            {"restored": temp.name, "safety_backup": safety.name if safety else None},
            "备份已恢复，请刷新页面；如异常请重启服务",
        )
    finally:
        temp.unlink(missing_ok=True)
