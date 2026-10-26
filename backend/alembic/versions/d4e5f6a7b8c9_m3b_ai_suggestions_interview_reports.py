"""M3a Slice 2/3 与 M3b：AI 建议、仿真面试、周报告表

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["ai_prompt_versions.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "idx_ai_suggestions_target",
        "ai_suggestions",
        ["kind", "target_type", "target_id", "created_at"],
    )

    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_interview_sessions_status",
        "interview_sessions",
        ["status", "started_at"],
    )

    op.create_table(
        "interview_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("follow_up", sa.Text(), nullable=True),
        sa.Column("follow_up_answer", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("gaps_json", sa.Text(), nullable=True),
        sa.Column("scored_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("scored_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("session_id", "question_id", name="uq_interview_turn"),
    )
    op.create_index(
        "idx_interview_turns_session", "interview_turns", ["session_id"]
    )

    op.create_table(
        "interview_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("session_id", name="uq_interview_report_session"),
    )

    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("week_start", sa.String(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("week_start", name="uq_weekly_report_week"),
    )


def downgrade() -> None:
    op.drop_table("weekly_reports")
    op.drop_table("interview_reports")
    op.drop_index("idx_interview_turns_session", table_name="interview_turns")
    op.drop_table("interview_turns")
    op.drop_index("idx_interview_sessions_status", table_name="interview_sessions")
    op.drop_table("interview_sessions")
    op.drop_index("idx_ai_suggestions_target", table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
