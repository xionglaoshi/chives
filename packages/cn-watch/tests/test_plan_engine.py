from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from cn_watch.engine import Engine
from cn_watch.market_context import MarketSnapshot
from cn_watch.models import CN_TZ
from cn_watch.plans import PlanError
from cn_watch.storage import FileStore
from support import FakeMarket, ScriptedSource, StepClock, config, plan, quote

CODE = "002553.SZ"


def step(price: float, *, code: str = CODE, **fields):
    def build(now):
        return {code: quote(price, code=code, prev_close=15.0, exch=now, **fields)}

    return build


def build(tmp_path, *, overrides=None, steps=None, market=None, store=None, clock=None):
    cfg = config(**(overrides or {}))
    out = store or FileStore(tmp_path / "data")
    engine = Engine(
        cfg,
        ScriptedSource(steps or [{}]),
        clock or StepClock(),
        out,
        market_client=market or FakeMarket(),
    )
    return engine, out


def p(**overrides):
    return plan(**overrides)


def poll(engine, seconds=3.0):
    engine.clock.advance(seconds)
    return engine.poll()


def codes(engine):
    return [row["code"] for row in engine.watchlist_dict()["watchlist"]]


def sources(engine):
    return {row["code"]: row["source"] for row in engine.watchlist_dict()["watchlist"]}


def test_upsert_adds_plan_code_to_runtime_watchlist(tmp_path):
    engine, store = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    result = engine.upsert_plan(p(code="601099.SH"))
    assert result["status"] == "created"
    assert codes(engine) == [CODE, "601099.SH"]
    assert sources(engine)["601099.SH"] == "plan"
    assert json.loads((store.out_dir / "watchlist.runtime.json").read_text()) == ["601099.SH"]
    state_rows = {row["code"]: row for row in engine.state_dict()["watchlist"]}
    assert state_rows["601099.SH"]["source"] == "plan"


def test_upsert_existing_config_code_is_not_marked_plan(tmp_path):
    engine, _ = build(tmp_path)
    engine.upsert_plan(p())
    assert sources(engine)[CODE] == "config"


def test_upsert_existing_user_runtime_code_is_not_marked_plan(tmp_path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    engine.source.quotes = {}
    engine.source.steps = [step(15.0, code="601099.SH")]
    engine.add_symbol("601099.SH")
    assert sources(engine)["601099.SH"] == "runtime"
    engine.upsert_plan(p(code="601099.SH"))
    assert sources(engine)["601099.SH"] == "runtime"


def test_remove_plan_revokes_auto_watch(tmp_path):
    engine, store = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    engine.upsert_plan(p(code="601099.SH"))
    result = engine.remove_plan("plan-1")
    assert result["status"] == "removed"
    assert codes(engine) == [CODE]
    assert json.loads((store.out_dir / "watchlist.runtime.json").read_text()) == []
    assert engine.plans_payload()["plans"] == []


def test_remove_plan_keeps_user_runtime_code(tmp_path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    engine.source.steps = [step(15.0, code="601099.SH")]
    engine.add_symbol("601099.SH")
    engine.upsert_plan(p(code="601099.SH"))
    engine.remove_plan("plan-1")
    assert codes(engine) == [CODE, "601099.SH"]
    assert sources(engine)["601099.SH"] == "runtime"


def test_remove_plan_keeps_config_code(tmp_path):
    engine, _ = build(tmp_path)
    engine.upsert_plan(p())
    engine.remove_plan("plan-1")
    assert codes(engine) == [CODE]
    assert sources(engine)[CODE] == "config"


def test_remove_one_of_two_plans_keeps_auto_watch(tmp_path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    engine.upsert_plan(p(id="a", code="601099.SH"))
    engine.upsert_plan(p(id="b", code="601099.SH"))
    engine.remove_plan("a")
    assert "601099.SH" in codes(engine)
    engine.remove_plan("b")
    assert "601099.SH" not in codes(engine)


def test_remove_missing_plan_is_404(tmp_path):
    engine, _ = build(tmp_path)
    with pytest.raises(PlanError) as excinfo:
        engine.remove_plan("nope")
    assert excinfo.value.code == "not_found"
    assert excinfo.value.status_code == 404


def test_add_symbol_promotes_auto_plan_code_to_user(tmp_path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    engine.upsert_plan(p(code="601099.SH"))
    assert sources(engine)["601099.SH"] == "plan"
    engine.source.steps = [step(15.0, code="601099.SH")]
    engine.add_symbol("601099.SH")
    assert sources(engine)["601099.SH"] == "runtime"
    engine.remove_plan("plan-1")
    assert "601099.SH" in codes(engine)


def test_remove_symbol_clears_auto_marker(tmp_path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    engine.upsert_plan(p(code="601099.SH"))
    engine.remove_symbol("601099.SH")
    assert "601099.SH" not in codes(engine)
    engine.upsert_plan(p(id="second", code="601099.SH"))
    assert sources(engine)["601099.SH"] == "plan"


def test_restart_restores_plan_state_source_and_history(tmp_path):
    clock = StepClock()
    engine, store = build(
        tmp_path,
        overrides={"limits": {"max_watchlist": 2}, "rules": []},
        steps=[step(16.0, code="601099.SH")],
        clock=clock,
    )
    engine.upsert_plan(p(code="601099.SH", stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"

    second = Engine(
        engine.config,
        ScriptedSource([step(16.0, code="601099.SH")]),
        StepClock(),
        FileStore(store.out_dir),
        market_client=FakeMarket(),
    )
    assert second.plan_payload("plan-1")["state"] == "execute"
    assert second.plan_payload("plan-1")["history"][0]["to"] == "execute"
    assert sources(second)["601099.SH"] == "plan"


def test_restart_first_evaluation_does_not_alert(tmp_path):
    engine, store = build(
        tmp_path,
        overrides={"limits": {"max_watchlist": 2}, "rules": []},
        steps=[step(16.0, code="601099.SH")],
    )
    engine.upsert_plan(p(code="601099.SH", stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    engine.poll()
    before = max(item["id"] for item in engine.alerts()["alerts"])

    second = Engine(
        engine.config,
        ScriptedSource([step(16.0, code="601099.SH")]),
        StepClock(),
        FileStore(store.out_dir),
        market_client=FakeMarket(),
    )
    second.poll()
    after = second.alerts()["alerts"]
    assert max(item["id"] for item in after) == before
    assert second.plan_payload("plan-1")["state"] == "execute"


def test_expired_plan_is_not_evaluated_and_has_no_alert(tmp_path):
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0)],
    )
    engine.upsert_plan(
        p(
            stock=[{"type": "price_cross", "direction": "up", "level": 16.0}],
            expires_at="2026-11-03T09:31:00+08:00",
        )
    )
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    engine.clock.advance(120)
    engine.poll()
    payload = engine.plan_payload("plan-1")
    assert payload["state"] == "expired"
    assert payload["active"] is False
    assert payload["history"][-1]["to"] == "expired"
    assert [item for item in engine.alerts()["alerts"] if item.get("rule_type") == "plan"][-1]["detail"]["to"] == "execute"

    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "expired"


def test_expired_auto_watch_is_released_after_one_trading_day(tmp_path):
    clock = StepClock()
    engine, _ = build(
        tmp_path,
        overrides={"limits": {"max_watchlist": 2}, "rules": []},
        clock=clock,
    )
    engine.upsert_plan(
        p(code="601099.SH", expires_at="2026-11-03T10:00:00+08:00")
    )
    assert "601099.SH" in codes(engine)
    clock.advance(3600)
    engine.upsert_plan(p(id="other", code="002553.SZ"))
    engine.poll()
    assert "601099.SH" in codes(engine)
    clock.advance(86400)
    engine.poll()
    assert "601099.SH" not in codes(engine)


def test_non_trading_day_does_not_evaluate(tmp_path):
    clock = StepClock(datetime(2026, 11, 7, 10, 0, 0, tzinfo=CN_TZ))
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0)],
        clock=clock,
    )
    engine.upsert_plan(p(stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "observe"
    assert engine.alerts()["alerts"] == []


def test_outside_active_window_does_not_evaluate(tmp_path):
    clock = StepClock(datetime(2026, 11, 3, 12, 0, 0, tzinfo=CN_TZ))
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0)],
        clock=clock,
    )
    engine.upsert_plan(p(stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "observe"
    assert engine.alerts()["alerts"] == []


def test_execute_steps_up_immediately_and_down_after_three(tmp_path):
    clock = StepClock()
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[
            step(16.0),
            step(15.0),
            step(15.0),
            step(15.0),
        ],
        clock=clock,
    )
    engine.upsert_plan(p(stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    clock.advance(3)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    clock.advance(3)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    clock.advance(3)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "await_confirm"
    history = engine.plan_payload("plan-1")["history"]
    assert [row["to"] for row in history] == ["execute", "await_confirm"]


def test_execute_to_await_confirm_needs_three(tmp_path):
    clock = StepClock()
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0), step(15.0), step(15.0), step(15.0)],
        clock=clock,
    )
    engine.upsert_plan(
        p(
            market=[{"type": "regime", "values": ["strong"]}],
            stock=[{"type": "price_cross", "direction": "up", "level": 16.0}],
        )
    )
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    clock.advance(3)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    clock.advance(3)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    clock.advance(3)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "await_confirm"


def test_terminal_abandon_needs_three_to_leave(tmp_path):
    clock = StepClock()
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[
            step(16.0, volume_ratio=2.0),
            step(16.0, volume_ratio=1.0),
            step(16.0, volume_ratio=1.0),
            step(16.0, volume_ratio=1.0),
        ],
        clock=clock,
    )
    engine.upsert_plan(p(giveup=[{"type": "volume_ratio", "op": ">=", "value": 2.0}]))
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "abandon"
    for _ in range(2):
        clock.advance(3)
        engine.poll()
        assert engine.plan_payload("plan-1")["state"] == "abandon"
    clock.advance(3)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"


def test_held_exit_is_immediate_and_alerted(tmp_path):
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(14.0)],
    )
    engine.upsert_plan(p(held=True, stop_price=14.5, stock=[{"type": "price_cross", "direction": "up", "level": 99}]))
    engine.poll()
    payload = engine.plan_payload("plan-1")
    assert payload["state"] == "exit"
    alert = [item for item in engine.alerts()["alerts"] if item.get("rule_type") == "plan"][-1]
    assert alert["severity"] == "L2"
    assert alert["detail"]["to"] == "exit"


def test_giveup_alert_and_priority_over_execute(tmp_path):
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0, volume_ratio=3.0)],
    )
    engine.upsert_plan(
        p(
            stock=[{"type": "price_cross", "direction": "up", "level": 1}],
            giveup=[{"type": "volume_ratio", "op": ">=", "value": 2}],
        )
    )
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "abandon"
    alert = [item for item in engine.alerts()["alerts"] if item.get("rule_type") == "plan"][-1]
    assert alert["severity"] == "L2"
    assert alert["rule_id"] == "plan:plan-1"
    assert alert["detail"]["from"] == "observe"


def test_await_confirm_alert_is_l1_and_has_contract_fields(tmp_path):
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(15.0)],
    )
    engine.upsert_plan(
        p(
            market=[{"type": "regime", "values": ["strong"]}],
            stock=[{"type": "price_cross", "direction": "up", "level": 16.0}],
            label="观察 A",
        )
    )
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "await_confirm"
    alert = [item for item in engine.alerts()["alerts"] if item.get("rule_type") == "plan"][-1]
    assert alert["severity"] == "L1"
    assert alert["price"] == 15.0
    assert alert["code"] == CODE
    assert alert["rule_id"] == "plan:plan-1"
    assert set(alert["detail"]) == {"plan_id", "from", "to", "reason", "label"}
    assert alert["detail"]["label"] == "观察 A"


def test_debounce_same_target_within_five_minutes(tmp_path):
    clock = StepClock()
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0), step(15.0), step(15.0), step(15.0), step(16.0)],
        clock=clock,
    )
    engine.upsert_plan(p(stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    engine.poll()
    alert_count = len([item for item in engine.alerts()["alerts"] if item.get("rule_type") == "plan"])
    assert alert_count == 1
    for _ in range(4):
        clock.advance(3)
        engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    alerts = [item for item in engine.alerts()["alerts"] if item.get("rule_type") == "plan"]
    assert [item["detail"]["to"] for item in alerts] == ["execute", "await_confirm"]


def test_debounce_allows_same_target_after_five_minutes(tmp_path):
    clock = StepClock()
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0), step(15.0), step(15.0), step(15.0), step(16.0)],
        clock=clock,
    )
    engine.upsert_plan(p(stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    engine.poll()
    for _ in range(3):
        clock.advance(3)
        engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "await_confirm"
    clock.advance(301)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "execute"
    alerts = [item for item in engine.alerts()["alerts"] if item.get("rule_type") == "plan"]
    assert [item["detail"]["to"] for item in alerts] == ["execute", "await_confirm", "execute"]
    assert [item["id"] for item in alerts] == sorted(item["id"] for item in alerts)


def test_market_failure_only_makes_conditions_unknown(tmp_path):
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0)],
        market=FakeMarket(MarketSnapshot(ok=False, age_s=99.0), error=RuntimeError("down")),
    )
    engine.upsert_plan(
        p(
            market=[{"type": "regime", "values": ["strong"]}],
            stock=[{"type": "price_cross", "direction": "up", "level": 1}],
        )
    )
    engine.poll()
    payload = engine.plan_payload("plan-1")
    assert payload["state"] == "observe"
    assert payload["conds"]["market"] == [None]
    assert payload["conds"]["stock"] == [True]
    assert engine.health_dict()["status"] in {"ok", "stale"}
    assert engine.watchlist_dict()["count"] == 1


def test_market_snapshot_regime_none_is_unknown(tmp_path):
    engine, _ = build(
        tmp_path,
        overrides={"rules": []},
        steps=[step(16.0)],
        market=FakeMarket(MarketSnapshot(ok=False, age_s=99.0)),
    )
    engine.upsert_plan(p(market=[{"type": "regime", "values": ["strong"]}]))
    engine.poll()
    assert engine.plan_payload("plan-1")["conds"]["market"] == [None]


def test_existing_rule_alerts_are_not_broken_by_plans(tmp_path):
    engine, _ = build(
        tmp_path,
        steps=[step(16.0)],
    )
    engine.upsert_plan(p(id="p", stock=[{"type": "price_cross", "direction": "up", "level": 1}]))
    engine.poll()
    alerts = engine.alerts()["alerts"]
    rule_alerts = [item for item in alerts if item.get("rule_type") == "pct_change"]
    plan_alerts = [item for item in alerts if item.get("rule_type") == "plan"]
    assert len(rule_alerts) == 1
    assert len(plan_alerts) == 1
    assert engine.alerts(after_id=rule_alerts[0]["id"])["alerts"] == plan_alerts


def test_plans_payload_market_context_and_as_of(tmp_path):
    engine, _ = build(tmp_path)
    payload = engine.plans_payload()
    assert set(payload) == {"ok", "as_of", "market_context", "plans"}
    assert payload["ok"] is True
    assert set(payload["market_context"]) == {"ok", "age_s", "regime"}


def test_plan_payload_includes_plan_and_flat_fields(tmp_path):
    engine, _ = build(tmp_path)
    engine.upsert_plan(p(label="x"))
    payload = engine.plan_payload("plan-1")
    assert payload["plan"]["id"] == "plan-1"
    assert payload["id"] == "plan-1"
    assert payload["state"] == "observe"


def test_plan_payload_missing_is_404(tmp_path):
    engine, _ = build(tmp_path)
    with pytest.raises(PlanError) as excinfo:
        engine.plan_payload("nope")
    assert excinfo.value.code == "not_found"


def test_concurrent_upserts_are_serialized(tmp_path):
    engine, _ = build(tmp_path)
    def put(index):
        return engine.upsert_plan(p(id=f"p{index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(put, range(20)))
    assert len(results) == 20
    assert len(engine.plans_payload()["plans"]) == 20


def test_concurrent_upsert_and_remove_same_plan(tmp_path):
    engine, _ = build(tmp_path)
    engine.upsert_plan(p(id="same"))
    barrier = threading.Barrier(2)

    def upsert():
        barrier.wait()
        try:
            engine.upsert_plan(p(id="same", label="again"))
        except PlanError:
            pass

    def remove():
        barrier.wait()
        try:
            engine.remove_plan("same")
        except PlanError:
            pass

    threads = [threading.Thread(target=upsert), threading.Thread(target=remove)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(engine.plans_payload()["plans"]) in {0, 1}


def test_bad_plans_file_is_empty_and_not_overwritten(tmp_path, caplog):
    store = FileStore(tmp_path / "data")
    store.out_dir.mkdir(parents=True, exist_ok=True)
    target = store.out_dir / "plans.runtime.json"
    target.write_text("{{{ not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="cn_watch.plans"):
        engine = Engine(
            config(),
            ScriptedSource([{}]),
            StepClock(),
            store,
            market_client=FakeMarket(),
        )
    assert engine.plans_payload()["plans"] == []
    assert target.read_text(encoding="utf-8") == "{{{ not json"
    assert any("已损坏" in record.getMessage() for record in caplog.records)
    engine.upsert_plan(p())
    assert len(engine.plans_payload()["plans"]) == 1


def test_wrong_structure_and_version_are_empty(tmp_path):
    store = FileStore(tmp_path / "data")
    store.out_dir.mkdir(parents=True, exist_ok=True)
    target = store.out_dir / "plans.runtime.json"
    target.write_text("[]", encoding="utf-8")
    engine = Engine(config(), ScriptedSource([{}]), StepClock(), store, market_client=FakeMarket())
    assert engine.plans_payload()["plans"] == []

    target.write_text('{"version": 99, "plans": []}', encoding="utf-8")
    second = Engine(config(), ScriptedSource([{}]), StepClock(), store, market_client=FakeMarket())
    assert second.plans_payload()["plans"] == []


def test_persistence_history_is_capped_at_30(tmp_path):
    clock = StepClock()
    steps = []
    for index in range(40):
        steps.append(step(16.0 if index % 2 == 0 else 15.0))
    engine, store = build(
        tmp_path,
        overrides={"rules": []},
        steps=steps,
        clock=clock,
    )
    engine.upsert_plan(p(stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]))
    for _ in range(40):
        clock.advance(3)
        engine.poll()
    payload = engine.plan_payload("plan-1")
    assert len(payload["history"]) <= 30
    second = Engine(
        engine.config,
        ScriptedSource([{}]),
        StepClock(),
        FileStore(store.out_dir),
        market_client=FakeMarket(),
    )
    assert len(second.plan_payload("plan-1")["history"]) <= 30


def test_plan_upsert_persistence_error_is_reported(tmp_path, monkeypatch):
    engine, _ = build(tmp_path)
    def boom():
        raise OSError("disk full")
    monkeypatch.setattr(engine, "_save_plans", boom)
    with pytest.raises(PlanError) as excinfo:
        engine.upsert_plan(p())
    assert excinfo.value.code == "persistence_error"
    assert engine.plans_payload()["plans"] == []


def test_upsert_reactivates_expired_plan_when_expiry_moves_forward(tmp_path):
    clock = StepClock()
    engine, _ = build(tmp_path, overrides={"rules": []}, clock=clock)
    engine.upsert_plan(p(expires_at="2026-11-03T09:31:00+08:00"))
    clock.advance(120)
    engine.poll()
    assert engine.plan_payload("plan-1")["state"] == "expired"
    engine.upsert_plan(p(expires_at="2026-11-03T15:00:00+08:00"))
    payload = engine.plan_payload("plan-1")
    assert payload["state"] == "observe"
    assert payload["active"] is True
    assert payload["history"][-1]["from"] == "expired"
