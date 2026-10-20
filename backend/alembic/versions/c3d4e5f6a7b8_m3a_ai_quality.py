"""M3a AI 网关与质量审查表

Revision ID: c3d4e5f6a7b8
Revises: 9f1c2d3e4a5b
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "9f1c2d3e4a5b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_prompt_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_ai_prompt_name_version"),
    )
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("prompt_version_id", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["ai_prompt_versions.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("idx_ai_calls_created", "ai_calls", ["created_at"])
    op.create_index("idx_ai_calls_purpose", "ai_calls", ["purpose", "created_at"])
    op.create_table(
        "ai_cache",
        sa.Column("cache_key", sa.String(), primary_key=True),
        sa.Column("prompt_version_id", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["ai_prompt_versions.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_table(
        "quality_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("issues_json", sa.Text(), nullable=True),
        sa.Column("overall_risk", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["ai_prompt_versions.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "idx_quality_target",
        "quality_checks",
        ["target_type", "target_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_quality_target", table_name="quality_checks")
    op.drop_table("quality_checks")
    op.drop_table("ai_cache")
    op.drop_index("idx_ai_calls_purpose", table_name="ai_calls")
    op.drop_index("idx_ai_calls_created", table_name="ai_calls")
    op.drop_table("ai_calls")
    op.drop_table("ai_prompt_versions")
