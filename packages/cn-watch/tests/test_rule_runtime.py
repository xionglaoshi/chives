from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from cn_watch.calendar import WeekdayCalendar
from cn_watch.config import ConfigError, load_config, parse_config
from cn_watch.engine import Engine, RuleError
from cn_watch.storage import FileStore
from support import BASE_CONFIG, DAY0, StepClock, config, quote

ALL_CODES = ["002553.SZ", "601099.SH"]


class MappingSource:
    def __init__(self, quotes=None):
        self.quotes = quotes if quotes is not None else {
            code: quote(code=code, name=f"名称{code[:6]}", price=15.0, prev_close=15.0)
            for code in ALL_CODES
        }
        self.calls: list[list[str]] = []

    def fetch(self, codes, now):
        self.calls.append(list(codes))
        result = {}
        for code in codes:
            original = self.quotes.get(code)
            if original is None:
                continue
            result[code] = quote(
                code=code,
                name=original.name,
                price=original.price,
                prev_close=original.prev_close,
                exch=now,
            )
        return result


def build(tmp_path: Path, *, overrides=None, source=None, store=None) -> tuple[Engine, FileStore]:
    cfg = config(**(overrides or {}))
    out = store or FileStore(tmp_path / "data")
    return Engine(cfg, source or MappingSource(), StepClock(), out), out


def rows(engine: Engine) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in engine.rules_payload()["rules"]}


def rule_dict(**fields: Any) -> dict[str, Any]:
    return dict(fields)


def test_upsert_create_override_replace(tmp_path: Path):
    engine, store = build(tmp_path)
    assert rows(engine)["pct_up_3"]["source"] == "config"

    created = engine.upsert_rule(
        rule_dict(id="new_rule", type="pct_change", direction="up", threshold_pct=2.0),
        actor="tester",
    )
    assert created["status"] == "created"
    assert created["before"] is None
    assert created["after"]["source"] == "runtime"
    assert rows(engine)["new_rule"]["source"] == "runtime"

    replaced = engine.upsert_rule(
        rule_dict(id="new_rule", type="pct_change", direction="up", threshold_pct=4.0),
        actor="tester",
    )
    assert replaced["status"] == "replaced"
    assert replaced["before"]["threshold_pct"] == 2.0
    assert rows(engine)["new_rule"]["threshold_pct"] == 4.0
    assert len([row for row in engine.rules_payload()["rules"] if row["id"] == "new_rule"]) == 1

    overridden = engine.upsert_rule(
        rule_dict(id="pct_up_3", type="pct_change", direction="up", threshold_pct=1.5),
        actor="tester",
    )
    assert overridden["status"] == "override"
    assert overridden["before"]["source"] == "config"
    assert overridden["before"]["threshold_pct"] == 3.0
    assert rows(engine)["pct_up_3"]["source"] == "override"
    assert rows(engine)["pct_up_3"]["threshold_pct"] == 1.5
    runtime_data = json.loads((store.out_dir / "rules.runtime.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in runtime_data["rules"]] == ["new_rule"]
    assert runtime_data["overrides"]["pct_up_3"]["rule"]["threshold_pct"] == 1.5


def test_config_rule_remove_is_a_disabled_override(tmp_path: Path):
    engine, _ = build(tmp_path)
    result = engine.remove_rule("pct_up_3", actor="tester")
    assert result["status"] == "disabled"
    assert result["after"]["source"] == "override"
    assert result["after"]["disabled"] is True
    assert result["after"]["threshold_pct"] == 3.0
    assert rows(engine)["pct_up_3"]["disabled"] is True
    assert engine.rules_payload()["enabled_count"] == 0

    again = engine.remove_rule("pct_up_3")
    assert again["status"] == "already_disabled"
    assert len(engine.rule_history()["history"]) == 1


def test_revert_restores_config_rule_and_deletes_runtime_rule(tmp_path: Path):
    engine, _ = build(tmp_path)
    engine.upsert_rule(
        rule_dict(id="pct_up_3", type="pct_change", direction="up", threshold_pct=2.0)
    )
    reverted = engine.revert_rule("pct_up_3")
    assert reverted["status"] == "reverted"
    assert reverted["after"]["source"] == "config"
    assert reverted["after"]["threshold_pct"] == 3.0

    engine.upsert_rule(
        rule_dict(id="new_rule", type="pct_change", direction="up", threshold_pct=2.0)
    )
    gone = engine.revert_rule("new_rule")
    assert gone["status"] == "reverted"
    assert gone["after"] is None
    assert "new_rule" not in rows(engine)

    unchanged = engine.revert_rule("pct_up_3")
    assert unchanged["status"] == "unchanged"
    assert len(engine.rule_history()["history"]) == 4

    with pytest.raises(RuleError) as excinfo:
        engine.revert_rule("missing")
    assert excinfo.value.code == "rule_not_found"


def test_audit_history_has_before_after_and_sanitized_actor(tmp_path: Path):
    engine, _ = build(tmp_path)
    engine.upsert_rule(
        rule_dict(id="new_rule", type="pct_change", direction="up", threshold_pct=2.0),
        actor="  agent\n<script>  ",
    )
    engine.remove_rule("pct_up_3", actor="human")
    engine.revert_rule("pct_up_3", actor="x" * 200)
    history = engine.rule_history(limit=10)["history"]
    assert [item["action"] for item in history] == ["revert", "remove", "upsert"]
    assert set(history[0]) == {"ts", "action", "rule_id", "before", "after", "actor"}
    assert history[0]["actor"] == "x" * 64
    assert history[1]["actor"] == "human"
    assert history[2]["actor"] == "agentscript"
    assert history[2]["before"] is None
    assert history[2]["after"]["threshold_pct"] == 2.0
    assert history[1]["after"]["disabled"] is True
    assert history[0]["after"]["source"] == "config"
    assert engine.rule_history(limit=1)["count"] == 1


def test_persistence_and_restart_merge(tmp_path: Path):
    first, store = build(tmp_path)
    first.upsert_rule(
        rule_dict(id="new_rule", type="pct_change", direction="up", threshold_pct=2.0)
    )
    first.upsert_rule(
        rule_dict(id="pct_up_3", type="pct_change", direction="up", threshold_pct=1.5)
    )
    first.remove_rule("pct_up_3")
    first.upsert_rule(
        rule_dict(id="pct_up_3", type="pct_change", direction="up", threshold_pct=1.5)
    )

    data = json.loads((store.out_dir / "rules.runtime.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert [item["id"] for item in data["rules"]] == ["new_rule"]
    assert data["overrides"]["pct_up_3"]["rule"]["threshold_pct"] == 1.5
    assert len(data["history"]) == 4

    second = Engine(
        first.config,
        MappingSource(),
        StepClock(),
        FileStore(store.out_dir),
    )
    second_rows = rows(second)
    assert second_rows["new_rule"]["source"] == "runtime"
    assert second_rows["pct_up_3"]["source"] == "override"
    assert second_rows["pct_up_3"]["threshold_pct"] == 1.5
    assert len(second.rule_history()["history"]) == 4


def test_corrupt_runtime_rules_file_is_empty_and_logged(tmp_path: Path, caplog):
    store = FileStore(tmp_path / "data")
    store.out_dir.mkdir(parents=True, exist_ok=True)
    (store.out_dir / "rules.runtime.json").write_text("{{{ not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="cn_watch.rule_store"):
        engine = Engine(config(), MappingSource(), StepClock(), store)
    assert list(rows(engine)) == ["pct_up_3"]
    assert any("已损坏" in record.getMessage() for record in caplog.records)
    engine.upsert_rule(
        rule_dict(id="new_rule", type="pct_change", direction="up", threshold_pct=2.0)
    )
    assert "new_rule" in rows(engine)


def test_invalid_stored_rule_is_skipped(tmp_path: Path, caplog):
    store = FileStore(tmp_path / "data")
    store.out_dir.mkdir(parents=True, exist_ok=True)
    (store.out_dir / "rules.runtime.json").write_text(
        json.dumps(
            {
                "rules": [
                    {"id": "bad type", "type": "pct_change", "direction": "up", "threshold_pct": 1},
                    {"id": "too_big", "type": "pct_change", "direction": "up", "threshold_pct": 99},
                ]
            }
        ),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="cn_watch.rule_store"):
        engine = Engine(config(), MappingSource(), StepClock(), store)
    assert list(rows(engine)) == ["pct_up_3"]
    assert any("已忽略" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    ("rule", "field"),
    [
        ({"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 0.09}, "threshold_pct"),
        ({"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 25.01}, "threshold_pct"),
        ({"id": "r", "type": "vwap_deviation", "threshold_pct": 0.05}, "threshold_pct"),
        ({"id": "r", "type": "vwap_deviation", "threshold_pct": 26}, "threshold_pct"),
        ({"id": "r", "type": "limit_proximity", "side": "up", "within_pct": 0.04}, "within_pct"),
        ({"id": "r", "type": "limit_proximity", "side": "up", "within_pct": 10.01}, "within_pct"),
        ({"id": "r", "type": "volume_surge", "window_seconds": 60, "multiple": 1.1}, "multiple"),
        ({"id": "r", "type": "volume_surge", "window_seconds": 60, "multiple": 51}, "multiple"),
        ({"id": "r", "type": "price_cross", "direction": "up", "level": 0}, "level"),
        ({"id": "r", "type": "price_cross", "direction": "up", "level": -1}, "level"),
    ],
)
def test_out_of_bounds_rules_are_rejected_without_state_change(tmp_path: Path, rule, field):
    engine, _ = build(tmp_path)
    before = json.dumps(engine.rules_payload(), sort_keys=True)
    with pytest.raises(RuleError) as excinfo:
        engine.upsert_rule(rule)
    assert excinfo.value.code == "out_of_bounds"
    assert excinfo.value.field == field
    assert excinfo.value.minimum is not None
    assert json.dumps(engine.rules_payload(), sort_keys=True) == before


@pytest.mark.parametrize(
    "rule",
    [
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 0.1},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 25},
        {"id": "r", "type": "vwap_deviation", "threshold_pct": 0.1, "min_amount_yuan": 0},
        {"id": "r", "type": "vwap_deviation", "threshold_pct": 25, "min_amount_yuan": 0},
        {"id": "r", "type": "limit_proximity", "side": "up", "within_pct": 0.05},
        {"id": "r", "type": "limit_proximity", "side": "up", "within_pct": 10},
        {"id": "r", "type": "volume_surge", "window_seconds": 60, "multiple": 1.2, "min_window_amount_yuan": 0},
        {"id": "r", "type": "volume_surge", "window_seconds": 60, "multiple": 50, "min_window_amount_yuan": 0},
        {"id": "r", "type": "price_cross", "direction": "up", "level": 0.01},
    ],
)
def test_inclusive_boundaries_are_accepted(tmp_path: Path, rule):
    engine, _ = build(tmp_path)
    result = engine.upsert_rule(rule)
    assert result["status"] == "created"


@pytest.mark.parametrize(
    "rule",
    [
        "not a dict",
        {"id": "r", "type": "magic", "threshold_pct": 1},
        {"id": "../etc", "type": "pct_change", "direction": "up", "threshold_pct": 1},
        {"id": "a" * 41, "type": "pct_change", "direction": "up", "threshold_pct": 1},
        {"id": "r", "type": "pct_change", "direction": "sideways", "threshold_pct": 1},
        {"id": "r", "type": "pct_change", "direction": "up"},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": "3"},
        {"id": "r", "type": "limit_proximity", "within_pct": 1},
        {"id": "r", "type": "price_cross", "direction": "up"},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": []},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": ["601099", "601099.SH"]},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": ["399975"]},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": "601099"},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": [None]},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": ["601099"], "codes": ["601099"]},
        {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": True},
    ],
)
def test_invalid_rule_payloads_are_rejected(tmp_path: Path, rule):
    engine, _ = build(tmp_path)
    with pytest.raises(RuleError) as excinfo:
        engine.upsert_rule(rule)
    assert excinfo.value.code in {"invalid_rule", "invalid_id"}
    assert list(rows(engine)) == ["pct_up_3"]


def test_max_rules_limit_counts_enabled_rules(tmp_path: Path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_rules": 2}})
    engine.upsert_rule(
        rule_dict(id="r2", type="pct_change", direction="up", threshold_pct=2.0)
    )
    with pytest.raises(RuleError) as excinfo:
        engine.upsert_rule(
            rule_dict(id="r3", type="pct_change", direction="up", threshold_pct=2.0)
        )
    assert excinfo.value.code == "rules_full"
    assert set(rows(engine)) == {"pct_up_3", "r2"}

    engine.remove_rule("r2")
    engine.upsert_rule(
        rule_dict(id="r3", type="pct_change", direction="up", threshold_pct=2.0)
    )
    assert "r3" in rows(engine)


def test_config_rejects_more_rules_than_max_rules():
    rules = [
        {"id": f"r{i}", "type": "pct_change", "direction": "up", "threshold_pct": 1.0}
        for i in range(3)
    ]
    with pytest.raises(ConfigError):
        parse_config({**BASE_CONFIG, "rules": rules, "limits": {"max_rules": 2}})


def test_cooldown_reset_only_for_the_changed_rule(tmp_path: Path):
    source = MappingSource({"002553.SZ": quote(price=15.47, prev_close=15.0)})
    engine, _ = build(
        tmp_path,
        overrides={
            "rules": [
                {"id": "up2", "type": "pct_change", "direction": "up", "threshold_pct": 2.0},
                {"id": "up3", "type": "pct_change", "direction": "up", "threshold_pct": 3.0},
            ]
        },
        source=source,
    )
    engine.poll()
    before = {
        row["rule_id"]: (row["armed"], row["fired_count"])
        for row in engine.state_dict()["rules"]
    }
    assert before == {"up2": (False, 1), "up3": (False, 1)}

    engine.upsert_rule(
        rule_dict(id="up2", type="pct_change", direction="up", threshold_pct=1.5)
    )
    after_upsert = {
        (row["code"], row["rule_id"]): (row["armed"], row["fired_count"])
        for row in engine.state_dict()["rules"]
    }
    assert after_upsert[("002553.SZ", "up2")] == (True, 0)
    assert after_upsert[("002553.SZ", "up3")] == (False, 1)

    engine.clock.advance(3)
    engine.poll()
    fired = engine.state_dict()["rules"]
    assert {row["rule_id"]: row["fired_count"] for row in fired} == {"up2": 1, "up3": 1}


def test_changing_symbols_resets_only_that_rule(tmp_path: Path):
    source = MappingSource({code: quote(code=code, price=15.47) for code in ALL_CODES})
    engine, _ = build(tmp_path, overrides={"watchlist": ALL_CODES}, source=source)
    engine.poll()
    assert len(engine.state_dict()["rules"]) == 2

    engine.upsert_rule(
        rule_dict(
            id="pct_up_3",
            type="pct_change",
            direction="up",
            threshold_pct=3.0,
            symbols=["601099.SH"],
        )
    )
    table = {
        (row["code"], row["rule_id"]): (row["armed"], row["fired_count"])
        for row in engine.state_dict()["rules"]
    }
    assert table == {("601099.SH", "pct_up_3"): (True, 0)}

    engine.clock.advance(3)
    engine.poll()
    table = {
        (row["code"], row["rule_id"]): (row["armed"], row["fired_count"])
        for row in engine.state_dict()["rules"]
    }
    assert table == {("601099.SH", "pct_up_3"): (False, 1)}


def test_runtime_rule_and_t77_runtime_symbol_combination(tmp_path: Path):
    source = MappingSource(
        {
            "002553.SZ": quote(price=15.0),
            "601099.SH": quote(code="601099.SH", price=10.2, prev_close=10.0),
        }
    )
    engine, _ = build(tmp_path, source=source)
    engine.add_symbol("601099")
    engine.upsert_rule(
        rule_dict(
            id="new_scoped",
            type="pct_change",
            direction="up",
            threshold_pct=1.0,
            symbols=["601099"],
        )
    )
    assert rows(engine)["new_scoped"]["symbols"] == ["601099.SH"]
    engine.poll()
    fired = {(item["code"], item["rule_id"]) for item in engine.alerts()["alerts"]}
    assert ("601099.SH", "new_scoped") in fired
    assert ("002553.SZ", "new_scoped") not in fired


def test_runtime_rule_applies_to_later_added_symbol(tmp_path: Path):
    source = MappingSource(
        {
            "002553.SZ": quote(price=15.0),
            "601099.SH": quote(code="601099.SH", price=10.2, prev_close=10.0),
        }
    )
    engine, _ = build(tmp_path, source=source)
    engine.upsert_rule(
        rule_dict(id="global_up", type="pct_change", direction="up", threshold_pct=1.0)
    )
    engine.poll()
    assert ("002553.SZ", "global_up") not in {
        (item["code"], item["rule_id"]) for item in engine.alerts()["alerts"]
    }
    engine.add_symbol("601099")
    engine.poll()
    assert ("601099.SH", "global_up") in {
        (item["code"], item["rule_id"]) for item in engine.alerts()["alerts"]
    }


def test_concurrent_upserts_are_serialized(tmp_path: Path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_rules": 20}})
    errors: list[str] = []

    def upsert(index: int) -> None:
        try:
            engine.upsert_rule(
                rule_dict(
                    id=f"r{index}",
                    type="pct_change",
                    direction="up",
                    threshold_pct=1.0 + index / 10,
                )
            )
        except RuleError as exc:
            errors.append(exc.code)

    threads = [threading.Thread(target=upsert, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert {f"r{index}" for index in range(6)} <= set(rows(engine))
    assert len(engine.rule_history(limit=100)["history"]) == 6


class AlwaysSource:
    def fetch(self, codes, now):
        return {
            code: quote(code=code, price=15.47, prev_close=15.0, exch=now)
            for code in codes
        }


def write_config(path: Path, overrides: dict[str, Any], serial: int) -> None:
    raw = {**BASE_CONFIG, **overrides}
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    stamp = 1_700_000_000_000_000_000 + serial * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


def test_config_hot_reload_success_and_rules_apply(tmp_path: Path):
    path = tmp_path / "watch.yaml"
    write_config(path, {"rules": [{"id": "up4", "type": "pct_change", "direction": "up", "threshold_pct": 4.0}]}, 1)
    cfg = load_config(path)
    clock = StepClock()
    engine = Engine(
        cfg,
        AlwaysSource(),
        clock,
        FileStore(tmp_path / "data"),
        config_path=path,
    )
    engine.poll()
    assert engine.alerts()["alerts"] == []

    write_config(
        path,
        {
            "rules": [{"id": "up1", "type": "pct_change", "direction": "up", "threshold_pct": 1.0}],
            "alerts": {"cooldown_seconds": 10, "rearm_pct": 0.1},
        },
        2,
    )
    clock.advance(3)
    engine.poll()
    assert [item["rule_id"] for item in engine.alerts()["alerts"]] == ["up1"]
    assert engine.health_dict()["config_reload_error"] is None
    assert [row["id"] for row in engine.rules_payload()["rules"]] == ["up1"]
    assert engine.config.alerts.cooldown_seconds == 10


def test_config_hot_reload_failure_keeps_old_config_and_reports(tmp_path: Path, caplog):
    path = tmp_path / "watch.yaml"
    write_config(path, {"rules": [{"id": "up3", "type": "pct_change", "direction": "up", "threshold_pct": 3.0}]}, 1)
    cfg = load_config(path)
    clock = StepClock()
    engine = Engine(
        cfg,
        AlwaysSource(),
        clock,
        FileStore(tmp_path / "data"),
        config_path=path,
    )
    engine.poll()

    path.write_text("rules: [{id: broken, type: pct_change}]\n", encoding="utf-8")
    os.utime(path, ns=(1_700_000_000_000_000_000 + 2_000_000_000,) * 2)
    with caplog.at_level(logging.WARNING, logger="cn_watch.engine"):
        clock.advance(3)
        engine.poll()
    health = engine.health_dict()
    assert health["status"] in {"ok", "degraded", "down", "stale"}
    assert health["config_reload_error"]
    assert [row["id"] for row in engine.rules_payload()["rules"]] == ["up3"]
    assert any("config_reload result=error" in record.getMessage() for record in caplog.records)

    write_config(
        path,
        {"rules": [{"id": "up2", "type": "pct_change", "direction": "up", "threshold_pct": 2.0}]},
        3,
    )
    clock.advance(3)
    engine.poll()
    assert engine.health_dict()["config_reload_error"] is None
    assert [row["id"] for row in engine.rules_payload()["rules"]] == ["up2"]


def test_config_hot_reload_updates_watchlist_and_keeps_runtime_symbols(tmp_path: Path):
    path = tmp_path / "watch.yaml"
    write_config(path, {"watchlist": ["002553.SZ"]}, 1)
    cfg = load_config(path)
    clock = StepClock()
    engine = Engine(
        cfg,
        AlwaysSource(),
        clock,
        FileStore(tmp_path / "data"),
        config_path=path,
    )
    engine.poll()
    engine.add_symbol("601099")
    assert [row["code"] for row in engine.watchlist_dict()["watchlist"]] == [
        "002553.SZ",
        "601099.SH",
    ]

    write_config(path, {"watchlist": ["600000.SH"]}, 2)
    clock.advance(3)
    engine.poll()
    entries = [(row["code"], row["source"]) for row in engine.watchlist_dict()["watchlist"]]
    assert entries == [("600000.SH", "config"), ("601099.SH", "runtime")]


def test_config_calendar_and_api_changes_only_warn(tmp_path: Path, caplog):
    path = tmp_path / "watch.yaml"
    write_config(path, {}, 1)
    cfg = load_config(path)
    calendar = WeekdayCalendar()
    clock = StepClock()
    engine = Engine(
        cfg,
        AlwaysSource(),
        clock,
        FileStore(tmp_path / "data"),
        calendar=calendar,
        config_path=path,
    )
    engine.poll()
    write_config(
        path,
        {
            "api": {"host": "127.0.0.1", "port": 9999},
            "calendar": {"source": "weekdays"},
            "rules": [{"id": "up1", "type": "pct_change", "direction": "up", "threshold_pct": 1.0}],
        },
        2,
    )
    with caplog.at_level(logging.WARNING, logger="cn_watch.engine"):
        clock.advance(3)
        engine.poll()
    messages = [record.getMessage() for record in caplog.records]
    assert any("api.host/port" in item and "重启" in item for item in messages)
    assert engine.calendar is calendar
    assert [row["id"] for row in engine.rules_payload()["rules"]] == ["up1"]


def test_load_config_attaches_path_for_hot_reload(tmp_path: Path):
    path = tmp_path / "watch.yaml"
    write_config(path, {"rules": [{"id": "up3", "type": "pct_change", "direction": "up", "threshold_pct": 3.0}]}, 1)
    cfg = load_config(path)
    assert cfg.config_path == path
    engine = Engine(cfg, AlwaysSource(), StepClock(), FileStore(tmp_path / "data"))
    clock = engine.clock
    engine.poll()
    write_config(
        path,
        {"rules": [{"id": "up2", "type": "pct_change", "direction": "up", "threshold_pct": 2.0}]},
        2,
    )
    clock.advance(3)
    engine.poll()
    assert [row["id"] for row in engine.rules_payload()["rules"]] == ["up2"]


def test_config_calendar_change_simulating_holiday_needs_restart(tmp_path: Path, caplog):
    from cn_watch.calendar import build_calendar

    first_dates = tmp_path / "dates_first.json"
    second_dates = tmp_path / "dates_second.json"
    first_dates.write_text('["2026-11-03"]', encoding="utf-8")
    second_dates.write_text('["2026-11-04"]', encoding="utf-8")
    path = tmp_path / "watch.yaml"
    write_config(
        path,
        {"calendar": {"source": "file", "file": str(first_dates)}},
        1,
    )
    cfg = load_config(path)
    calendar = build_calendar(cfg.calendar, tmp_path / "data")
    assert calendar.is_trading_day(DAY0)
    clock = StepClock()
    engine = Engine(
        cfg,
        AlwaysSource(),
        clock,
        FileStore(tmp_path / "data"),
        calendar=calendar,
    )
    engine.poll()

    write_config(
        path,
        {"calendar": {"source": "file", "file": str(second_dates)}},
        2,
    )
    with caplog.at_level(logging.WARNING, logger="cn_watch.engine"):
        clock.advance(3)
        engine.poll()
    messages = [record.getMessage() for record in caplog.records]
    assert any("calendar" in item and "重启" in item for item in messages)
    assert engine.calendar is calendar
    assert engine.calendar.is_trading_day(DAY0)
    assert engine.health_dict()["trading_day"] is True


def test_config_reload_applies_active_windows_and_polling(tmp_path: Path):
    path = tmp_path / "watch.yaml"
    write_config(
        path,
        {
            "active_windows": ["11:00:00-12:00:00"],
            "polling": dict(BASE_CONFIG["polling"], base_seconds=9.0, idle_seconds=30),
            "rules": [{"id": "up1", "type": "pct_change", "direction": "up", "threshold_pct": 1.0}],
        },
        1,
    )
    cfg = load_config(path)
    clock = StepClock()
    engine = Engine(cfg, AlwaysSource(), clock, FileStore(tmp_path / "data"))
    engine.poll()
    assert engine.state_dict()["session"] == "pre_open"
    assert engine.alerts()["alerts"] == []

    write_config(
        path,
        {
            "active_windows": ["09:00:00-10:00:00"],
            "polling": dict(BASE_CONFIG["polling"], base_seconds=7.0, idle_seconds=30),
            "rules": [{"id": "up1", "type": "pct_change", "direction": "up", "threshold_pct": 1.0}],
        },
        2,
    )
    clock.advance(3)
    engine.poll()
    state = engine.state_dict()
    assert state["session"] == "open"
    assert [item["rule_id"] for item in engine.alerts()["alerts"]] == ["up1"]
    assert state["next_interval"] == 7.0
