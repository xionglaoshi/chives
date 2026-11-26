"""Lag-behind-wall-clock staleness (polling.max_lag_seconds)."""

from __future__ import annotations

import copy
import json
import threading
import urllib.request
from datetime import datetime, timedelta

import pytest

from chives_radar.config import ConfigError, parse_config
from chives_radar.engine import Engine, SourceError
from chives_radar.server import make_server, stop_server
from support import BASE_CONFIG, DAY0, MemoryStore, ScriptedSource, StepClock, config, quote


def with_lag(value: float):
    polling = copy.deepcopy(BASE_CONFIG["polling"])
    polling["max_lag_seconds"] = value
    return config(polling=polling)


def lag_source(lag_fn, price_fn=lambda _: 15.0):
    def fetch(codes, now):
        elapsed = (now - DAY0).total_seconds()
        exch = now - timedelta(seconds=lag_fn(elapsed))
        return {code: quote(price=price_fn(elapsed), exch=exch) for code in codes}

    return fetch


class FunctionSource:
    def __init__(self, func):
        self.func = func

    def fetch(self, codes, now):
        return self.func(codes, now)


def run(cfg, source, *, seconds=120, start=DAY0):
    if callable(source) and not hasattr(source, "fetch"):
        source = FunctionSource(source)
    clock = StepClock(start)
    store = MemoryStore()
    engine = Engine(cfg, source, clock, store)
    engine.run(threading.Event(), end_at=start + timedelta(seconds=seconds))
    return engine, store, clock


def poll_at(store, seconds):
    target = DAY0 + timedelta(seconds=seconds)
    return next((row for row in store.polls if datetime.fromisoformat(row["t"]) == target), None)


# ------------------------------------------------------------- boundaries
def test_lag_exactly_at_threshold_is_not_stale():
    _, store, _ = run(with_lag(20), lag_source(lambda _: 20), seconds=30)
    assert store.polls
    assert all(row["lag_seconds"] == 20.0 for row in store.polls)
    assert all(row["stale"] is False for row in store.polls)
    assert all(row["health"] == "ok" for row in store.polls)
    assert store.alerts == []


def test_lag_slightly_above_threshold_is_stale():
    _, store, _ = run(with_lag(20), lag_source(lambda _: 20.5), seconds=30)
    assert store.polls
    assert all(row["lag_seconds"] == 20.5 for row in store.polls)
    assert all(row["stale"] is True for row in store.polls)
    assert all(row["health"] == "stale" for row in store.polls)
    assert store.alerts == []


def test_lag_seconds_keeps_original_float_precision():
    _, store, _ = run(with_lag(20), lag_source(lambda _: 20.25), seconds=6)
    assert store.polls
    assert all(row["lag_seconds"] == 20.25 for row in store.polls)


# -------------------------------------------------- advance but still lagging
def test_advancing_but_lagging_is_stale_and_never_alerts():
    _, store, _ = run(
        with_lag(20),
        lag_source(lambda _: 40, price_fn=lambda elapsed: 15.6 if elapsed >= 30 else 15.0),
        seconds=120,
    )
    assert store.alerts == []
    assert all(row["stale"] is True for row in store.polls)
    assert all(row["health"] == "stale" for row in store.polls)
    assert all(row["lag_seconds"] == 40.0 for row in store.polls)


def test_catching_up_clears_stale_and_alerts_once():
    _, store, _ = run(
        with_lag(20),
        lag_source(
            lambda elapsed: 40 if elapsed < 90 else 3,
            price_fn=lambda elapsed: 15.6 if elapsed >= 30 else 15.0,
        ),
        seconds=120,
    )
    assert poll_at(store, 87)["stale"] is True
    assert poll_at(store, 87)["lag_seconds"] == 40.0
    assert poll_at(store, 90)["stale"] is False
    assert poll_at(store, 90)["lag_seconds"] == 3.0
    assert poll_at(store, 90)["health"] == "ok"
    assert len(store.alerts) == 1
    assert datetime.fromisoformat(store.alerts[0]["ts"]) == DAY0 + timedelta(seconds=90)
    caught_up = poll_at(store, 90)["t"]
    assert all(row["stale"] is False for row in store.polls if row["t"] >= caught_up)


# -------------------------------------------------------------- validation
@pytest.mark.parametrize("value", [0, -5, "abc", True, None])
def test_invalid_max_lag_seconds_is_a_config_error(value):
    polling = copy.deepcopy(BASE_CONFIG["polling"])
    polling["max_lag_seconds"] = value
    with pytest.raises(ConfigError):
        parse_config(dict(copy.deepcopy(BASE_CONFIG), polling=polling))


def test_max_lag_seconds_defaults_to_20():
    assert config().polling.max_lag_seconds == 20.0
    assert "max_lag_seconds" not in BASE_CONFIG["polling"]


# --------------------------------------------------------------- watchlist
def test_latest_timestamp_across_watchlist_ignores_a_suspended_symbol():
    cfg = config(watchlist=["002553.SZ", "300750.SZ"])
    frozen = DAY0 - timedelta(seconds=300)

    def source(codes, now):
        return {
            "002553.SZ": quote(price=15.0, exch=now),
            "300750.SZ": quote(code="300750.SZ", price=200.0, prev_close=200.0, exch=frozen),
        }

    engine, store, _ = run(cfg, source, seconds=30)
    assert store.polls
    assert all(row["lag_seconds"] == 0.0 for row in store.polls)
    assert all(row["stale"] is False for row in store.polls)
    state = engine.state_dict()
    assert state["lag_seconds"] == 0.0
    assert state["last_exchange_time"] == (DAY0 + timedelta(seconds=30)).isoformat()


# ------------------------------------------------------------- exposure
def test_health_state_and_every_poll_row_expose_lag_fields():
    cfg = with_lag(30)
    source = ScriptedSource([{"002553.SZ": quote(price=15.0, exch=DAY0)}, SourceError("timeout")])
    clock = StepClock()
    store = MemoryStore()
    engine = Engine(cfg, source, clock, store)

    assert engine.state_dict()["lag_seconds"] is None
    assert engine.health_dict()["lag_seconds"] is None
    assert engine.state_dict()["max_lag_seconds"] == 30.0

    engine.poll()
    state = engine.state_dict()
    health = engine.health_dict()
    assert state["lag_seconds"] == 0.0
    assert state["max_lag_seconds"] == 30.0
    assert health["lag_seconds"] == 0.0
    assert health["max_lag_seconds"] == 30.0
    assert store.polls[-1]["lag_seconds"] == 0.0
    assert store.polls[-1]["max_lag_seconds"] == 30.0

    clock.advance(3)
    engine.poll()
    failed = store.polls[-1]
    assert failed["ok"] is False
    assert failed["lag_seconds"] == 3.0
    assert failed["max_lag_seconds"] == 30.0


def test_http_health_and_state_expose_lag_fields():
    engine = Engine(
        with_lag(20),
        ScriptedSource([{"002553.SZ": quote(price=15.0, exch=DAY0 - timedelta(seconds=40))}]),
        StepClock(),
        MemoryStore(),
    )
    engine.poll()
    httpd = make_server(engine, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/health", timeout=5) as response:
            health = json.loads(response.read())
        with urllib.request.urlopen(base + "/state", timeout=5) as response:
            state = json.loads(response.read())
        assert health["lag_seconds"] == 40.0
        assert health["max_lag_seconds"] == 20.0
        assert health["status"] == "stale"
        assert state["lag_seconds"] == 40.0
        assert state["max_lag_seconds"] == 20.0
        assert state["stale"] is True
    finally:
        stop_server(httpd, thread)


def test_lag_is_not_stale_outside_active_windows():
    start = DAY0.replace(hour=11, minute=29, second=0)

    def source(codes, now):
        return {code: quote(price=15.0, exch=now - timedelta(seconds=60)) for code in codes}

    _, store, _ = run(config(), source, seconds=70, start=start)
    after_close = [
        row
        for row in store.polls
        if datetime.fromisoformat(row["t"]).time() >= start.replace(hour=11, minute=30).time()
    ]
    assert after_close
    assert all(row["stale"] is False for row in after_close)
    assert all(row["lag_seconds"] == 60.0 for row in after_close)
