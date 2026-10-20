"""M3a AI 状态与用量。Key 永不回显。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ok
from ..models import AiCall, AiPromptVersion, User
from ..security import get_current_user
from ..services.ai.gateway import AIConfig
from ..utils.timeutil import utcnow

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
def ai_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    config = AIConfig.from_env()
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls, input_tokens, output_tokens, cost = db.execute(
        select(
            func.count(AiCall.id),
            func.coalesce(func.sum(AiCall.input_tokens), 0),
            func.coalesce(func.sum(AiCall.output_tokens), 0),
            func.coalesce(func.sum(AiCall.cost), 0.0),
        ).where(
            AiCall.created_at >= month_start,
            AiCall.status.in_(("success", "failed")),
        )
    ).one()
    cache_hits = int(
        db.scalar(
            select(func.count(AiCall.id)).where(
                AiCall.created_at >= month_start,
                AiCall.status == "cache_hit",
            )
        )
        or 0
    )
    prompts = db.scalars(
        select(AiPromptVersion).order_by(AiPromptVersion.name, AiPromptVersion.version)
    ).all()
    return ok(
        {
            "configured": config.configured,
            "model": config.model or None,
            "base_url": config.base_url or None,
            "timeout_sec": config.timeout_sec,
            "max_input_chars": config.max_input_chars,
            "max_output_tokens": config.max_output_tokens,
            "monthly_token_limit": config.monthly_token_limit,
            "cache_ttl_days": config.cache_ttl_days,
            "json_mode": config.json_mode,
            "usage": {
                "calls": int(calls or 0),
                "cache_hits": cache_hits,
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "tokens": int(input_tokens or 0) + int(output_tokens or 0),
                "cost": round(float(cost or 0), 6),
            },
            "prompt_versions": [
                {"name": row.name, "version": row.version} for row in prompts
            ],
            "env": [
                "BAJIU_AI_BASE_URL",
                "BAJIU_AI_API_KEY",
                "BAJIU_AI_MODEL",
            ],
        }
    )
