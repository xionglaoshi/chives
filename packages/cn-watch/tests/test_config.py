from __future__ import annotations

import copy
import logging
from pathlib import Path

import pytest
import yaml

from cn_watch.config import ConfigError, load_config, normalize_code, parse_config
from support import BASE_CONFIG, DAY0


def raw(**overrides):
    value = copy.deepcopy(BASE_CONFIG)
    value.update(overrides)
    return value


def test_valid_config_and_loopback_localhost():
    cfg = parse_config(raw(api={"host": "localhost", "port": 9000}))
    assert cfg.api.host == "localhost"
    assert cfg.watchlist == ("002553.SZ",)
    assert cfg.active_at(DAY0)
    assert cfg.gateway_url == "http://127.0.0.1:8868"


def test_gateway_url_is_configurable_on_loopback():
    cfg = parse_config(raw(gateway_url="http://localhost:8799/"))
    assert cfg.gateway_url == "http://localhost:8799"


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com:8868",
        "ftp://127.0.0.1:8868",
        "http://user:pass@127.0.0.1:8868",
        "http://127.0.0.1:8868/v1/call?x=1",
        "not-a-url",
    ],
)
def test_invalid_gateway_url_rejected(value):
    with pytest.raises(ConfigError):
        parse_config(raw(gateway_url=value))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("002553.SZ", "002553.SZ"),
        ("002553", "002553.SZ"),
        ("600000", "600000.SH"),
        ("900901", "900901.SH"),
        ("300750.sz", "300750.SZ"),
        (2553, "002553.SZ"),
        (300750, "300750.SZ"),
    ],
)
def test_normalize_code(value, expected):
    assert normalize_code(value) == expected


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["rules"][0].update(type="magic"),
        lambda c: c["rules"][0].pop("threshold_pct"),
        lambda c: c["rules"][0].update(threshold_pct=-3.0),
        lambda c: c["rules"][0].update(threshold_pct=0),
        lambda c: c["rules"].append(copy.deepcopy(c["rules"][0])),
        lambda c: c.update(watchlist=["ABC123"]),
        lambda c: c.update(watchlist=["600000.XX"]),
        lambda c: c.update(watchlist=[f"{600000 + i}.SH" for i in range(81)]),
        lambda c: c.update(api={"host": "0.0.0.0", "port": 8865}),
        lambda c: c.update(active_windows=["9点-11点"]),
        lambda c: c.update(active_windows=["11:30:00-09:30:00"]),
        lambda c: c["polling"].update(base_seconds=0),
        lambda c: c["polling"].update(backoff_seconds=[]),
        lambda c: c["polling"].update(stale_after_seconds=-1),
        lambda c: c["polling"].update(jitter_pct=101),
        lambda c: c["alerts"].update(cooldown_seconds=-1),
        lambda c: c["api"].update(port=0),
        lambda c: c["api"].update(port=70000),
        lambda c: c["rules"][0].update(direction="sideways"),
        lambda c: c["rules"][0].update(codes=[]),
    ],
)
def test_invalid_configs_raise(mutate):
    value = raw()
    mutate(value)
    with pytest.raises(ConfigError):
        parse_config(value)


@pytest.mark.parametrize(
    "rule",
    [
        {"id": "x", "type": "vwap_deviation", "threshold_pct": 2.0},
        {"id": "x", "type": "vwap_deviation", "threshold_pct": 2.0, "min_amount_yuan": -1},
        {"id": "x", "type": "limit_proximity", "side": "up"},
        {"id": "x", "type": "limit_proximity", "side": "left", "within_pct": 0.5},
        {"id": "x", "type": "price_cross", "direction": "up"},
        {"id": "x", "type": "price_cross", "direction": "down", "level": 0},
        {"id": "x", "type": "volume_surge", "window_seconds": 60, "multiple": 3.0},
        {"id": "x", "type": "volume_surge", "window_seconds": 0, "multiple": 3.0, "min_window_amount_yuan": 1},
        {"id": "", "type": "pct_change", "direction": "up", "threshold_pct": 1.0},
    ],
)
def test_rule_specific_errors(rule):
    with pytest.raises(ConfigError):
        parse_config(raw(rules=[rule]))


def test_rules_can_be_scoped_to_codes():
    cfg = parse_config(
        raw(
            rules=[
                {
                    "id": "only_one",
                    "type": "pct_change",
                    "direction": "up",
                    "threshold_pct": 1.0,
                    "codes": ["600000"],
                }
            ]
        )
    )
    assert cfg.rules[0].codes == ("600000.SH",)
    assert not cfg.rules[0].applies_to("002553.SZ")


def test_load_config_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_bad_yaml(tmp_path: Path):
    target = tmp_path / "bad.yaml"
    target.write_text("watchlist: [", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(target)


def test_load_config_empty(tmp_path: Path):
    target = tmp_path / "empty.yaml"
    target.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(target)


def test_load_config_roundtrip(tmp_path: Path):
    target = tmp_path / "ok.yaml"
    target.write_text(yaml.safe_dump(BASE_CONFIG, allow_unicode=True), encoding="utf-8")
    assert load_config(target).watchlist == ("002553.SZ",)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("512880", "512880.SH"),
        ("512880.SH", "512880.SH"),
        ("510300", "510300.SH"),
        ("159915", "159915.SZ"),
        ("159915.SZ", "159915.SZ"),
    ],
)
def test_etf_codes_are_normalized(value, expected):
    assert normalize_code(value) == expected


@pytest.mark.parametrize("value", ["399975", "399975.SZ", "000300.SH", "999999"])
def test_index_codes_are_rejected_in_config(value):
    with pytest.raises(ConfigError):
        normalize_code(value)
    with pytest.raises(ConfigError):
        parse_config(raw(watchlist=[value]))


def test_symbols_are_normalized_and_exposed():
    cfg = parse_config(
        raw(
            watchlist=["002553.SZ", "601099", "512880"],
            rules=[
                {
                    "id": "near_up_wide",
                    "type": "limit_proximity",
                    "side": "up",
                    "within_pct": 1.5,
                    "symbols": ["601099", "512880"],
                }
            ],
        )
    )
    rule = cfg.rules[0]
    assert rule.symbols == ("601099.SH", "512880.SH")
    assert rule.codes is None
    assert rule.as_dict().get("codes") is None
    assert rule.applies_to("601099.SH")
    assert not rule.applies_to("002553.SZ")
    assert rule.as_dict()["symbols"] == ["601099.SH", "512880.SH"]


def test_symbols_default_to_none_for_all_symbols():
    cfg = parse_config(raw())
    rule = cfg.rules[0]
    assert rule.symbols is None
    assert rule.applies_to("002553.SZ")
    assert rule.applies_to("512880.SH")
    assert rule.as_dict()["symbols"] is None


def test_multiple_rules_of_the_same_type_can_coexist():
    cfg = parse_config(
        raw(
            watchlist=["002553.SZ", "601099.SH"],
            rules=[
                {
                    "id": "near_up_wide",
                    "type": "limit_proximity",
                    "side": "up",
                    "within_pct": 1.5,
                    "symbols": ["601099.SH"],
                },
                {
                    "id": "near_up",
                    "type": "limit_proximity",
                    "side": "up",
                    "within_pct": 0.5,
                    "symbols": ["002553.SZ"],
                },
            ],
        )
    )
    assert [rule.id for rule in cfg.rules] == ["near_up_wide", "near_up"]
    assert cfg.rules[0].symbols == ("601099.SH",)
    assert cfg.rules[1].symbols == ("002553.SZ",)


def test_symbols_not_in_watchlist_warns_but_does_not_fail(caplog):
    with caplog.at_level(logging.WARNING, logger="cn_watch.config"):
        cfg = parse_config(
            raw(
                rules=[
                    {
                        "id": "near_up",
                        "type": "limit_proximity",
                        "side": "up",
                        "within_pct": 0.5,
                        "symbols": ["601099", "512880"],
                    }
                ]
            )
        )
    assert cfg.rules[0].symbols == ("601099.SH", "512880.SH")
    messages = [record.getMessage() for record in caplog.records]
    assert any("near_up" in message and "601099.SH" in message for message in messages)
    assert any("512880.SH" in message for message in messages)


@pytest.mark.parametrize(
    "symbols",
    [
        [],
        ["601099", "601099.SH"],
        ["601099", "601099"],
        ["ABC123"],
        ["399975"],
        ["000300.SH"],
        [None],
        [True],
        ["600000.XX"],
        "601099",
        601099,
        None,
        {"601099": 1},
    ],
)
def test_invalid_symbols_are_rejected(symbols):
    with pytest.raises(ConfigError):
        parse_config(
            raw(
                rules=[
                    {
                        "id": "near_up",
                        "type": "limit_proximity",
                        "side": "up",
                        "within_pct": 0.5,
                        "symbols": symbols,
                    }
                ]
            )
        )


def test_symbols_and_legacy_codes_cannot_be_combined():
    with pytest.raises(ConfigError):
        parse_config(
            raw(
                rules=[
                    {
                        "id": "near_up",
                        "type": "limit_proximity",
                        "side": "up",
                        "within_pct": 0.5,
                        "symbols": ["002553.SZ"],
                        "codes": ["002553.SZ"],
                    }
                ]
            )
        )


def test_empty_watchlist_and_rules_are_valid():
    # Reminder plans add their own codes at runtime, so an engine may start watching nothing.
    parsed = parse_config(raw(watchlist=[], rules=[]))
    assert parsed.watchlist == ()
    assert parsed.rules == ()
