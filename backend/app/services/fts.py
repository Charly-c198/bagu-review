"""SQLite FTS5 全文索引（M2）。

- `question_fts`：题干 / 答案 / 笔记
- `knowledge_fts`：标题 / 内容 / 别名

中文没有空格，默认 unicode61 分词无法切词，因此优先使用 trigram 分词器
（按 3 字符窗口索引，天然支持中文子串匹配）。trigram 无法命中 <3 字的查询，
调用方在返回 None 时退回 LIKE。
"""

from __future__ import annotations

import logging
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import DATABASE_URL

logger = logging.getLogger("bajiu.fts")

TRIGRAM = True
_READY = False

_QUESTION_DDL = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS question_fts
       USING fts5(stem, answer, notes, tokenize='trigram')""",
    """CREATE TRIGGER IF NOT EXISTS question_fts_ai AFTER INSERT ON questions BEGIN
         INSERT INTO question_fts(rowid, stem, answer, notes)
         VALUES (new.id, new.stem, coalesce(new.answer, ''), coalesce(new.notes, ''));
       END""",
    """CREATE TRIGGER IF NOT EXISTS question_fts_au
       AFTER UPDATE OF stem, answer, notes ON questions BEGIN
         DELETE FROM question_fts WHERE rowid = old.id;
         INSERT INTO question_fts(rowid, stem, answer, notes)
         VALUES (new.id, new.stem, coalesce(new.answer, ''), coalesce(new.notes, ''));
       END""",
    """CREATE TRIGGER IF NOT EXISTS question_fts_ad AFTER DELETE ON questions BEGIN
         DELETE FROM question_fts WHERE rowid = old.id;
       END""",
]

_KNOWLEDGE_DDL = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
       USING fts5(title, content, aliases, tokenize='trigram')""",
    """CREATE TRIGGER IF NOT EXISTS knowledge_fts_ai AFTER INSERT ON knowledge_points BEGIN
         INSERT INTO knowledge_fts(rowid, title, content, aliases)
         VALUES (new.id, new.title, coalesce(new.content, ''), coalesce(new.aliases, ''));
       END""",
    """CREATE TRIGGER IF NOT EXISTS knowledge_fts_au
       AFTER UPDATE OF title, content, aliases ON knowledge_points BEGIN
         DELETE FROM knowledge_fts WHERE rowid = old.id;
         INSERT INTO knowledge_fts(rowid, title, content, aliases)
         VALUES (new.id, new.title, coalesce(new.content, ''), coalesce(new.aliases, ''));
       END""",
    """CREATE TRIGGER IF NOT EXISTS knowledge_fts_ad AFTER DELETE ON knowledge_points BEGIN
         DELETE FROM knowledge_fts WHERE rowid = old.id;
       END""",
]

_BACKFILL = [
    """INSERT INTO question_fts(rowid, stem, answer, notes)
       SELECT q.id, q.stem, coalesce(q.answer, ''), coalesce(q.notes, '')
       FROM questions q
       WHERE q.id NOT IN (SELECT rowid FROM question_fts)""",
    """INSERT INTO knowledge_fts(rowid, title, content, aliases)
       SELECT k.id, k.title, coalesce(k.content, ''), coalesce(k.aliases, '')
       FROM knowledge_points k
       WHERE k.id NOT IN (SELECT rowid FROM knowledge_fts)""",
]


def fts_supported() -> bool:
    return DATABASE_URL.startswith("sqlite")


def ensure_fts(engine, *, force: bool = False) -> None:
    """建表 / 触发器并补齐历史数据；失败只记录警告，不影响主流程。"""
    global _READY, TRIGRAM
    if (_READY and not force) or not fts_supported():
        return
    try:
        with engine.begin() as conn:
            try:
                for statement in _QUESTION_DDL + _KNOWLEDGE_DDL:
                    conn.exec_driver_sql(statement)
            except Exception:
                # 旧版 SQLite 不支持 trigram：退回 unicode61（英文仍可精确检索）。
                TRIGRAM = False
                logger.warning("FTS5 trigram 不可用，退回 unicode61 分词")
                for statement in _QUESTION_DDL + _KNOWLEDGE_DDL:
                    conn.exec_driver_sql(statement.replace(", tokenize='trigram'", ""))
            for statement in _BACKFILL:
                conn.exec_driver_sql(statement)
        _READY = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("FTS5 初始化失败，搜索退回 LIKE：%s", exc)


def rebuild_fts(db: Session) -> None:
    """清空并重建索引（备份恢复、批量导入后可调用）。"""
    if not fts_supported():
        return
    ensure_fts(db.get_bind())
    for table in ("question_fts", "knowledge_fts"):
        db.execute(text(f"DELETE FROM {table}"))
    for statement in _BACKFILL:
        db.execute(text(statement))
    db.commit()


def _match_ids(db: Session, table: str, query: str, limit: int) -> Sequence[int] | None:
    if not fts_supported():
        return None
    ensure_fts(db.get_bind())
    query = (query or "").strip()
    if not query:
        return None
    tokens = query.split()
    if not TRIGRAM:
        # unicode61 对中文按整段字符处理，中文查询会命中不了；交给 LIKE。
        if any(ord(ch) > 127 for ch in query):
            return None
        tokens = tokens[:5]
    # trigram 需要每个查询片段至少 3 个字符。
    if any(len(token) < 3 for token in tokens):
        return None
    phrase = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens[:5])
    try:
        rows = db.execute(
            text(
                f"SELECT rowid FROM {table} WHERE {table} MATCH :q "
                "ORDER BY rank LIMIT :limit"
            ),
            {"q": phrase, "limit": limit},
        ).all()
        return [int(row[0]) for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.debug("FTS 查询失败，退回 LIKE：%s", exc)
        return None


def search_question_ids(db: Session, query: str, limit: int = 500) -> list[int] | None:
    """返回命中的题目 id；None 表示应退回 LIKE。"""
    ids = _match_ids(db, "question_fts", query, limit)
    return None if ids is None else list(ids)


def search_knowledge_ids(db: Session, query: str, limit: int = 500) -> list[int] | None:
    ids = _match_ids(db, "knowledge_fts", query, limit)
    return None if ids is None else list(ids)
