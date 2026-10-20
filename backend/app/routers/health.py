"""健康检查（无需认证）。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..errors import ok
from ..utils.timeutil import utcnow

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz():
    return ok({"status": "ok", "version": __version__, "time": utcnow().isoformat() + "Z"})
