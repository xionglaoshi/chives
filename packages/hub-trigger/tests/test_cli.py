"""CLI behaviour: exit codes, baseline, --now/--from-id and dry-run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from hub_trigger import __version__

from support import base_config_dict, context, run_cli, runner_log, trigger, write_config


def _config(tmp_path: Path, hub_url: str, **overrides: Any) -> Path:
    payload = base_config_dict(tmp_path, hub_url)
    payload.update(overrides)
    return write_config(tmp_path, payload)


def test_once_baseline_exits_zero(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory([trigger(1), trigger(2)])
    path = _config(tmp_path, hub.url)
    result = run_cli(path, "--once")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    saved = json.loads((tmp_path / "state/state.json").read_text(encoding="utf-8"))
    assert saved["last_trigger_id"] == 2
    assert hub.judgements == []


def test_once_processes_with_from_id(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    row = trigger(1)
    hub.add(row, context(row))
    path = _config(tmp_path, hub.url)
    result = run_cli(path, "--once", "--from-id", "0", "--now", "2026-11-03T09:40:00+08:00")
    assert result.returncode == 0, result.stderr
    assert len(hub.judgements) == 1


def test_from_id_processes_existing_state(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    row = trigger(5)
    hub.add(row, context(row))
    path = _config(tmp_path, hub.url)
    run_cli(path, "--once")
    result = run_cli(path, "--once", "--from-id", "0", "--now", "2026-11-03T09:40:00+08:00")
    assert result.returncode == 0, result.stderr
    assert hub.judgements[0]["id"] == 5


def test_dry_run_never_starts_runner(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    row = trigger(1)
    hub.add(row, context(row))
    path = _config(tmp_path, hub.url)
    result = run_cli(path, "--once", "--from-id", "0", "--dry-run", "--now", "2026-11-03T09:40:00+08:00")
    assert result.returncode == 0, result.stderr
    assert runner_log(tmp_path) == []
    assert hub.judgements == []
    records = (tmp_path / "state/analyses.jsonl").read_text(encoding="utf-8")
    assert "dry_run" in records


def test_now_is_used_for_staleness(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    row = trigger(1, ts="2026-11-03T09:00:00+08:00")
    hub.add(row, context(row))
    path = _config(tmp_path, hub.url)
    result = run_cli(
        path, "--once", "--from-id", "0", "--now", "2026-11-03T09:40:00+08:00"
    )
    assert result.returncode == 0, result.stderr
    assert "stale_trigger" in (tmp_path / "state/analyses.jsonl").read_text(encoding="utf-8")
    assert hub.judgements == []


def test_invalid_now_exits_two(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    path = _config(tmp_path, hub_factory([]).url)
    result = run_cli(path, "--once", "--now", "not-a-time")
    assert result.returncode == 2
    assert "参数错误" in result.stderr


def test_missing_config_exits_two(tmp_path: Path) -> None:
    result = run_cli(tmp_path / "missing.yaml", "--once")
    assert result.returncode == 2
    assert "配置错误" in result.stderr


def test_invalid_config_exits_two(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    result = run_cli(path, "--once")
    assert result.returncode == 2


def test_non_loopback_env_exits_two(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    path = _config(tmp_path, hub_factory([]).url)
    result = run_cli(path, "--once", env={"CHIVES_HUB_URL": "http://example.com:8867"})
    assert result.returncode == 2
    assert "回环" in result.stderr


def test_unreachable_hub_exits_one(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    path = _config(tmp_path, "http://127.0.0.1:1")
    result = run_cli(path, "--once")
    assert result.returncode == 1


def test_version_flag() -> None:
    result = run_cli(Path("unused.yaml"), "--version")
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_config_is_required() -> None:
    import subprocess
    import sys

    import os

    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "hub_trigger"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "--config" in result.stderr
