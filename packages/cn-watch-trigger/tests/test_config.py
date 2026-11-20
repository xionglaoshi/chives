from __future__ import annotations

import copy
from pathlib import Path

import pytest

from cn_watch_trigger.clock import parse_moment, parse_now
from cn_watch_trigger.config import ConfigError, load_config

from support import PKG, REPO, TEMPLATE, base_config_dict, write_config


def config_payload(tmp_path: Path, engine: str = "http://127.0.0.1:8865", **overrides):
    payload = base_config_dict(tmp_path, engine)
    payload.update(overrides)
    return payload


def test_example_config_loads() -> None:
    cfg = load_config(PKG / "trigger.example.yaml")
    assert cfg.engine == "http://127.0.0.1:8865"
    assert cfg.state_dir == REPO / "runtime/watch/analyses"
    assert cfg.poll_seconds == 3.0
    assert len(cfg.triggers) == 2
    assert cfg.limits.max_runs_per_day == 20
    assert cfg.limits.max_queue == 5
    assert cfg.runner.command.count("{prompt}") == 1
    assert "headless" in cfg.runner.command
    assert cfg.runner.cwd == REPO


def test_relative_paths_are_relative_to_config_dir(tmp_path: Path) -> None:
    nested = tmp_path / "conf"
    nested.mkdir()
    payload = config_payload(tmp_path)
    payload["state_dir"] = "state"
    payload["runner"]["cwd"] = "."
    path = write_config(nested, payload)
    cfg = load_config(path)
    assert cfg.state_dir == nested / "state"
    assert cfg.runner.cwd == nested
    assert cfg.base_dir == nested


def test_template_without_alert_data_block_is_allowed(tmp_path: Path) -> None:
    template = tmp_path / "template.md"
    template.write_text("分析这个告警：{alert_json}\n", encoding="utf-8")
    payload = config_payload(tmp_path)
    payload["prompt_template"] = str(template)
    cfg = load_config(write_config(tmp_path, payload))
    assert cfg.template_text == "分析这个告警：{alert_json}\n"


@pytest.mark.parametrize(
    "engine",
    [
        "http://10.1.2.3:8865",
        "http://127.0.0.1.evil.com:8865",
        "http://localhost.evil.com:8865",
        "http://0.0.0.0:8865",
        "https://[::2]:8865",
        "ftp://127.0.0.1:8865",
        "http://user:pass@127.0.0.1:8865",
        "http://127.0.0.1:8865/?token=x",
        "http://[::1",
    ],
)
def test_non_loopback_or_unsafe_engine_rejected(tmp_path: Path, engine: str) -> None:
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, config_payload(tmp_path, engine)))


def test_loopback_variants_accepted(tmp_path: Path) -> None:
    for engine in ("http://127.0.0.1:8865", "http://localhost:8865", "http://[::1]:8865"):
        payload = config_payload(tmp_path, engine)
        assert load_config(write_config(tmp_path, payload)).engine == engine


def test_trigger_codes_are_normalized(tmp_path: Path) -> None:
    payload = config_payload(tmp_path)
    payload["triggers"] = [{"rule_ids": ["pct_up_3"], "codes": ["002553.sz", "*"]}]
    cfg = load_config(write_config(tmp_path, payload))
    assert cfg.triggers[0].codes == ("002553.SZ", "*")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(prompt_template=str(REPO / "README.md")),
        lambda p: p.update(prompt_template=str(Path("/nonexistent/template.md"))),
        lambda p: p.update(triggers=[]),
        lambda p: p.update(poll_seconds=-1),
        lambda p: p.update(poll_seconds=0),
        lambda p: p.update(poll_seconds=True),
        lambda p: p["limits"].update(max_runs_per_day=0),
        lambda p: p["limits"].update(max_runs_per_day=True),
        lambda p: p["limits"].update(cooldown_seconds=-1),
        lambda p: p["limits"].update(max_alert_age_seconds=0),
        lambda p: p["limits"].update(run_timeout_seconds=0),
        lambda p: p["limits"].update(max_queue=0),
        lambda p: p["runner"].update(command=["echo", "hi"]),
        lambda p: p["runner"].update(command="echo {prompt}"),
        lambda p: p["runner"].update(command=["x", "{prompt}", "{prompt}"]),
        lambda p: p["runner"].update(command=[]),
        lambda p: p["runner"].update(env={"X": 1}),
        lambda p: p["runner"].update(cwd="/nonexistent/cwd"),
        lambda p: p["triggers"][0].update(rule_ids=[]),
        lambda p: p["triggers"][0].update(codes=[]),
    ],
)
def test_invalid_configs_rejected(tmp_path: Path, mutate) -> None:
    payload = config_payload(tmp_path)
    mutate(payload)
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, payload))


def test_invalid_yaml_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("engine: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_config_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_config_is_not_mutated_by_loader(tmp_path: Path) -> None:
    payload = config_payload(tmp_path)
    original = copy.deepcopy(payload)
    load_config(write_config(tmp_path, payload))
    assert payload == original


def test_clock_parsing() -> None:
    fixed = parse_now("2026-11-03T09:40:00+08:00")
    assert fixed.isoformat() == "2026-11-03T09:40:00+08:00"
    assert parse_moment("2026-11-03T01:40:00Z").isoformat() == "2026-11-03T09:40:00+08:00"
    assert parse_moment("2026-11-03T09:40:00").isoformat() == "2026-11-03T09:40:00+08:00"
    with pytest.raises(ValueError):
        parse_moment("not-a-time")
