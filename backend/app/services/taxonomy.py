"""题目与知识条目的分类/标签/公司关联写入。"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import (
    QuestionCategory,
    QuestionCompany,
    QuestionTag,
)
from .categories import (
    get_or_create_category_path,
    get_or_create_company,
    get_or_create_tag,
)


def set_question_taxonomy(
    db: Session,
    question_id: int,
    *,
    category_ids: list[int] | None = None,
    category_path: str | None = None,
    tags: list[str] | None = None,
    tag_ids: list[int] | None = None,
    companies: list[str] | None = None,
    replace: bool = False,
) -> None:
    if replace:
        db.execute(
            delete(QuestionCategory).where(QuestionCategory.question_id == question_id)
        )
        db.execute(delete(QuestionTag).where(QuestionTag.question_id == question_id))
        db.execute(
            delete(QuestionCompany).where(QuestionCompany.question_id == question_id)
        )

    final_categories = list(category_ids or [])
    if category_path:
        final_categories.append(get_or_create_category_path(db, category_path.split("/")).id)
    for category_id in dict.fromkeys(final_categories):
        db.merge(
            QuestionCategory(question_id=question_id, category_id=category_id)
        )

    final_tag_ids = list(tag_ids or [])
    for name in tags or []:
        final_tag_ids.append(get_or_create_tag(db, name).id)
    for tag_id in dict.fromkeys(final_tag_ids):
        db.merge(QuestionTag(question_id=question_id, tag_id=tag_id))

    for name in companies or []:
        company = get_or_create_company(db, name)
        db.merge(
            QuestionCompany(question_id=question_id, company_id=company.id)
        )
