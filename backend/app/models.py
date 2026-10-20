"""数据模型：严格对应项目文档 V0.4 第 7 章 DDL。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .utils.timeutil import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("idx_auth_sessions_expires", "expires_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_categories_parent_name"),
        Index(
            "uq_categories_root_name",
            "name",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    format: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="processing", nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ok_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fail_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CrawlSource(Base):
    __tablename__ = "crawl_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    user_agent: Mapped[str] = mapped_column(
        Text, default="InterviewReviewBot/1.0 (+personal use)", nullable=False
    )
    interval_sec: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_files_per_run: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class CrawlTask(Base):
    __tablename__ = "crawl_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_sources.id", ondelete="CASCADE"), nullable=False
    )
    parent_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("crawl_tasks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CrawlTaskFile(Base):
    __tablename__ = "crawl_task_files"
    __table_args__ = (
        UniqueConstraint("task_id", "url", name="uq_crawl_task_file"),
        Index("idx_task_files_status", "task_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_tasks.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cached_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        Index("idx_questions_status", "status", "is_deleted"),
        Index("idx_questions_hash", "content_hash"),
        Index("idx_questions_source", "source_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    source_type: Mapped[str] = mapped_column(
        String, default="manual", nullable=False
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    simhash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class QuestionCategory(Base):
    __tablename__ = "question_categories"
    __table_args__ = (Index("idx_qc_category", "category_id"),)

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )


class QuestionTag(Base):
    __tablename__ = "question_tags"
    __table_args__ = (Index("idx_qt_tag", "tag_id"),)

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class QuestionCompany(Base):
    __tablename__ = "question_companies"
    __table_args__ = (Index("idx_qco_company", "company_id"),)

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )


class QuestionOrigin(Base):
    __tablename__ = "question_origins"
    __table_args__ = (
        UniqueConstraint(
            "question_id", "source_type", "origin_ref", name="uq_question_origin"
        ),
        Index("idx_origins_q", "question_id"),
        Index("idx_origins_batch", "import_batch_id"),
        Index("idx_origins_task", "crawl_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("crawl_sources.id", ondelete="SET NULL"), nullable=True
    )
    import_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    crawl_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("crawl_tasks.id", ondelete="SET NULL"), nullable=True
    )
    origin_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class MasteryRecord(Base):
    __tablename__ = "mastery_records"
    __table_args__ = (Index("idx_mastery_q", "question_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    q: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String, default="practice", nullable=False)
    session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ReviewSchedule(Base):
    __tablename__ = "review_schedule"
    __table_args__ = (Index("idx_review_due", "next_review_date"),)

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ef: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_review_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_q: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_rated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_schedule_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_reviewed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class MistakeBook(Base):
    __tablename__ = "mistake_book"
    __table_args__ = (Index("idx_mistake_q", "question_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (
        Index("idx_knowledge_status", "status", "is_deleted"),
        Index("idx_knowledge_hash", "content_hash"),
        Index("idx_knowledge_category", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String, default="concept", nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    aliases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    source_type: Mapped[str] = mapped_column(
        String, default="manual", nullable=False
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    simhash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class QuestionKnowledge(Base):
    __tablename__ = "question_knowledge"
    __table_args__ = (Index("idx_qk_knowledge", "knowledge_id"),)

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(
        String, default="related", primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class KnowledgeOrigin(Base):
    __tablename__ = "knowledge_origins"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_id", "source_type", "origin_ref", name="uq_knowledge_origin"
        ),
        Index("idx_korigins_k", "knowledge_id"),
        Index("idx_korigins_batch", "import_batch_id"),
        Index("idx_korigins_task", "crawl_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("crawl_sources.id", ondelete="SET NULL"), nullable=True
    )
    import_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    crawl_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("crawl_tasks.id", ondelete="SET NULL"), nullable=True
    )
    origin_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class PendingItem(Base):
    __tablename__ = "pending_items"
    __table_args__ = (
        Index("idx_pending_status", "status", "source_type"),
        Index("idx_pending_type", "item_type", "status", "source_type"),
        Index("idx_pending_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_type: Mapped[str] = mapped_column(
        String, default="question", nullable=False
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    import_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    crawl_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("crawl_tasks.id", ondelete="SET NULL"), nullable=True
    )
    origin_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    knowledge_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    knowledge_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_meta: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    simhash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    dup_of: Mapped[Optional[int]] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )
    dup_of_pending_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pending_items.id", ondelete="SET NULL"), nullable=True
    )
    dup_of_knowledge_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True
    )
    created_question_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )
    created_knowledge_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TagRule(Base):
    __tablename__ = "tag_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(
        String, default="contains", nullable=False
    )
    tag_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=True
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    difficulty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("idx_audit_target", "target_type", "target_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String, default="user", nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AiPromptVersion(Base):
    __tablename__ = "ai_prompt_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_ai_prompt_name_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    schema_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AiCall(Base):
    __tablename__ = "ai_calls"
    __table_args__ = (
        Index("idx_ai_calls_created", "created_at"),
        Index("idx_ai_calls_purpose", "purpose", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_prompt_versions.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String, default="", nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AiCache(Base):
    __tablename__ = "ai_cache"

    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    prompt_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_prompt_versions.id", ondelete="SET NULL"), nullable=True
    )
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class QualityCheck(Base):
    __tablename__ = "quality_checks"
    __table_args__ = (
        Index("idx_quality_target", "target_type", "target_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    issues_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overall_risk: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String, default="", nullable=False)
    prompt_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_prompt_versions.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
