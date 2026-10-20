"""SM-2 间隔重复算法（按项目文档 V0.4 第 10 章实现）。

纯函数实现，便于单元测试与跨日固定时钟测试。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta


@dataclass
class Sm2State:
    reps: int = 0
    ef: float = 2.5
    interval_days: int = 0
    lapses: int = 0
    next_review_date: str | None = None   # YYYY-MM-DD（本地日期）
    first_reviewed_at: str | None = None  # YYYY-MM-DD（本地日期）
    last_schedule_date: str | None = None  # YYYY-MM-DD（同日防重）


def round_half_up(value: float) -> int:
    """四舍五入，避免 Python 银行家舍入。"""
    return int(value + 0.5)


def should_advance(
    state: Sm2State,
    q: int,
    today: date,
    early_advances: bool = False,
) -> bool:
    today_s = today.isoformat()
    if state.last_schedule_date == today_s:
        return False
    if state.first_reviewed_at is None:
        return True
    if state.next_review_date is None:
        return True
    if state.next_review_date <= today_s:
        return True
    if q < 3:  # 未到期题评“不熟”仍允许重置
        return True
    if early_advances:
        return True
    return False


def apply_sm2(
    state: Sm2State,
    q: int,
    today: date,
    *,
    early_advances: bool = False,
    interval_cap_days: int = 90,
    ef_min: float = 1.3,
) -> tuple[Sm2State, bool]:
    """按评分推进或跳过排程。

    返回 (新状态, 是否改变排程)。未改变排程时，调用方仍应更新 last_q /
    last_rated_at 并写入掌握记录。
    """
    if not 0 <= q <= 5:
        raise ValueError("q 必须在 0..5 之间")

    if not should_advance(state, q, today, early_advances):
        return state, False

    today_s = today.isoformat()
    new = replace(state)

    if q < 3:
        # 记忆失败：不更新 EF，重置 reps 与间隔。
        new.lapses += 1
        new.reps = 0
        new.interval_days = 1
    else:
        # 文档要求先更新 EF，再用新 EF 计算间隔。
        new.ef = new.ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        new.ef = max(round(new.ef, 10), ef_min)
        new.reps += 1
        if new.reps == 1:
            new.interval_days = 1
        elif new.reps == 2:
            new.interval_days = 6
        else:
            new.interval_days = round_half_up(new.interval_days * new.ef)
        new.interval_days = min(new.interval_days, interval_cap_days)

    new.next_review_date = (today + timedelta(days=new.interval_days)).isoformat()
    new.last_schedule_date = today_s
    if new.first_reviewed_at is None:
        new.first_reviewed_at = today_s
    return new, True
