"""导出路由。"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError
from ..models import User
from ..security import get_current_user
from ..services.export_service import export_json, export_markdown

router = APIRouter(tags=["export"])


@router.get("/export")
def export(
    format: str = Query(default="json"),
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if format == "json":
        payload = export_json(db, category_id)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        media_type = "application/json; charset=utf-8"
        filename = f"bajiu-export-{stamp}.json"
    elif format == "md":
        content = export_markdown(db, category_id)
        media_type = "text/markdown; charset=utf-8"
        filename = f"bajiu-export-{stamp}.md"
    else:
        raise ApiError(400, "VALIDATION_ERROR", "format 仅支持 json / md")
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
