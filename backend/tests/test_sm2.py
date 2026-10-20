from __future__ import annotations

from datetime import date, datetime, timezone

from app.utils.sm2 import Sm2State, apply_sm2, should_advance
from app.utils.timeutil import local_date_str


def advance(state: Sm2State) -> date:
    assert state.next_review_date
    return date.fromisoformat(state.next_review_date)


def test_case1_new_q5() -> None:
    today = date(2026, 10, 19)
    state, applied = apply_sm2(Sm2State(), 5, today)
    assert applied
    assert state.ef == 2.6
    assert state.reps == 1
    assert state.interval_days == 1
    assert state.next_review_date == "2026-10-20"
    assert state.first_reviewed_at == "2026-10-19"


def test_case2_second_q5() -> None:
    today = date(2026, 10, 19)
    state, _ = apply_sm2(Sm2State(), 5, today)
    state, applied = apply_sm2(state, 5, advance(state))
    assert applied
    assert state.ef == 2.7
    assert state.reps == 2
    assert state.interval_days == 6


def test_case3_third_q5_is_17_not_15() -> None:
    today = date(2026, 10, 19)
    state, _ = apply_sm2(Sm2State(), 5, today)
    state, _ = apply_sm2(state, 5, advance(state))
    state, applied = apply_sm2(state, 5, advance(state))
    assert applied
    assert state.ef == 2.8
    assert state.reps == 3
    assert state.interval_days == 17


def test_case4_q4_path_interval_15() -> None:
    today = date(2026, 10, 19)
    state, _ = apply_sm2(Sm2State(), 4, today)
    state, _ = apply_sm2(state, 4, advance(state))
    state, _ = apply_sm2(state, 4, advance(state))
    assert state.ef == 2.5
    assert state.interval_days == 15


def test_case5_lapse_resets() -> None:
    today = date(2026, 10, 19)
    state, _ = apply_sm2(Sm2State(), 5, today)
    state, _ = apply_sm2(state, 5, advance(state))
    ef_before = state.ef
    state, applied = apply_sm2(state, 2, advance(state))
    assert applied
    assert state.lapses == 1
    assert state.reps == 0
    assert state.interval_days == 1
    assert state.ef == ef_before
    assert state.next_review_date == "2026-10-27"


def test_case6_ef_floor_13() -> None:
    today = date(2026, 10, 19)
    state = Sm2State()
    for _ in range(15):
        state, _ = apply_sm2(state, 3, today)
        today = advance(state)
        if state.next_review_date is None:
            break
    assert state.ef == 1.3
    assert state.ef >= 1.3


def test_case7_interval_cap_90() -> None:
    today = date(2026, 10, 19)
    state = Sm2State(
        reps=5,
        ef=2.5,
        interval_days=80,
        next_review_date=today.isoformat(),
        first_reviewed_at="2026-01-01",
        last_schedule_date="2026-09-01",
    )
    state, applied = apply_sm2(state, 5, today, interval_cap_days=90)
    assert applied
    assert state.interval_days == 90


def test_case8_same_day_no_advance() -> None:
    today = date(2026, 10, 19)
    state, _ = apply_sm2(Sm2State(), 5, today)
    snapshot = (state.reps, state.ef, state.interval_days, state.next_review_date)
    state2, applied = apply_sm2(state, 5, today)
    assert not applied
    assert state2 == state
    assert (state2.reps, state2.ef, state2.interval_days, state2.next_review_date) == snapshot


def test_case9_cross_day_boundary() -> None:
    # 本地 23:59 与次日 00:01 应属于不同本地日期。
    late = datetime(2026, 10, 19, 15, 59, tzinfo=timezone.utc)  # 上海 23:59
    early = datetime(2026, 10, 19, 16, 1, tzinfo=timezone.utc)   # 上海次日 00:01
    assert local_date_str(late) == "2026-10-19"
    assert local_date_str(early) == "2026-10-20"


def test_case10_due_queue_excludes_same_day() -> None:
    today = date(2026, 10, 19)
    state = Sm2State(
        reps=1,
        ef=2.5,
        interval_days=1,
        next_review_date="2026-10-19",
        first_reviewed_at="2026-10-18",
        last_schedule_date="2026-10-19",
    )
    assert should_advance(state, 4, today) is False


def test_early_advances_setting() -> None:
    today = date(2026, 10, 19)
    state = Sm2State(
        reps=2,
        ef=2.5,
        interval_days=6,
        next_review_date="2026-10-25",
        first_reviewed_at="2026-10-01",
        last_schedule_date="2026-10-01",
    )
    _, applied = apply_sm2(state, 4, today)
    assert applied is False
    _, applied_early = apply_sm2(state, 4, today, early_advances=True)
    assert applied_early is True
