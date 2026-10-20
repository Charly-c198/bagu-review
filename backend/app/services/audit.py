"""审计日志。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog


def audit(
    db: Session,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: Any = None,
    actor: str = "user",
) -> None:
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )
