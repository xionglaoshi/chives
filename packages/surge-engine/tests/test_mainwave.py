from __future__ import annotations

from datetime import date, timedelta

import pytest

from surge_engine.spec import main_wave_score, time_score
from surge_engine.state import (
    CONFIRM_FAILED,
    MA10_BREAK,
    MA10_REPAIR,
    MAIN_EXIT,
    NORMAL_GRADE,
    PRIORITY1,
    PRIORITY2,
    Round,
    SECOND_BOARD,
    SUPPORT_BREAK,
    START,
    BarView,
    DayContext,
)


def new_round(*, C_F: float = 10.0, L_F: float = 9.0, G: float = 9.4) -> Round:
    return Round.create(
        code="000001.SZ",
        round_id=1,
        F=date(2020, 1, 1),
        f_index=0,
        C_F=C_F,
        L_F=L_F,
        G=G,
        M=10.5,
        m=9.8,
        drawdown=(10.5 - 9.8) / 10.5,
    )


def ctx(round_obj: Round, k: int, close: float | None, *, limit: bool = False, ma10: float | None = None,
        ma5: float | None = None, ma20: float | None = None, vol_ratio: float | None = None) -> DayContext:
    day_index = round_obj.f_index + k
    bar = None if close is None else BarView(close=close, low=close, high=close, volume=1000)
    return DayContext(
        date=date(2020, 1, 1) + timedelta(days=day_index),
        day_index=day_index,
        bar=bar,
        limit_up=limit,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        vol_ratio=vol_ratio,
    )


def names(events) -> list[str]:
    return [event.event for event in events]


def started_round() -> Round:
    r = new_round()
    r.step(ctx(r, 1, 10.0))
    events = r.step(ctx(r, 2, 10.5))
    assert START in names(events)
    assert r.started and r.P_star == 10.5 and r.k_start == 2
    return r


def test_priority_one_on_first_or_second_day() -> None:
    r = started_round()
    events = r.step(ctx(r, 3, 11.0, limit=True))
    assert PRIORITY1 in names(events)
    assert r.priority == "p1" and r.priority_date == ctx(r, 3, 11.0).date

    r = started_round()
    r.step(ctx(r, 3, 10.6))
    assert r.confirm_pending
    assert r.first_status() == "确认中"
    events = r.step(ctx(r, 4, 11.5, limit=True))
    assert PRIORITY1 in names(events)
    assert r.priority_date == ctx(r, 4, 11.5).date


def test_priority_two_requires_both_days_above() -> None:
    r = started_round()
    r.step(ctx(r, 3, 10.6))
    events = r.step(ctx(r, 4, 10.7))
    assert PRIORITY2 in names(events)
    assert r.priority == "p2" and r.priority_date == ctx(r, 4, 10.7).date


def test_only_one_day_above_goes_to_three_day_look() -> None:
    r = started_round()
    r.step(ctx(r, 3, 10.6))
    assert r.step(ctx(r, 4, 10.4)) == []
    assert r.confirm_pending
    assert r.step(ctx(r, 5, 10.4)) == []
    events = r.step(ctx(r, 6, 10.6))
    assert NORMAL_GRADE in names(events)
    assert r.priority == "normal" and r.in_first_pool


def test_look_fails_and_removes_from_first_pool_but_keeps_main_pool() -> None:
    r = started_round()
    r.step(ctx(r, 3, 10.6))
    r.step(ctx(r, 4, 10.4))
    r.step(ctx(r, 5, 10.4))
    r.step(ctx(r, 6, 10.4))
    events = r.step(ctx(r, 7, 10.4))
    assert CONFIRM_FAILED in names(events)
    assert not r.in_first_pool and r.in_main_pool and not r.out
    assert r.first_out_reason == "confirm_failed"


def test_confirmation_window_suspension_counts_as_failure() -> None:
    r = started_round()
    r.step(ctx(r, 3, 10.6))
    r.step(ctx(r, 4, None))
    r.step(ctx(r, 5, None))
    r.step(ctx(r, 6, 10.4))
    events = r.step(ctx(r, 7, 10.4))
    assert CONFIRM_FAILED in names(events)


def test_first_pool_score_components_and_time_decay() -> None:
    r = new_round()
    r.step(ctx(r, 1, 10.0))
    scores = r.scores()
    assert (scores["support_score"], scores["ma_score"], scores["volume_score"]) == (100, 0, 0)
    assert scores["time_score"] == pytest.approx(100.0)
    assert scores["score"] == 75
    for k in range(2, 24):
        r.step(ctx(r, k, 10.0))
    assert r.scores()["time_score"] == pytest.approx(50.0)
    assert r.scores()["score"] == 53


def test_ma_floor_after_start_at_k23() -> None:
    r = new_round()
    r.step(ctx(r, 1, 10.0))
    for k in range(2, 23):
        r.step(ctx(r, k, 10.0))
    r.step(ctx(r, 23, 10.5, ma5=10.0, ma10=10.1, ma20=10.05))
    assert r.started and r.st_value == pytest.approx(time_score(23))
    for k in (24, 25):
        r.step(ctx(r, k, 10.5, ma5=10.0, ma10=10.1, ma20=10.05))
    assert r.sm_satisfied and r.floor_active
    scores = r.scores()
    assert scores["ma_score"] == 100
    assert scores["score"] == 68  # 30 + 15 + 22.5, half-up
    # Sticky to the end of the round even without new convergence days.
    for k in range(26, 40):
        r.step(ctx(r, k, 10.5, ma5=11.0, ma10=10.0, ma20=10.0))
    assert r.sm_satisfied and r.floor_active
    assert r.scores()["score"] == 68


def test_main_wave_score_samples() -> None:
    assert main_wave_score(11.0, 11.0, 10.0)[0] == 80
    assert main_wave_score(11.5, 11.5, 10.0)[0] == 100
    assert main_wave_score(12.5, 12.5, 10.0)[0] == 100
    assert main_wave_score(12.501, 12.501, 10.0)[0] == 90
    assert main_wave_score(13.0, 13.0, 10.0)[0] == 90
    assert main_wave_score(13.001, 13.001, 10.0)[0] == 80
    assert main_wave_score(17.5, 17.5, 10.0)[0] == 0
    assert main_wave_score(18.0, 18.0, 10.0)[0] == 0

    assert main_wave_score(10.0, 9.701, 10.0)[1] == 0
    assert main_wave_score(10.0, 9.7, 10.0)[1] == 10
    assert main_wave_score(10.0, 9.401, 10.0)[1] == 10
    assert main_wave_score(10.0, 9.4, 10.0)[1] == 20

    base, deduction, gain, drawdown, score = main_wave_score(13.0, 12.61, 10.0)
    assert (base, deduction, score) == (90, 10, 80)
    assert gain == pytest.approx(0.3)
    assert drawdown == pytest.approx(0.03)


def test_zero_score_stays_in_pool() -> None:
    r = new_round()
    r.step(ctx(r, 1, 11.0, limit=True))
    r.step(ctx(r, 2, 18.0))
    scores = r.main_scores(18.0)
    assert scores["base_score"] == 0 and scores["score"] == 0
    assert r.in_main_pool and not r.out


def test_ma10_pre_entry_break_not_counted() -> None:
    r = new_round()
    r.step(ctx(r, 1, 10.4, limit=True, ma10=10.5))
    assert r.ma10_count == 0
    events = r.step(ctx(r, 2, 10.4, ma10=10.5))
    assert MA10_BREAK in names(events)
    assert r.ma10_count == 1


def test_ma10_consecutive_breaks_count_once_and_repair() -> None:
    r = new_round()
    r.step(ctx(r, 1, 11.0, limit=True))
    r.step(ctx(r, 2, 10.4, ma10=10.5))
    assert r.ma10_count == 1 and r.ma10_obs_left == 3
    assert r.step(ctx(r, 3, 10.3, ma10=10.5)) == []
    assert r.ma10_count == 1 and r.ma10_obs_left == 2
    events = r.step(ctx(r, 4, 10.6, ma10=10.5))
    assert MA10_REPAIR in names(events)
    assert r.ma10_obs_left == 0 and r.in_main_pool


def test_ma10_equal_does_not_repair() -> None:
    r = new_round()
    r.step(ctx(r, 1, 11.0, limit=True))
    r.step(ctx(r, 2, 10.4, ma10=10.5))
    assert r.step(ctx(r, 3, 10.5, ma10=10.5)) == []
    assert r.ma10_obs_left == 2


def test_second_ma10_event_unrepaired_removes_on_third_day() -> None:
    r = new_round()
    r.step(ctx(r, 1, 11.0, limit=True))
    r.step(ctx(r, 2, 10.4, ma10=10.5))
    r.step(ctx(r, 3, 10.3, ma10=10.5))
    r.step(ctx(r, 4, 10.6, ma10=10.5))  # repair first event
    r.step(ctx(r, 5, 10.4, ma10=10.5))  # second event
    assert r.ma10_count == 2 and r.ma10_obs_left == 3
    r.step(ctx(r, 6, 10.4, ma10=10.5))
    r.step(ctx(r, 7, 10.4, ma10=10.5))
    events = r.step(ctx(r, 8, 10.4, ma10=10.5))
    assert MAIN_EXIT in names(events)
    assert r.out and r.main_out_reason == "ma10_unrepaired"
    assert not r.in_first_pool


def test_third_ma10_event_removes_immediately() -> None:
    r = new_round()
    r.step(ctx(r, 1, 11.0, limit=True))
    r.step(ctx(r, 2, 10.4, ma10=10.5))
    r.step(ctx(r, 3, 10.6, ma10=10.5))  # repair 1
    r.step(ctx(r, 4, 10.4, ma10=10.5))  # event 2
    r.step(ctx(r, 5, 10.6, ma10=10.5))  # repair 2
    events = r.step(ctx(r, 6, 10.4, ma10=10.5))  # event 3
    assert [name for name in names(events) if name in (MA10_BREAK, MAIN_EXIT)] == [MA10_BREAK, MAIN_EXIT]
    assert r.out and r.main_out_reason == "ma10_third"


def test_started_stock_support_break_stops_after_start() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    r.step(ctx(r, 2, 10.5))
    events = r.step(ctx(r, 3, 9.3))
    assert SUPPORT_BREAK not in names(events)
    assert r.s1.status in ("normal", "stopped")
