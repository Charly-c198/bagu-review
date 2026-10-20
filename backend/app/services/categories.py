"""分类树、标签、公司的查询与按路径获取/创建。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import Category, Company, Tag


def category_map(db: Session) -> dict[int, Category]:
    return {c.id: c for c in db.scalars(select(Category)).all()}


def category_path(category_id: int | None, mapping: dict[int, Category]) -> str:
    if not category_id:
        return ""
    parts: list[str] = []
    seen: set[int] = set()
    current = mapping.get(category_id)
    while current and current.id not in seen:
        seen.add(current.id)
        parts.append(current.name)
        current = mapping.get(current.parent_id) if current.parent_id else None
    return "/".join(reversed(parts))


def category_paths_from_ids(
    category_ids: list[int], mapping: dict[int, Category]
) -> list[dict]:
    result = []
    for cid in sorted(set(category_ids)):
        cat = mapping.get(cid)
        if cat:
            result.append(
                {
                    "id": cat.id,
                    "name": cat.name,
                    "level": cat.level,
                    "path": category_path(cat.id, mapping),
                }
            )
    return result


def category_paths_for(
    db: Session, question_id: int, mapping: dict[int, Category] | None = None
) -> list[dict]:
    from ..models import QuestionCategory

    mapping = mapping or category_map(db)
    rows = db.execute(
        select(QuestionCategory.category_id).where(
            QuestionCategory.question_id == question_id
        )
    ).scalars().all()
    return category_paths_from_ids(list(rows), mapping)


def descendant_ids(db: Session, category_id: int) -> list[int]:
    mapping = category_map(db)
    if category_id not in mapping:
        return []
    children: dict[int | None, list[int]] = {}
    for cat in mapping.values():
        children.setdefault(cat.parent_id, []).append(cat.id)
    result: list[int] = []
    stack = [category_id]
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(children.get(current, []))
    return result


def build_tree(db: Session) -> list[dict]:
    mapping = category_map(db)
    question_counts = _count_map(
        db, "question_categories", "category_id"
    )
    knowledge_counts = _count_map(db, "knowledge_points", "category_id")
    children: dict[int | None, list[Category]] = {}
    for cat in mapping.values():
        children.setdefault(cat.parent_id, []).append(cat)

    def node(cat: Category) -> dict:
        kids = sorted(children.get(cat.id, []), key=lambda c: (c.sort_order, c.name))
        return {
            "id": cat.id,
            "parent_id": cat.parent_id,
            "name": cat.name,
            "level": cat.level,
            "sort_order": cat.sort_order,
            "path": category_path(cat.id, mapping),
            "question_count": question_counts.get(cat.id, 0),
            "knowledge_count": knowledge_counts.get(cat.id, 0),
            "children": [node(k) for k in kids],
        }

    roots = sorted(children.get(None, []), key=lambda c: (c.sort_order, c.name))
    return [node(r) for r in roots]


def _count_map(db: Session, table: str, column: str) -> dict[int, int]:
    from sqlalchemy import text

    rows = db.execute(
        text(f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}")
    ).all()
    return {int(row[0]): int(row[1]) for row in rows if row[0] is not None}


def find_category(db: Session, name: str, parent_id: int | None) -> Category | None:
    stmt = select(Category).where(func.lower(Category.name) == name.strip().lower())
    if parent_id is None:
        stmt = stmt.where(Category.parent_id.is_(None))
    else:
        stmt = stmt.where(Category.parent_id == parent_id)
    return db.scalar(stmt)


def get_or_create_category_path(db: Session, parts: list[str]) -> Category:
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        raise ApiError(400, "VALIDATION_ERROR", "分类路径不能为空")
    if len(parts) > 3:
        parts = parts[:3]
    parent_id: int | None = None
    current: Category | None = None
    for level, name in enumerate(parts, start=1):
        current = find_category(db, name, parent_id)
        if current is None:
            current = Category(
                parent_id=parent_id, name=name.strip(), level=level
            )
            db.add(current)
            db.flush()
        parent_id = current.id
    assert current is not None
    return current


def get_or_create_tag(db: Session, name: str) -> Tag:
    name = name.strip()
    if not name:
        raise ApiError(400, "VALIDATION_ERROR", "标签不能为空")
    tag = db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower()))
    if tag is None:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    return tag


def get_or_create_company(db: Session, name: str) -> Company:
    name = name.strip()
    if not name:
        raise ApiError(400, "VALIDATION_ERROR", "公司不能为空")
    company = db.scalar(
        select(Company).where(func.lower(Company.name) == name.lower())
    )
    if company is None:
        company = Company(name=name)
        db.add(company)
        db.flush()
    return company
