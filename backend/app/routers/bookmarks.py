"""收藏夹路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError, ok
from ..models import Bookmark, Question, User
from ..security import get_current_user
from ..services.batch_loader import serialize_question_list

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


class BookmarkRequest(BaseModel):
    question_id: int


@router.get("")
def list_bookmarks(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(Bookmark, Question)
        .join(Question, Question.id == Bookmark.question_id)
        .where(Question.is_deleted == 0)
        .order_by(Bookmark.id.desc())
    ).all()
    questions = [question for _bookmark, question in rows]
    items = serialize_question_list(db, questions, quiz=True)
    by_id = {item["id"]: item for item in items}
    for bookmark, question in rows:
        by_id[question.id]["bookmarked_at"] = bookmark.created_at.isoformat()
    return ok({"items": items, "total": len(items)})


@router.post("")
def add_bookmark(
    payload: BookmarkRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    question = db.get(Question, payload.question_id)
    if question is None or question.is_deleted:
        raise ApiError(404, "NOT_FOUND", "题目不存在")
    if db.scalar(select(Bookmark).where(Bookmark.question_id == question.id)) is None:
        db.add(Bookmark(question_id=question.id))
        db.commit()
    return ok({"question_id": question.id}, "已收藏")


@router.delete("/{question_id}")
def remove_bookmark(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    bookmark = db.scalar(
        select(Bookmark).where(Bookmark.question_id == question_id)
    )
    if bookmark:
        db.delete(bookmark)
        db.commit()
    return ok(None, "已取消收藏")
