"""时区与日期工具：数据库存 UTC，业务日期按 Asia/Shanghai。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:  # Windows 缺少 tzdata 时兜底（中国无夏令时）
    TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def utcnow() -> datetime:
    """返回不带 tzinfo 的 UTC 时间，便于 SQLite 存储。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    return datetime.now(TZ)


def local_today() -> date:
    return local_now().date()


def today_str() -> str:
    return local_today().isoformat()


def local_date_str(value: datetime | date) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(TZ).date().isoformat()
    return value.isoformat()


def parse_local_date(value: str) -> date:
    return date.fromisoformat(value)


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """返回本地某一天对应的 UTC 左闭右开区间（naive UTC）。"""
    start_local = datetime.combine(day, time.min, tzinfo=TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def add_days(base: date, days: int) -> date:
    return base + timedelta(days=days)
