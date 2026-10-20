"""错题本路由。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ok
from ..models import User
from ..security import get_current_user
from ..services.export_service import mistake_markdown
from ..services.review import mistake_questions, remove_mistake
from ..utils.timeutil import local_date_str, local_today

router = APIRouter(prefix="/mistakes", tags=["mistakes"])


@router.get("")
def list_mistakes(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    items = mistake_questions(db, category_id)
    return ok({"items": items, "total": len(items)})


@router.get("/export")
def export_mistakes(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    items = mistake_questions(db, category_id)
    for item in items:
        item["added_at"] = local_date_str(datetime.fromisoformat(item["added_at"]))
    content = mistake_markdown(db, items)
    filename = f"bajiu-mistakes-{local_today().isoformat()}.md"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{question_id}/remove")
def remove(
    question_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    removed = remove_mistake(db, question_id)
    return ok({"removed": removed}, "已移出错题本" if removed else "该题不在错题本中")
