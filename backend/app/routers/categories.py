"""分类树路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import Category, KnowledgePoint, QuestionCategory, User
from ..schemas import CategoryCreate, CategoryUpdate
from ..security import get_current_user
from ..services.audit import audit
from ..services.categories import build_tree, descendant_ids, find_category

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/tree")
def tree(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return ok(build_tree(db))


@router.post("")
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    parent = db.get(Category, payload.parent_id) if payload.parent_id else None
    if payload.parent_id and parent is None:
        raise ApiError(404, "NOT_FOUND", "父分类不存在")
    level = (parent.level + 1) if parent else 1
    if level > 3:
        raise ApiError(400, "VALIDATION_ERROR", "分类树最多 3 级")
    if find_category(db, payload.name, payload.parent_id):
        raise ApiError(409, "CONFLICT", "同级下已存在同名分类")
    category = Category(
        parent_id=payload.parent_id,
        name=payload.name.strip(),
        level=level,
        sort_order=payload.sort_order,
    )
    db.add(category)
    audit(db, "category_create", "category", None, {"name": payload.name})
    db.commit()
    db.refresh(category)
    return ok({"id": category.id, "name": category.name, "level": category.level})


@router.patch("/{category_id}")
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    category = db.get(Category, category_id)
    if category is None:
        raise ApiError(404, "NOT_FOUND", "分类不存在")
    data = payload.model_dump(exclude_unset=True)

    new_parent_id = category.parent_id
    if payload.move:
        new_parent_id = payload.parent_id
        if new_parent_id is not None:
            parent = db.get(Category, new_parent_id)
            if parent is None:
                raise ApiError(404, "NOT_FOUND", "父分类不存在")
            if parent.id == category.id or parent.id in descendant_ids(db, category.id):
                raise ApiError(400, "VALIDATION_ERROR", "不能移动到自身或子节点下")
            new_level = parent.level + 1
        else:
            new_level = 1
        if new_level > 3:
            raise ApiError(400, "VALIDATION_ERROR", "分类树最多 3 级")
        delta = new_level - category.level
        if delta:
            # 同步调整子节点层级，保持树结构一致。
            for cid in descendant_ids(db, category.id):
                child = db.get(Category, cid)
                if child and child.id != category.id:
                    child.level = child.level + delta
                    if child.level > 3:
                        raise ApiError(400, "VALIDATION_ERROR", "移动后子分类超过 3 级")
            category.level = new_level
        category.parent_id = new_parent_id

    if payload.name is not None:
        if find_category(db, payload.name, category.parent_id) and find_category(
            db, payload.name, category.parent_id
        ).id != category.id:
            raise ApiError(409, "CONFLICT", "同级下已存在同名分类")
        category.name = payload.name.strip()
    if payload.sort_order is not None:
        category.sort_order = payload.sort_order
    audit(db, "category_update", "category", category.id, data)
    db.commit()
    return ok({"id": category.id, "name": category.name, "level": category.level})


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    category = db.get(Category, category_id)
    if category is None:
        raise ApiError(404, "NOT_FOUND", "分类不存在")
    if db.scalar(select(func.count(Category.id)).where(Category.parent_id == category.id)):
        raise ApiError(409, "CONFLICT", "该分类下有子分类，请先删除或移动")
    if db.scalar(
        select(func.count(QuestionCategory.question_id)).where(
            QuestionCategory.category_id == category.id
        )
    ):
        raise ApiError(409, "CONFLICT", "该分类已被题目引用，暂不能删除")
    if db.scalar(
        select(func.count(KnowledgePoint.id)).where(
            KnowledgePoint.category_id == category.id,
            KnowledgePoint.is_deleted == 0,
        )
    ):
        raise ApiError(409, "CONFLICT", "该分类已被知识条目引用，暂不能删除")
    audit(db, "category_delete", "category", category.id, {"name": category.name})
    db.delete(category)
    db.commit()
    return ok(None, "已删除")
