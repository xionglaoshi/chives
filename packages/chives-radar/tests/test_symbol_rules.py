from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta

from chives_radar.engine import Engine
from support import DAY0, MemoryStore, StepClock, config, quote


class FunctionSource:
    def __init__(self, func):
        self.func = func

    def fetch(self, codes, now):
        return {code: value for code, value in self.func(codes, now).items() if code in codes}


def run(cfg, source, *, seconds=30):
    clock = StepClock()
    store = MemoryStore()
    engine = Engine(cfg, FunctionSource(source), clock, store, rng=random.Random(7))
    engine.run(threading.Event(), end_at=DAY0 + timedelta(seconds=seconds))
    return engine, store


def const(price, *, name="标的"):
    def fetch(codes, now):
        return {code: quote(code=code, name=name, price=price, exch=now) for code in codes}

    return fetch


def test_symbols_rule_only_evaluates_listed_codes():
    cfg = config(
        watchlist=["002553.SZ", "601099.SH"],
        rules=[
            {
                "id": "scoped_up",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 3.0,
                "symbols": ["002553.SZ"],
            },
            {
                "id": "global_up",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 3.0,
            },
        ],
    )
    engine, store = run(cfg, const(15.47), seconds=6)
    fired = [(alert["code"], alert["rule_id"]) for alert in store.alerts]
    assert {code for code, rule in fired if rule == "scoped_up"} == {"002553.SZ"}
    assert {code for code, rule in fired if rule == "global_up"} == {"002553.SZ", "601099.SH"}

    scoped_rows = [row for row in engine.state_dict()["rules"] if row["rule_id"] == "scoped_up"]
    assert [row["code"] for row in scoped_rows] == ["002553.SZ"]


def test_rule_without_symbols_applies_to_every_watched_code():
    cfg = config(watchlist=["002553.SZ", "601099.SH", "512880.SH"])
    _, store = run(cfg, const(15.47), seconds=6)
    assert {alert["code"] for alert in store.alerts} == {
        "002553.SZ",
        "601099.SH",
        "512880.SH",
    }


def test_cooldown_is_tracked_per_rule_and_symbol():
    def fetch(codes, now):
        elapsed = (now - DAY0).total_seconds()
        result = {}
        for code in codes:
            if code == "002553.SZ":
                price = 15.47 if elapsed < 300 else (15.20 if elapsed < 360 else 15.47)
            else:
                price = 15.0 if elapsed < 120 else 15.47
            result[code] = quote(code=code, price=price, exch=now)
        return result

    cfg = config(
        watchlist=["002553.SZ", "601099.SH"],
        rules=[
            {
                "id": "scoped_up",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 3.0,
                "symbols": ["002553.SZ", "601099.SH"],
            }
        ],
    )
    _, store = run(cfg, fetch, seconds=400)
    fired = [(alert["code"], datetime.fromisoformat(alert["ts"])) for alert in store.alerts]
    assert [(code, moment - DAY0) for code, moment in fired] == [
        ("002553.SZ", timedelta(0)),
        ("601099.SH", timedelta(seconds=120)),
        ("002553.SZ", timedelta(seconds=360)),
    ]


def test_runtime_added_symbol_is_not_mis_evaluated_by_a_scoped_rule():
    def fetch(codes, now):
        return {
            code: quote(code=code, name=f"名称{code[:6]}", price=15.30, exch=now)
            for code in codes
        }

    cfg = config(
        watchlist=["002553.SZ"],
        rules=[
            {
                "id": "scoped_up",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 2.0,
                "symbols": ["601099.SH"],
            },
            {
                "id": "global_up",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 1.0,
            },
        ],
    )
    clock = StepClock()
    engine = Engine(cfg, FunctionSource(fetch), clock, MemoryStore())
    engine.add_symbol("601099")
    engine.add_symbol("300750")
    engine.poll()

    fired = {(alert["code"], alert["rule_id"]) for alert in engine.alerts()["alerts"]}
    assert ("002553.SZ", "scoped_up") not in fired
    assert ("002553.SZ", "global_up") in fired
    assert ("601099.SH", "scoped_up") in fired
    assert ("601099.SH", "global_up") in fired
    assert ("300750.SZ", "global_up") in fired
    assert ("300750.SZ", "scoped_up") not in fired

    scoped_rows = [row for row in engine.state_dict()["rules"] if row["rule_id"] == "scoped_up"]
    assert [row["code"] for row in scoped_rows] == ["601099.SH"]


def test_missing_symbols_warning_does_not_block_runtime_addition(caplog):
    cfg = config(
        watchlist=["002553.SZ"],
        rules=[
            {
                "id": "later",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 2.0,
                "symbols": ["601099.SH"],
            }
        ],
    )
    assert cfg.rules[0].applies_to("601099.SH")
    assert any("later" in record.getMessage() for record in caplog.records)
