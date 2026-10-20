"""Pydantic 请求模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Frequency = Literal["high", "mid", "low"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class QuestionCreate(BaseModel):
    stem: str = Field(min_length=1)
    answer: str | None = None
    key_points: list[str] = Field(default_factory=list)
    notes: str | None = None
    category_ids: list[int] = Field(default_factory=list)
    category_path: str | None = None
    tags: list[str] = Field(default_factory=list)
    tag_ids: list[int] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    status: Literal["active", "draft"] = "active"


class QuestionUpdate(BaseModel):
    stem: str | None = Field(default=None, min_length=1)
    answer: str | None = None
    key_points: list[str] | None = None
    notes: str | None = None
    category_ids: list[int] | None = None
    category_path: str | None = None
    tags: list[str] | None = None
    tag_ids: list[int] | None = None
    companies: list[str] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    status: Literal["draft", "active", "archived"] | None = None


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    kind: Literal["concept", "principle", "process", "comparison", "pitfall", "other"] = "concept"
    category_id: int | None = None
    category_path: str | None = None
    aliases: list[str] = Field(default_factory=list)
    status: Literal["active", "draft"] = "active"
    send_to_pending: bool = False


class KnowledgeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    content: str | None = Field(default=None, min_length=1)
    kind: Literal["concept", "principle", "process", "comparison", "pitfall", "other"] | None = None
    category_id: int | None = None
    category_path: str | None = None
    aliases: list[str] | None = None
    status: Literal["draft", "active", "archived"] | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    parent_id: int | None = None
    sort_order: int | None = None
    move: bool = False


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class LinkCreate(BaseModel):
    knowledge_id: int
    relation_type: Literal["related", "prerequisite", "derived_from"] = "related"


class PendingUpdate(BaseModel):
    stem: str | None = None
    answer: str | None = None
    knowledge_title: str | None = None
    knowledge_content: str | None = None
    suggested_meta: dict | None = None
    reviewer_note: str | None = None


class ApproveRequest(BaseModel):
    stem: str | None = None
    answer: str | None = None
    key_points: list[str] | None = None
    notes: str | None = None
    knowledge_title: str | None = None
    knowledge_content: str | None = None
    kind: Literal["concept", "principle", "process", "comparison", "pitfall", "other"] | None = None
    category_id: int | None = None
    category_path: str | None = None
    tags: list[str] | None = None
    tag_ids: list[int] | None = None
    companies: list[str] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    aliases: list[str] | None = None
    relation_type: Literal["related", "prerequisite", "derived_from"] = "related"
    knowledge_ids: list[int] = Field(default_factory=list)


class RejectRequest(BaseModel):
    reviewer_note: str | None = None


class MergeRequest(BaseModel):
    target_type: Literal["question", "knowledge", "pending"]
    target_id: int
    reviewer_note: str | None = None


class RatingRequest(BaseModel):
    question_id: int
    q: int = Field(ge=0, le=5)
    mode: Literal["practice", "review", "mistake", "interview"] = "practice"
    sprint: bool = False


class QuizRequest(BaseModel):
    category_id: int | None = None
    tag: str | None = None
    tag_id: int | None = None
    company: str | None = None
    company_id: int | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    mastery: str | None = None
    source_type: str | None = None
    # M2 多维筛选：维度间 AND、维度内 OR。
    category_ids: list[int] = Field(default_factory=list)
    tag_ids: list[int] = Field(default_factory=list)
    company_ids: list[int] = Field(default_factory=list)
    difficulties: list[int] = Field(default_factory=list)
    frequencies: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    masteries: list[str] = Field(default_factory=list)
    q: str | None = None
    limit: int = Field(default=20, ge=1, le=200)
    mode: Literal["practice", "sprint"] = "practice"
    only_mistakes: bool = False
    only_due: bool = False
    only_unfamiliar: bool = False
    exclude_mastered: bool = False


class SourceCreate(BaseModel):
    name: str = Field(min_length=1)
    source_kind: Literal["github", "nowcoder"] = "github"
    url: str = Field(min_length=1)
    enabled: bool = True
    user_agent: str = "InterviewReviewBot/1.0 (+personal use)"
    interval_sec: int = Field(default=10, ge=1, le=3600)
    timeout_sec: int = Field(default=15, ge=1, le=120)
    max_retries: int = Field(default=3, ge=1, le=10)
    max_files_per_run: int = Field(default=100, ge=1, le=1000)


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None
    user_agent: str | None = None
    interval_sec: int | None = Field(default=None, ge=1, le=3600)
    timeout_sec: int | None = Field(default=None, ge=1, le=120)
    max_retries: int | None = Field(default=None, ge=1, le=10)
    max_files_per_run: int | None = Field(default=None, ge=1, le=1000)


class TagRuleCreate(BaseModel):
    keyword: str = Field(min_length=1)
    match_type: Literal["contains", "regex"] = "contains"
    tag_ids: list[int] = Field(default_factory=list)
    category_id: int | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    weight: float = 1.0
    enabled: bool = True


class TagRuleUpdate(BaseModel):
    keyword: str | None = None
    match_type: Literal["contains", "regex"] | None = None
    tag_id: int | None = None
    category_id: int | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    frequency: Frequency | None = None
    weight: float | None = None
    enabled: bool | None = None
