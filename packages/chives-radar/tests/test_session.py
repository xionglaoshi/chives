"""Session classification and last_rule_eval_ts exposure."""

from __future__ import annotations

from datetime import datetime, timedelta

from chives_radar.engine import Engine
from chives_radar.models import CN_TZ
from support import MemoryStore, ScriptedSource, StepClock, config, quote


def at(hour: int, minute: int, second: int = 0, *, day: int = 3) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=CN_TZ)


class FunctionSource:
    def __init__(self, func) -> None:
        self.func = func

    def fetch(self, codes, now):
        return self.func(codes, now)


def advance_to(clock: StepClock, moment: datetime) -> None:
    clock.advance((moment - clock.now()).total_seconds())


def poll_once(moment: datetime, *, price: float = 15.0, exch: datetime | None = None):
    clock = StepClock(moment)
    store = MemoryStore()
    source = ScriptedSource(
        [{"002553.SZ": quote(price=price, exch=exch if exch is not None else moment)}]
    )
    engine = Engine(config(), source, clock, store)
    outcome = engine.poll()
    return engine, store, outcome


# ------------------------------------------------------------------ session
def test_session_pre_open_before_the_first_window():
    _, store, _ = poll_once(at(9, 29, 59))
    assert store.polls[-1]["session"] == "pre_open"


def test_session_open_includes_both_window_ends():
    for moment in (
        at(9, 30, 0),
        at(10, 15, 0),
        at(11, 30, 0),
        at(13, 0, 0),
        at(14, 57, 0),
    ):
        _, store, _ = poll_once(moment)
        assert store.polls[-1]["session"] == "open", moment


def test_session_break_between_the_windows():
    for moment in (at(11, 30, 1), at(12, 0, 0), at(12, 59, 59)):
        _, store, _ = poll_once(moment)
        assert store.polls[-1]["session"] == "break", moment


def test_session_after_hours_after_the_last_window():
    for moment in (at(14, 57, 1), at(15, 0, 0), at(23, 59, 59)):
        _, store, _ = poll_once(moment)
        assert store.polls[-1]["session"] == "after_hours", moment


def test_session_non_trading_day_wins_over_the_clock():
    saturday = at(10, 0, 0, day=7)
    engine, store, _ = poll_once(saturday)
    assert store.polls[-1]["session"] == "non_trading_day"
    assert engine.state_dict()["session"] == "non_trading_day"


# ------------------------------------------------------- last_rule_eval_ts
def test_last_rule_eval_is_null_before_the_first_evaluation():
    _, store, _ = poll_once(at(9, 29, 0))
    row = store.polls[-1]
    assert row["session"] == "pre_open"
    assert row["last_rule_eval_ts"] is None


def test_last_rule_eval_updates_on_its_own_poll_and_freezes_when_closed():
    clock = StepClock(at(9, 29, 0))
    store = MemoryStore()
    engine = Engine(
        config(),
        ScriptedSource([lambda now: {"002553.SZ": quote(exch=now)}]),
        clock,
        store,
    )

    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] is None

    advance_to(clock, at(9, 30, 0))
    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] == at(9, 30, 0).isoformat()

    advance_to(clock, at(9, 30, 3))
    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] == at(9, 30, 3).isoformat()

    advance_to(clock, at(11, 30, 0))
    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] == at(11, 30, 0).isoformat()

    advance_to(clock, at(11, 30, 30))
    engine.poll()
    assert store.polls[-1]["session"] == "break"
    assert store.polls[-1]["last_rule_eval_ts"] == at(11, 30, 0).isoformat()

    advance_to(clock, at(12, 30, 0))
    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] == at(11, 30, 0).isoformat()

    advance_to(clock, at(13, 0, 0))
    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] == at(13, 0, 0).isoformat()

    advance_to(clock, at(14, 57, 0))
    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] == at(14, 57, 0).isoformat()

    advance_to(clock, at(14, 57, 30))
    engine.poll()
    assert store.polls[-1]["session"] == "after_hours"
    assert store.polls[-1]["last_rule_eval_ts"] == at(14, 57, 0).isoformat()


def test_last_rule_eval_stays_null_on_a_non_trading_day():
    engine, store, _ = poll_once(at(9, 30, 0, day=7))
    assert store.polls
    assert all(row["session"] == "non_trading_day" for row in store.polls)
    assert all(row["last_rule_eval_ts"] is None for row in store.polls)
    assert engine.state_dict()["last_rule_eval_ts"] is None


def test_failed_poll_does_not_advance_last_rule_eval():
    clock = StepClock(at(9, 30, 0))
    store = MemoryStore()
    engine = Engine(
        config(),
        ScriptedSource([{"002553.SZ": quote(exch=at(9, 30, 0))}, RuntimeError("timeout")]),
        clock,
        store,
    )
    engine.poll()
    assert store.polls[-1]["last_rule_eval_ts"] == at(9, 30, 0).isoformat()

    advance_to(clock, at(9, 30, 3))
    outcome = engine.poll()
    assert outcome.ok is False
    assert store.polls[-1]["session"] == "open"
    assert store.polls[-1]["last_rule_eval_ts"] == at(9, 30, 0).isoformat()


def test_stale_rule_is_unchanged_when_rules_are_evaluated_at_the_closing_second():
    clock = StepClock(at(11, 29, 0))
    store = MemoryStore()

    def source(codes, now):
        return {code: quote(exch=now - timedelta(seconds=60)) for code in codes}

    engine = Engine(config(), FunctionSource(source), clock, store)
    engine.poll()
    advance_to(clock, at(11, 30, 0))
    engine.poll()
    row = store.polls[-1]
    assert row["session"] == "open"
    assert row["stale"] is False
    assert row["lag_seconds"] == 60.0
    assert row["last_rule_eval_ts"] == at(11, 30, 0).isoformat()


def test_state_and_health_expose_session_and_last_rule_eval():
    engine, store, _ = poll_once(at(11, 30, 0))
    state = engine.state_dict()
    health = engine.health_dict()
    expected = at(11, 30, 0).isoformat()
    assert state["session"] == "open"
    assert state["last_rule_eval_ts"] == expected
    assert health["session"] == "open"
    assert health["last_rule_eval_ts"] == expected
    assert store.states[-1]["session"] == "open"
    assert store.states[-1]["last_rule_eval_ts"] == expected
