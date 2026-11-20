from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mcp_filter_proxy.config import (
    CheckConfig,
    ConfigError,
    EmptyAllowlistError,
    load_config,
    parse_config,
)


def base(**overrides):
    data = {
        "name": "proxy",
        "upstream": {"command": "/bin/true"},
        "allow": ["search_symbol"],
    }
    data.update(overrides)
    return data


def test_defaults_are_applied():
    cfg = parse_config(base(), environ={})
    assert cfg.rename_prefix == ""
    assert cfg.upstream.args == ()
    assert cfg.upstream.cwd is None
    assert cfg.upstream.inherit_env is False
    assert dict(cfg.upstream.env) == {}
    assert cfg.cache.max_entries == 500
    assert cfg.cache.ttl_default == 60
    assert cfg.cache.ttl_for("anything") == 60
    assert cfg.rate_limit.max_calls_per_minute == 60
    assert cfg.checks == ()
    assert cfg.annotations_for("search_symbol") == {}


def test_env_reference_expansion_and_overrides():
    data = base(upstream={"command": "/bin/true", "env": {"TOKEN": "pre-${SECRET}-post"}})
    cfg = parse_config(data, environ={"SECRET": "abc"})
    assert cfg.upstream.env["TOKEN"] == "pre-abc-post"


def test_missing_env_reference_fails_with_variable_name():
    data = base(upstream={"command": "/bin/true", "env": {"TOKEN": "${T10_NOT_SET}"}})
    with pytest.raises(ConfigError) as info:
        parse_config(data, environ={})
    assert "T10_NOT_SET" in str(info.value)


def test_empty_allow_fails():
    with pytest.raises(EmptyAllowlistError):
        parse_config(base(allow=[]), environ={})
    with pytest.raises(EmptyAllowlistError):
        parse_config({"name": "p", "upstream": {"command": "/bin/true"}}, environ={})


def test_duplicate_allow_names_are_deduplicated():
    cfg = parse_config(base(allow=["a", "b", "a"]), environ={})
    assert cfg.allow == ("a", "b")


def test_checks_and_annotations_are_parsed():
    data = base(
        checks=[
            {
                "tool": "search_symbol",
                "type": "bars_within_requested_dates",
                "start_arg": "start_date",
                "end_arg": "end_date",
                "date_field": "trade_date",
            }
        ],
        annotations={"search_symbol": {"units": {"volume": "lots"}}},
    )
    cfg = parse_config(data, environ={})
    assert cfg.checks == (
        CheckConfig(
            tool="search_symbol",
            type="bars_within_requested_dates",
            start_arg="start_date",
            end_arg="end_date",
            date_field="trade_date",
        ),
    )
    assert cfg.checks_for("search_symbol")[0].date_field == "trade_date"
    assert cfg.checks_for("get_fund_flow") == ()
    assert cfg.annotations_for("search_symbol") == {"units": {"volume": "lots"}}
    assert cfg.annotations_for("get_fund_flow") == {}


def test_cache_and_rate_limit_values():
    data = base(
        cache={"max_entries": 7, "ttl_seconds": {"default": 10, "b": 0}},
        rate_limit={"max_calls_per_minute": 3},
    )
    cfg = parse_config(data, environ={})
    assert cfg.cache.max_entries == 7
    assert cfg.cache.ttl_for("unknown") == 10
    assert cfg.cache.ttl_for("b") == 0
    assert cfg.rate_limit.max_calls_per_minute == 3


@pytest.mark.parametrize(
    "cache",
    [
        {"max_entries": 0},
        {"max_entries": True},
        {"ttl_seconds": {"default": -1}},
        {"ttl_seconds": {"x": "soon"}},
    ],
)
def test_invalid_cache_values_are_rejected(cache):
    with pytest.raises(ConfigError):
        parse_config(base(cache=cache), environ={})


def test_invalid_rate_limit_is_rejected():
    with pytest.raises(ConfigError):
        parse_config(base(rate_limit={"max_calls_per_minute": 0}), environ={})
    with pytest.raises(ConfigError):
        parse_config(base(rate_limit={"max_calls_per_minute": True}), environ={})


def test_non_mapping_document_is_rejected():
    with pytest.raises(ConfigError):
        parse_config(["not", "a", "mapping"], environ={})


def test_load_config_reports_invalid_yaml(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_config(path, environ={})
    assert "invalid YAML" in str(info.value)


def test_load_config_from_file(tmp_path: Path):
    path = tmp_path / "ok.yaml"
    path.write_text(yaml.safe_dump(base(), sort_keys=False), encoding="utf-8")
    cfg = load_config(path, environ={})
    assert cfg.name == "proxy"
