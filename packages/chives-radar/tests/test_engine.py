from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta

import pytest

from chives_radar.engine import Engine, SourceError
from chives_radar.models import CN_TZ
from support import BASE_CONFIG, DAY0, MemoryStore, ScriptedSource, StepClock, config, quote


class FunctionSource:
    def __init__(self, func):
        self.func = func

    def fetch(self, codes, now):
        return self.func(codes, now)


def run(cfg, source, *, start=DAY0, seconds=200, store=None):
    if callable(source) and not hasattr(source, "fetch"):
        source = FunctionSource(source)
    clock = StepClock(start)
    store = store or MemoryStore()
    engine = Engine(cfg, source, clock, store, rng=random.Random(7))
    engine.run(threading.Event(), end_at=start + timedelta(seconds=seconds))
    return engine, store, clock


def timed_source(price_fn, *, exch_fn=None):
    def fetch(codes, now):
        elapsed = (now - DAY0).total_seconds()
        exch = exch_fn(elapsed, now) if exch_fn else now
        return {code: quote(price=price_fn(elapsed), exch=exch) for code in codes}

    return FunctionSource(fetch)


def alert_times(store):
    return [datetime.fromisoformat(alert["ts"]) for alert in store.alerts]


def poll_at(store, seconds):
    target = DAY0 + timedelta(seconds=seconds)
    return next(
        (row for row in store.polls if datetime.fromisoformat(row["t"]) == target), None
    )


# ------------------------------------------------------------- cooldown
def test_cooldown_retreat_and_rearm():
    def price(elapsed):
        if elapsed < 300:
            return 15.20
        if elapsed < 480:
            return 15.47
        if elapsed < 540:
            return 15.20
        return 15.47

    cfg = config()
    _, store, _ = run(cfg, timed_source(price), seconds=610)
    times = alert_times(store)
    assert len(times) == 2
    assert times[0] == DAY0 + timedelta(seconds=300)
    assert DAY0 + timedelta(seconds=600) <= times[1] <= DAY0 + timedelta(seconds=606)


def test_cooldown_elapsed_without_retreat_does_not_fire():
    cfg = config()
    _, store, _ = run(cfg, timed_source(lambda _: 15.47), seconds=400)
    assert len(store.alerts) == 1


def test_retreat_without_cooldown_does_not_fire():
    def price(elapsed):
        if elapsed < 60:
            return 15.47
        if elapsed < 120:
            return 15.20
        return 15.47

    cfg = config()
    _, store, _ = run(cfg, timed_source(price), seconds=240)
    assert len(store.alerts) == 1
    assert poll_at(store, 120)["mode"] == "base"


# ----------------------------------------------------------- price cross
def test_price_cross_first_snapshot_and_hysteresis():
    def price(elapsed):
        if elapsed < 60:
            return 15.90
        if elapsed < 63:
            return 15.90
        if elapsed < 393:
            return 16.03
        if elapsed < 702:
            return 15.90
        return 16.05

    cfg = config(
        rules=[{"id": "cross_16", "type": "price_cross", "level": 16.0, "direction": "up"}]
    )
    _, store, _ = run(cfg, timed_source(price), seconds=710)
    times = alert_times(store)
    assert len(times) == 2
    assert times[0] == DAY0 + timedelta(seconds=63)
    assert DAY0 + timedelta(seconds=702) <= times[1] <= DAY0 + timedelta(seconds=708)


def test_duplicate_snapshot_is_never_evaluated():
    frozen = DAY0 + timedelta(seconds=60)

    def source(codes, now):
        elapsed = (now - DAY0).total_seconds()
        exch = frozen if elapsed < 66 else now
        price = 15.90 if elapsed < 63 else 16.05
        return {"002553.SZ": quote(price=price, exch=exch)}

    cfg = config(
        rules=[{"id": "cross_16", "type": "price_cross", "level": 16.0, "direction": "up"}]
    )
    _, store, _ = run(cfg, source, seconds=80)
    assert len(store.alerts) == 1
    assert alert_times(store)[0] == DAY0 + timedelta(seconds=66)


# ----------------------------------------------------------------- stale
def test_stale_detection_suppression_and_recovery():
    frozen = DAY0 + timedelta(seconds=60)

    def source(codes, now):
        elapsed = (now - DAY0).total_seconds()
        if elapsed < 63:
            return {"002553.SZ": quote(price=15.0, exch=now)}
        if elapsed < 96:
            return {"002553.SZ": quote(price=15.5, exch=frozen)}
        return {"002553.SZ": quote(price=15.5, exch=now)}

    cfg = config()
    _, store, _ = run(cfg, source, seconds=120)
    assert len(store.alerts) == 1
    assert alert_times(store)[0] == DAY0 + timedelta(seconds=96)
    assert poll_at(store, 75)["stale"] is False
    assert poll_at(store, 78)["stale"] is True
    assert poll_at(store, 78)["health"] == "stale"
    assert poll_at(store, 96)["stale"] is False
    assert poll_at(store, 96)["health"] == "ok"


# --------------------------------------------------------- active window
def test_outside_active_window_updates_but_never_fires():
    start = DAY0.replace(hour=11, minute=29, second=0)
    noon = DAY0.replace(hour=11, minute=30, second=30)
    reopen = DAY0.replace(hour=13, minute=0, second=0)

    def source(codes, now):
        price = 15.5 if now >= noon else 15.0
        return {"002553.SZ": quote(price=price, exch=now)}

    cfg = config()
    _, store, _ = run(cfg, source, start=start, seconds=(reopen - start).total_seconds() + 2)
    times = alert_times(store)
    assert len(times) == 1
    assert times[0] == reopen
    idle_polls = [row for row in store.polls if row["mode"] == "idle"]
    assert idle_polls and all(row["next_interval"] == 30.0 for row in idle_polls)


# --------------------------------------------------------------- schedule
def test_adaptive_fast_mode_and_hold():
    def price(elapsed):
        return 15.42 if 60 <= elapsed < 75 else 15.0

    cfg = config()
    _, store, _ = run(cfg, timed_source(price), seconds=200)
    before = [row for row in store.polls if datetime.fromisoformat(row["t"]) < DAY0 + timedelta(seconds=60)]
    fast = [row for row in store.polls if row["mode"] == "fast"]
    assert before and all(row["mode"] == "base" and row["next_interval"] == 3.0 for row in before)
    assert fast
    assert all(row["next_interval"] == 1.0 for row in fast)
    assert poll_at(store, 90)["mode"] == "fast"
    late = [
        row
        for row in store.polls
        if datetime.fromisoformat(row["t"]) >= DAY0 + timedelta(seconds=105)
    ]
    assert late and all(row["mode"] == "base" for row in late)


def test_base_mode_by_default():
    cfg = config()
    _, store, _ = run(cfg, timed_source(lambda _: 15.0), seconds=30)
    assert all(row["mode"] == "base" and row["next_interval"] == 3.0 for row in store.polls)


def test_backoff_sequence_and_recovery():
    def source(codes, now):
        elapsed = (now - DAY0).total_seconds()
        if 60 <= elapsed < 130:
            raise SourceError("timeout")
        return {"002553.SZ": quote(price=15.0, exch=now)}

    cfg = config()
    _, store, _ = run(cfg, source, seconds=200)
    expected = {
        60: (False, "backoff", 3.0, "degraded", 1),
        63: (False, "backoff", 6.0, "degraded", 2),
        69: (False, "backoff", 12.0, "down", 3),
        81: (False, "backoff", 30.0, "down", 4),
        111: (False, "backoff", 30.0, "down", 5),
    }
    for second, (ok, mode, interval, health, failures) in expected.items():
        row = poll_at(store, second)
        assert row is not None, second
        assert (row["ok"], row["mode"], row["next_interval"], row["health"], row["consecutive_failures"]) == (
            ok,
            mode,
            interval,
            health,
            failures,
        )
    recovery = poll_at(store, 141)
    assert recovery["ok"] is True
    assert recovery["mode"] == "base"
    assert recovery["next_interval"] == 3.0
    assert recovery["health"] == "ok"
    assert recovery["consecutive_failures"] == 0


def test_jitter_stays_within_band():
    polling = dict(BASE_CONFIG["polling"], jitter_pct=10)
    cfg = config(polling=polling)
    _, store, _ = run(cfg, timed_source(lambda _: 15.0), seconds=30)
    for row in store.polls:
        assert 2.7 <= row["next_interval"] <= 3.3


# -------------------------------------------------------------- multiple
def test_missing_codes_are_reported_without_failing_the_poll():
    def source(codes, now):
        return {"002553.SZ": quote(price=15.0, exch=now)}

    cfg = config(watchlist=["002553.SZ", "300750.SZ"])
    engine, store, _ = run(cfg, source, seconds=10)
    state = engine.state_dict()
    assert state["missing"] == ["300750.SZ"]
    assert "002553.SZ" in state["quotes"]
    assert all(row["ok"] for row in store.polls)


def test_stale_ends_as_soon_as_timestamp_advances():
    def source(codes, now):
        elapsed = (now - DAY0).total_seconds()
        if elapsed < 60:
            return {"002553.SZ": quote(price=15.0, exch=now)}
        if elapsed < 93:
            return {"002553.SZ": quote(price=15.0, exch=DAY0 + timedelta(seconds=60))}
        return {"002553.SZ": quote(price=15.5, exch=now - timedelta(seconds=20))}

    cfg = config()
    _, store, _ = run(cfg, source, seconds=110)
    assert poll_at(store, 78)["health"] == "stale"
    assert poll_at(store, 93)["health"] == "ok"
    assert poll_at(store, 93)["stale"] is False
    assert alert_times(store)[0] == DAY0 + timedelta(seconds=93)


def test_price_cross_uses_the_last_valid_snapshot_even_outside_windows():
    start = DAY0.replace(hour=11, minute=29, second=0)
    jump = DAY0.replace(hour=11, minute=30, second=30)
    reopen = DAY0.replace(hour=13, minute=0, second=0)

    def source(codes, now):
        price = 15.5 if now >= jump else 15.0
        return {"002553.SZ": quote(price=price, exch=now)}

    cfg = config(
        rules=[{"id": "cross_15_2", "type": "price_cross", "level": 15.2, "direction": "up"}]
    )
    _, store, _ = run(cfg, source, start=start, seconds=(reopen - start).total_seconds() + 2)
    assert store.alerts == []


def test_first_snapshot_with_an_old_exchange_timestamp_is_stale():
    frozen = DAY0 - timedelta(seconds=60)

    def source(codes, now):
        elapsed = (now - DAY0).total_seconds()
        exch = frozen if elapsed < 30 else now
        return {"002553.SZ": quote(price=15.5, exch=exch)}

    cfg = config()
    _, store, _ = run(cfg, source, seconds=60)
    assert poll_at(store, 0)["stale"] is True
    assert store.alerts and alert_times(store)[0] == DAY0 + timedelta(seconds=30)


def test_price_cross_first_engine_snapshot_never_fires():
    def source(codes, now):
        return {"002553.SZ": quote(price=15.5, exch=now)}

    cfg = config(
        rules=[{"id": "cross_15", "type": "price_cross", "level": 15.0, "direction": "up"}]
    )
    _, store, _ = run(cfg, source, seconds=12)
    assert store.alerts == []


def test_empty_watchlist_polls_nothing_and_stays_healthy():
    seen: list[list[str]] = []

    def fetch(codes, now):
        seen.append(list(codes))
        return {}

    engine, store, _ = run(config(watchlist=[], rules=[]), fetch, seconds=120)
    assert seen and all(codes == [] for codes in seen)
    assert store.alerts == []
    assert engine.consecutive_failures == 0
    assert store.polls[-1]["health"] == "ok"
    assert store.polls[-1]["stale"] is False


def test_gateway_source_with_no_codes_makes_no_request():
    from chives_radar.sources import GatewaySource

    # Port 9 has no listener; fetch() must return before any socket is opened.
    assert GatewaySource("http://127.0.0.1:9").fetch([], DAY0) == {}
