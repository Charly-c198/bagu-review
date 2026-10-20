"""应用设置的默认值、读取、校验与更新。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import AppSetting

DEFAULTS: dict[str, Any] = {
    "sm2.ef_initial": 2.5,
    "sm2.ef_min": 1.3,
    "sm2.interval_cap_days": 90,
    "sm2.daily_new_limit": 20,
    "sm2.daily_review_limit": 50,
    "dedupe.simhash_threshold": 3,
    "manual.new_to_pending": False,
    "import.direct_to_active": False,
    "import.max_rows": 2000,
    "import.max_bytes": 5 * 1024 * 1024,
    "review.early_advances": False,
    "crawl.max_files_per_run": 100,
    "auth.token_ttl_minutes": 10080,
    "mistake.auto_remove_streak": 2,
}

# key -> (type, min, max)
_NUMERIC_RANGES: dict[str, tuple[type, float, float]] = {
    "sm2.ef_initial": (float, 1.3, 5.0),
    "sm2.ef_min": (float, 1.3, 3.0),
    "sm2.interval_cap_days": (int, 1, 365),
    "sm2.daily_new_limit": (int, 0, 500),
    "sm2.daily_review_limit": (int, 0, 2000),
    "dedupe.simhash_threshold": (int, 0, 32),
    "import.max_rows": (int, 1, 100000),
    "import.max_bytes": (int, 1024, 100 * 1024 * 1024),
    "crawl.max_files_per_run": (int, 1, 1000),
    "auth.token_ttl_minutes": (int, 5, 60 * 24 * 365),
    "mistake.auto_remove_streak": (int, 0, 10),
}

_BOOL_KEYS = {
    "manual.new_to_pending",
    "import.direct_to_active",
    "review.early_advances",
}


def _decode(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def get_settings(db: Session) -> dict[str, Any]:
    result = dict(DEFAULTS)
    for row in db.scalars(select(AppSetting)).all():
        result[row.key] = _decode(row.value_json)
    return result


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    return _decode(row.value_json)


def _validate(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise ApiError(400, "VALIDATION_ERROR", f"未知设置项：{key}")
    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ApiError(400, "VALIDATION_ERROR", f"{key} 必须是布尔值")
        return value
    if key in _NUMERIC_RANGES:
        cast, low, high = _NUMERIC_RANGES[key]
        try:
            cast_value = cast(value)
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "VALIDATION_ERROR", f"{key} 类型不正确") from exc
        if cast is int and float(value) != int(float(value)):
            raise ApiError(400, "VALIDATION_ERROR", f"{key} 必须是整数")
        if not low <= cast_value <= high:
            raise ApiError(
                400, "VALIDATION_ERROR", f"{key} 必须在 {low} 到 {high} 之间"
            )
        return cast_value
    raise ApiError(400, "VALIDATION_ERROR", f"{key} 不支持")


def update_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict) or not patch:
        raise ApiError(400, "VALIDATION_ERROR", "设置内容不能为空")
    for key, value in patch.items():
        clean = _validate(key, value)
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value_json=json.dumps(clean, ensure_ascii=False)))
        else:
            row.value_json = json.dumps(clean, ensure_ascii=False)
    db.commit()
    return get_settings(db)
