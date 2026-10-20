"""FTS5 全文索引（M2）

Revision ID: 9f1c2d3e4a5b
Revises: 5b31c536ec52
Create Date: 2026-10-20
"""

from __future__ import annotations

from alembic import op

revision = "9f1c2d3e4a5b"
down_revision = "5b31c536ec52"
branch_labels = None
depends_on = None


_STATEMENTS = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS question_fts
       USING fts5(stem, answer, notes, tokenize='trigram')""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
       USING fts5(title, content, aliases, tokenize='trigram')""",
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
    """INSERT INTO question_fts(rowid, stem, answer, notes)
       SELECT q.id, q.stem, coalesce(q.answer, ''), coalesce(q.notes, '')
       FROM questions q WHERE q.id NOT IN (SELECT rowid FROM question_fts)""",
    """INSERT INTO knowledge_fts(rowid, title, content, aliases)
       SELECT k.id, k.title, coalesce(k.content, ''), coalesce(k.aliases, '')
       FROM knowledge_points k WHERE k.id NOT IN (SELECT rowid FROM knowledge_fts)""",
]


def upgrade() -> None:
    for statement in _STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for trigger in (
        "question_fts_ai",
        "question_fts_au",
        "question_fts_ad",
        "knowledge_fts_ai",
        "knowledge_fts_au",
        "knowledge_fts_ad",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS question_fts")
    op.execute("DROP TABLE IF EXISTS knowledge_fts")
