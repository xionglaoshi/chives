from __future__ import annotations

import json
from pathlib import Path

import pytest

from chives_signals.config import ConfigError, load_config, parse_text


def test_defaults(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("runtime:\n  db_path: hub.db\n  out_dir: .\n", encoding="utf-8")
    config = load_config(tmp_path / "c.yaml")
    assert config.api_host == "127.0.0.1"
    assert config.api_port == 8867
    assert config.db_path == (tmp_path / "hub.db").resolve()
    assert config.cn_watch_base == "http://127.0.0.1:8865"
    assert config.market_watch_base == "http://127.0.0.1:8866"
    assert config.max_active_plans == 30
    assert config.max_plan_days == 30
    assert config.max_body_bytes == 65536
    assert config.max_tencent_codes == 80


def test_nested_yaml_and_comments(tmp_path: Path) -> None:
    text = (
        "# comment\n"
        "api:\n"
        "  host: 127.0.0.1   # another\n"
        "  port: 9999\n"
        "polling:\n"
        "  alerts_seconds: 4\n"
        "  plans_seconds: 5\n"
    )
    (tmp_path / "c.yaml").write_text(text, encoding="utf-8")
    config = load_config(tmp_path / "c.yaml")
    assert config.api_port == 9999
    assert config.alerts_seconds == 4.0
    assert config.plans_seconds == 5.0


def test_json_config(tmp_path: Path) -> None:
    payload = {"api": {"port": 8800}, "runtime": {"db_path": "x.db", "out_dir": "."}}
    (tmp_path / "c.json").write_text(json.dumps(payload), encoding="utf-8")
    config = load_config(tmp_path / "c.json")
    assert config.api_port == 8800
    assert config.db_path == (tmp_path / "x.db").resolve()


def test_relative_paths_resolved(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "c.yaml").write_text(
        "runtime:\n  db_path: ../data/hub.db\n  out_dir: ../data\nanalyses_dir: ../a\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "c.yaml")
    assert config.db_path == (tmp_path.parent / "data/hub.db").resolve()
    assert config.analyses_dir == (tmp_path.parent / "a").resolve()


def test_host_must_be_loopback(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("api:\n  host: 0.0.0.0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path / "c.yaml")


def test_port_range(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("api:\n  port: 70000\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path / "c.yaml")


def test_upstream_must_be_loopback(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text(
        "upstreams:\n  cn_watch: http://10.0.0.1:8865\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "c.yaml")


def test_production_upstream_port_is_fixed(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text(
        "upstreams:\n  cn_watch: http://127.0.0.1:9999\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "c.yaml")


def test_test_mode_allows_loopback_override(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("runtime:\n  db_path: hub.db\n  out_dir: .\n", encoding="utf-8")
    config = load_config(
        tmp_path / "c.yaml",
        env={"CHIVES_HUB_TEST_MODE": "1", "CHIVES_HUB_CN_WATCH_BASE": "http://127.0.0.1:1234"},
    )
    assert config.cn_watch_base == "http://127.0.0.1:1234"


def test_override_without_test_mode_rejected(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("runtime:\n  db_path: hub.db\n  out_dir: .\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(
            tmp_path / "c.yaml",
            env={"CHIVES_HUB_CN_WATCH_BASE": "http://127.0.0.1:1234"},
        )


def test_tencent_override_requires_test_mode(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("runtime:\n  db_path: hub.db\n  out_dir: .\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(
            tmp_path / "c.yaml",
            env={"CHIVES_HUB_TENCENT_BASE": "http://127.0.0.1:1234"},
        )


def test_tencent_override_must_be_loopback(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("runtime:\n  db_path: hub.db\n  out_dir: .\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(
            tmp_path / "c.yaml",
            env={"CHIVES_HUB_TEST_MODE": "1", "CHIVES_HUB_TENCENT_BASE": "http://example.com"},
        )


def test_body_cap_is_fixed(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text(
        "runtime:\n  db_path: hub.db\n  out_dir: .\nlimits:\n  max_body_bytes: 1024\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "c.yaml")


def test_close_time_validation(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text(
        "runtime:\n  db_path: hub.db\n  out_dir: .\nsnapshots:\n  close_time: '25:99'\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "c.yaml")


def test_max_plan_days_bound(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text(
        "runtime:\n  db_path: hub.db\n  out_dir: .\nlimits:\n  max_plan_days: 31\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "c.yaml")


def test_missing_file() -> None:
    with pytest.raises(ConfigError):
        load_config("/no/such/config.yaml")


def test_parse_text_scalars() -> None:
    parsed = parse_text("a: 1\nb: true\nc: null\nd: 'x y'\ne: [1, 2]\nf: {k: v}\n")
    assert parsed == {"a": 1, "b": True, "c": None, "d": "x y", "e": [1, 2], "f": {"k": "v"}}


def test_parse_text_rejects_bad_indent() -> None:
    with pytest.raises(ConfigError):
        parse_text("a:\n    b: 1\n  c: 2\n")


def test_calendar_file_default(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("runtime:\n  db_path: hub.db\n  out_dir: .\n", encoding="utf-8")
    config = load_config(tmp_path / "c.yaml")
    assert config.calendar_file == (tmp_path / "../../config/trade_calendar.json").resolve()


def test_profile_dir_resolved(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text(
        "runtime:\n  db_path: hub.db\n  out_dir: .\nportfolio:\n  profile_dir: profile\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "c.yaml")
    assert config.profile_dir == (tmp_path / "profile").resolve()
