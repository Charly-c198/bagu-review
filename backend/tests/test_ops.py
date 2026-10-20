"""运维/安全补测：Markdown XSS 防线、Alembic 空库迁移。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
FRONTEND_SRC = BACKEND_DIR.parent / "frontend" / "src"


def test_markdown_script_stored_as_plain_text(auth_client: TestClient) -> None:
    stem = "XSS 测试：<script>alert(1)</script> 是什么？"
    answer = "<img src=x onerror=alert(1)> 应作为纯文本保存。"
    created = auth_client.post(
        "/api/v1/questions", json={"stem": stem, "answer": answer}
    )
    assert created.status_code == 200, created.text
    question_id = created.json()["data"]["id"]

    stored = auth_client.get(f"/api/v1/questions/{question_id}").json()["data"]
    assert "<script>alert(1)</script>" in stored["stem"]
    assert stored["answer"].startswith("<img src=x onerror=alert(1)>")

    exported = auth_client.get("/api/v1/export", params={"format": "md"})
    assert exported.status_code == 200
    text = exported.content.decode("utf-8")
    # 导出的是文本本身，前端不得用 v-html 解释它。
    assert "<script>alert(1)</script>" in text

    # 待审/导入路径同样按纯文本保存，不做 HTML 过滤（防线在渲染层）。
    imported = auth_client.post(
        "/api/v1/import/markdown",
        files={
            "file": (
                "xss.md",
                "## 题目：<script>alert(2)</script> 导入题？\n**答案**：<b>加粗</b>\n".encode(),
                "text/markdown",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    pending = auth_client.get(
        "/api/v1/pending", params={"page_size": 50}
    ).json()["data"]["items"]
    item = next(row for row in pending if "<script>alert(2)</script>" in (row["stem"] or ""))
    assert "<b>加粗</b>" in (item["answer"] or "")


def test_frontend_has_no_raw_html_rendering() -> None:
    offenders = []
    for path in FRONTEND_SRC.rglob("*.vue"):
        text = path.read_text(encoding="utf-8")
        if "v-html" in text or "innerHTML" in text:
            offenders.append(str(path.relative_to(FRONTEND_SRC)))
    assert not offenders, f"以下文件绕过了 XSS 防线：{offenders}"


def test_alembic_upgrade_from_empty_database(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic.db"
    env = os.environ.copy()
    env["BAJIU_DB_PATH"] = str(db_path)
    env["BAJIU_DATA_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version and version[0], "alembic_version 未写入"
    assert {"questions", "knowledge_points", "pending_items", "tag_rules"} <= tables

    # 迁移脚本应覆盖 ORM 的全部表（新增模型忘记写迁移时会在这里暴露）。
    from app.database import Base

    missing = set(Base.metadata.tables) - tables
    assert not missing, f"迁移缺少表：{sorted(missing)}"
