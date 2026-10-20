"""组合筛选（M2 多维筛选增强）。

单值参数保持 M1 行为；新增多值参数，维度之间 AND、维度内部 OR。
列表参数接受逗号分隔字符串（查询参数）或列表（JSON 请求体）。
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import (
    Question,
    QuestionCategory,
    QuestionCompany,
    QuestionTag,
    ReviewSchedule,
)
from .categories import descendant_ids


def parse_int_list(value: str | Iterable[int] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    result: list[int] = []
    for part in parts:
        text = str(part).strip()
        if not text:
            continue
        try:
            result.append(int(text))
        except ValueError:
            continue
    return list(dict.fromkeys(result))


def parse_str_list(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    return list(dict.fromkeys(str(part).strip() for part in parts if str(part).strip()))


def _category_ids(db: Session, selected: list[int]) -> list[int]:
    ids: list[int] = []
    for category_id in selected:
        ids.extend(descendant_ids(db, category_id))
    return list(dict.fromkeys(ids))


def _mastery_ids(db: Session, values: list[str]) -> list[int] | None:
    clauses = []
    lowered = {value.lower() for value in values}
    if lowered & {"unlearned", "new", "待学", "未学"}:
        clauses.append(
            Question.id.not_in(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.first_reviewed_at.is_not(None)
                )
            )
        )
    if lowered & {"unfamiliar", "不熟"}:
        clauses.append(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.last_q.is_not(None), ReviewSchedule.last_q < 3
                )
            )
        )
    if lowered & {"familiar", "熟悉"}:
        clauses.append(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.last_q >= 3, ReviewSchedule.last_q < 5
                )
            )
        )
    if lowered & {"mastered", "精通"}:
        clauses.append(
            Question.id.in_(
                select(ReviewSchedule.question_id).where(
                    ReviewSchedule.last_q == 5
                )
            )
        )
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]  # type: ignore[return-value]
    return or_(*clauses)  # type: ignore[return-value]


def apply_multi_filters(
    stmt,
    db: Session,
    *,
    category_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
    company_ids: list[int] | None = None,
    difficulties: list[int] | None = None,
    frequencies: list[str] | None = None,
    sources: list[str] | None = None,
    masteries: list[str] | None = None,
):
    if category_ids:
        ids = _category_ids(db, category_ids)
        if not ids:
            return stmt.where(Question.id == -1)
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCategory.question_id).where(
                    QuestionCategory.category_id.in_(ids)
                )
            )
        )
    if tag_ids:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionTag.question_id).where(
                    QuestionTag.tag_id.in_(tag_ids)
                )
            )
        )
    if company_ids:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionCompany.question_id).where(
                    QuestionCompany.company_id.in_(company_ids)
                )
            )
        )
    if difficulties:
        stmt = stmt.where(Question.difficulty.in_(difficulties))
    if frequencies:
        stmt = stmt.where(Question.frequency.in_(frequencies))
    if sources:
        stmt = stmt.where(Question.source_type.in_(sources))
    if masteries:
        mastery_clause = _mastery_ids(db, masteries)
        if mastery_clause is not None:
            stmt = stmt.where(mastery_clause)
    return stmt
