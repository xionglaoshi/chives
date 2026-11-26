from __future__ import annotations

from pathlib import Path

import pytest

from chives_compass.config import (
    ConfigError,
    load_config,
    load_watchlist,
    parse_config,
)

BASE = {
    "api": {"host": "127.0.0.1", "port": 8866},
    "polling": {"index_seconds": 3, "timeout_seconds": 5},
    "limits": {"max_per_minute": {"gateway": 100}},
    "calendar": {"source": "weekdays"},
    "rules": {"R1": {"enabled": False}},
}


def test_defaults_and_rule_merge():
    cfg = parse_config(BASE)
    assert cfg.api.port == 8866
    assert cfg.rule("R1").enabled is False
    assert cfg.rule("R1").params["change_pct_max"] == -1.0
    assert cfg.rule("R2").enabled is True
    assert [rule.id for rule in cfg.rules] == ["R1", "R2", "R3", "R4", "R5", "R6"]


def test_non_loopback_host_rejected():
    with pytest.raises(ConfigError):
        parse_config({"api": {"host": "0.0.0.0", "port": 8866}})


def test_bad_port_rejected():
    with pytest.raises(ConfigError):
        parse_config({"api": {"host": "127.0.0.1", "port": 70000}})


def test_timeout_upper_bound():
    with pytest.raises(ConfigError):
        parse_config({"polling": {"timeout_seconds": 6}})


def test_timeout_five_seconds_allowed():
    assert parse_config({"polling": {"timeout_seconds": 5}}).polling.timeout_seconds == 5.0


def test_stale_after_unknown_key():
    with pytest.raises(ConfigError):
        parse_config({"polling": {"stale_after_seconds": {"foo": 1}}})


def test_concurrency_limited_to_two():
    with pytest.raises(ConfigError):
        parse_config({"limits": {"max_concurrency": 3}})


def test_unknown_rule_rejected():
    with pytest.raises(ConfigError):
        parse_config({"rules": {"R9": {}}})


def test_unknown_rule_param_rejected():
    with pytest.raises(ConfigError):
        parse_config({"rules": {"R1": {"params": {"nope": 1}}}})


@pytest.mark.parametrize(
    "rule_id,param,value",
    [
        ("R1", "change_pct_max", -1000),
        ("R2", "up_ratio_max", 2.0),
        ("R3", "rank_max", 99),
        ("R4", "zt_increase_min", -1),
        ("R5", "buffer_pct", -1),
        ("R6", "volume_ratio_min", -1),
    ],
)
def test_rule_param_ranges(rule_id, param, value):
    with pytest.raises(ConfigError):
        parse_config({"rules": {rule_id: {"params": {param: value}}}})


def test_confirm_must_be_positive():
    with pytest.raises(ConfigError):
        parse_config({"rules": {"R3": {"confirm": 0}}})


def test_level_whitelist():
    with pytest.raises(ConfigError):
        parse_config({"rules": {"R3": {"level": "L9"}}})


def test_unknown_rule_key_rejected():
    with pytest.raises(ConfigError):
        parse_config({"rules": {"R3": {"foo": 1}}})


def test_calendar_file_required():
    with pytest.raises(ConfigError):
        parse_config({"calendar": {"source": "file"}})


def test_relative_paths_resolve_against_base(tmp_path):
    cfg = parse_config(
        {"runtime": {"db_path": "data/m.db"}, "watchlist_file": "config/watch.yaml"},
        base_dir=tmp_path,
    )
    assert cfg.runtime.db_path == tmp_path / "data/m.db"
    assert cfg.watchlist_file == tmp_path / "config/watch.yaml"


def test_load_config_roundtrip(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(
        "api: {host: 127.0.0.1, port: 8799}\n"
        "calendar: {source: weekdays}\n"
        "rules:\n  R1:\n    enabled: false\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.api.port == 8799
    assert cfg.config_path == path
    assert cfg.rule("R1").enabled is False


def test_load_config_rejects_empty(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_load_watchlist_reads_cn_watch_file(tmp_path):
    path = tmp_path / "watch.yaml"
    path.write_text(
        "watchlist: [002553.SZ, 601099.SH, 002553.SZ]\n"
        "rules:\n  - {id: x, type: pct_change}\n",
        encoding="utf-8",
    )
    assert load_watchlist(path) == ("002553.SZ", "601099.SH")


def test_load_watchlist_missing_file_is_empty(tmp_path):
    assert load_watchlist(tmp_path / "nope.yaml") == ()


def test_load_watchlist_bad_yaml_is_empty(tmp_path):
    path = tmp_path / "watch.yaml"
    path.write_text("watchlist: [1, 2\n", encoding="utf-8")
    assert load_watchlist(path) == ()


def test_load_watchlist_caps_at_limit(tmp_path):
    codes = ", ".join(f"{index:06d}.SZ" for index in range(1, 90))
    path = tmp_path / "watch.yaml"
    path.write_text(f"watchlist: [{codes}]\n", encoding="utf-8")
    assert len(load_watchlist(path)) == 80


def test_config_rule_as_dict_shape():
    cfg = parse_config(BASE)
    payload = cfg.rule("R1").as_dict()
    assert set(payload) == {"id", "name", "enabled", "params", "confirm", "cooldown_minutes", "level"}
