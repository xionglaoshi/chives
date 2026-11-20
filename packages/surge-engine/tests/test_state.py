from __future__ import annotations

from datetime import date, timedelta

from surge_engine.state import (
    ENTER_FIRST_POOL,
    ENTER_MAIN_POOL,
    EXPIRED,
    Round,
    SECOND_BOARD,
    START,
    SUPPORT_BREAK,
    SUPPORT_BROKEN,
    SUPPORT_RECOVER,
    BarView,
    DayContext,
)


def new_round(
    *,
    code: str = "000001.SZ",
    round_id: int = 1,
    f_index: int = 0,
    C_F: float = 10.0,
    L_F: float = 9.0,
    G: float = 9.4,
) -> Round:
    return Round.create(
        code=code,
        round_id=round_id,
        F=date(2020, 1, 1),
        f_index=f_index,
        C_F=C_F,
        L_F=L_F,
        G=G,
        M=10.5,
        m=9.8,
        drawdown=(10.5 - 9.8) / 10.5,
    )


def ctx(round_obj: Round, k: int, close: float | None, *, limit: bool = False, ma10: float | None = None,
        ma5: float | None = None, ma20: float | None = None, volume: int = 1000) -> DayContext:
    day_index = round_obj.f_index + k
    bar = None if close is None else BarView(close=close, low=close, high=close, volume=volume)
    return DayContext(
        date=date(2020, 1, 1) + timedelta(days=day_index),
        day_index=day_index,
        bar=bar,
        limit_up=limit,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
    )


def names(events) -> list[str]:
    return [event.event for event in events]


def test_branch_second_board_goes_straight_to_main_pool() -> None:
    r = new_round()
    events = r.step(ctx(r, 1, 11.0, limit=True))
    assert SECOND_BOARD in names(events)
    assert ENTER_MAIN_POOL in names(events)
    assert ENTER_FIRST_POOL not in names(events)
    assert not r.in_first_pool and r.in_main_pool
    assert r.entry_date == ctx(r, 1, 11.0).date
    assert r.basis == 10.0
    assert r.hmax == 11.0
    assert r.k == 1


def test_branch_suspended_next_day_enters_first_pool() -> None:
    r = new_round()
    events = r.step(ctx(r, 1, None))
    assert names(events) == [ENTER_FIRST_POOL]
    assert r.in_first_pool and not r.in_main_pool
    assert r.k == 1


def test_expiry_at_k45_even_with_suspensions() -> None:
    r = new_round()
    r.step(ctx(r, 1, 10.0))
    for k in range(2, 45):
        events = r.step(ctx(r, k, None))
        assert EXPIRED not in names(events)
    events = r.step(ctx(r, 45, None))
    assert EXPIRED in names(events)
    assert r.k == 45
    assert r.out and not r.in_first_pool


def test_start_uses_first_board_close_in_breakout_line() -> None:
    r = new_round()
    r.step(ctx(r, 1, 10.0))
    assert r.step(ctx(r, 2, 10.0)) == []  # equal is not "above"
    assert not r.started
    events = r.step(ctx(r, 2, 10.01))
    assert START in names(events)
    assert r.started and r.P_star == 10.01
    assert r.in_main_pool and r.basis == 10.01


def test_start_freezes_mark_price_and_stops_support_and_expiry() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    r.step(ctx(r, 2, 10.5))
    assert r.started and r.P_star == 10.5 and r.k_start == 2
    assert r.st_value == 100 - (2 - 1) * 100 / 44
    # Below both supports after the start: no support events, P* unchanged.
    events = r.step(ctx(r, 3, 9.0))
    assert not {SUPPORT_BREAK, SUPPORT_BROKEN} & set(names(events))
    assert r.P_star == 10.5
    for k in range(4, 50):
        events = r.step(ctx(r, k, 9.0))
    assert EXPIRED not in names(events)
    assert r.in_main_pool


def test_support_first_break_and_recovery_on_first_observation_day() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    events = r.step(ctx(r, 2, 9.3))
    assert names(events) == [SUPPORT_BREAK]
    assert r.s1.status == "observing" and r.s1.obs_left == 3
    events = r.step(ctx(r, 3, 9.5))
    assert names(events) == [SUPPORT_RECOVER]
    assert r.s1.status == "normal" and r.s1.recovered


def test_support_recovery_on_second_and_third_observation_day() -> None:
    for recover_k in (4, 5):
        r = new_round(G=9.4, L_F=9.0)
        r.step(ctx(r, 1, 10.0))
        r.step(ctx(r, 2, 9.3))
        for k in range(3, recover_k):
            r.step(ctx(r, k, 9.3))
        events = r.step(ctx(r, recover_k, 9.45))
        assert SUPPORT_RECOVER in names(events), recover_k
        assert r.s1.status == "normal"


def test_support_three_failed_observation_days_removes_from_first_pool() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    r.step(ctx(r, 2, 9.3))
    assert r.step(ctx(r, 3, 9.3)) == []
    assert r.step(ctx(r, 4, 9.3)) == []
    events = r.step(ctx(r, 5, 9.3))
    assert SUPPORT_BROKEN in names(events)
    assert r.out and not r.in_first_pool
    assert r.first_out_reason == "support_broken"


def test_support_close_equal_is_neither_break_nor_recovery() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    assert r.step(ctx(r, 2, 9.4)) == []
    r.step(ctx(r, 3, 9.3))
    assert SUPPORT_RECOVER not in names(r.step(ctx(r, 4, 9.4)))
    assert r.s1.obs_left == 2
    assert r.step(ctx(r, 5, 9.4)) == []
    assert r.s1.obs_left == 1
    events = r.step(ctx(r, 6, 9.4))
    assert SUPPORT_BROKEN in names(events)


def test_s1_rebreak_after_recovery_removes_immediately() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    r.step(ctx(r, 2, 9.3))
    r.step(ctx(r, 3, 9.5))
    events = r.step(ctx(r, 4, 9.3))
    assert names(events) == [SUPPORT_BREAK, SUPPORT_BROKEN]
    assert r.out and r.first_out_reason == "support_rebreak"


def test_s2_rebreak_after_recovery_observes_again() -> None:
    r = new_round(G=9.0, L_F=9.5)
    r.step(ctx(r, 1, 10.0))
    assert SUPPORT_BREAK in names(r.step(ctx(r, 2, 9.4)))
    assert r.s2.status == "observing" and r.s1.status == "normal"
    assert SUPPORT_RECOVER in names(r.step(ctx(r, 3, 9.6)))
    assert SUPPORT_BREAK in names(r.step(ctx(r, 4, 9.4)))
    assert r.s2.status == "observing" and r.s2.obs_left == 3
    assert SUPPORT_RECOVER in names(r.step(ctx(r, 5, 9.6)))
    assert r.s2.status == "normal"


def test_suspension_counts_as_support_observation_day() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    r.step(ctx(r, 2, 9.3))
    assert r.step(ctx(r, 3, None)) == []
    assert r.s1.obs_left == 2
    assert r.step(ctx(r, 4, None)) == []
    assert r.s1.obs_left == 1
    events = r.step(ctx(r, 5, None))
    assert SUPPORT_BROKEN in names(events)


def test_round_state_roundtrip() -> None:
    r = new_round(G=9.4, L_F=9.0)
    r.step(ctx(r, 1, 10.0))
    r.step(ctx(r, 2, 9.3))
    r.step(ctx(r, 3, 9.5))
    r.step(ctx(r, 4, 10.6))
    restored = Round.from_state(r.to_state())
    assert restored.to_state() == r.to_state()
    assert restored.summary()["first_pool_days"] == r.summary()["first_pool_days"]
