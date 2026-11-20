"""Shared fixtures/helpers for the offline test suite."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from hub_trigger.clock import SHANGHAI
from hub_trigger.config import FastJudgeConfig, Limits, RunnerConfig
from hub_trigger.hub import HubClient
from hub_trigger.service import FastJudgeService
from hub_trigger.store import FastJudgeStore

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]
TEMPLATE = REPO / "presets/finance/fast-judge.md"
FAKE_RUNNER = PKG / "tests/fake_runner.py"
NOW = datetime(2026, 11, 3, 9, 40, 0, tzinfo=SHANGHAI)
DEFAULT_TEXT = "观察｜现价仍在区间下沿，量能未确认｜10:30 看能否站稳 VWAP｜跌破 10.20 放弃"


def default_limits(**overrides: Any) -> Limits:
    values: dict[str, Any] = {
        "max_runs_per_day": 20,
        "cooldown_seconds": 600.0,
        "max_trigger_age_seconds": 120.0,
        "run_timeout_seconds": 5.0,
        "max_queue": 3,
    }
    values.update(overrides)
    return Limits(**values)


def runner_config(
    tmp_path: Path,
    *,
    mode: str = "ok",
    text: str | None = None,
    log: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> RunnerConfig:
    env = {
        "FAKE_RUNNER_MODE": mode,
        "FAKE_RUNNER_LOG": str(log or (tmp_path / "runner.log")),
    }
    if text is not None:
        env["FAKE_RUNNER_TEXT"] = text
    if extra_env:
        env.update(extra_env)
    return RunnerConfig(
        command=(sys.executable, str(FAKE_RUNNER), "{prompt}"),
        env=env,
        cwd=cwd or tmp_path,
    )


def make_config(
    tmp_path: Path,
    hub: str,
    *,
    limits: Limits | None = None,
    runner: RunnerConfig | None = None,
    template_text: str | None = None,
    state_dir: Path | None = None,
) -> FastJudgeConfig:
    return FastJudgeConfig(
        hub=hub,
        state_dir=state_dir or (tmp_path / "state"),
        poll_seconds=0.5,
        prompt_template=TEMPLATE,
        template_text=TEMPLATE.read_text(encoding="utf-8") if template_text is None else template_text,
        limits=limits or default_limits(),
        runner=runner or runner_config(tmp_path),
        config_path=tmp_path / "fastjudge.yaml",
        base_dir=tmp_path,
    )


def service(
    config: FastJudgeConfig,
    *,
    now: datetime = NOW,
    from_id: int | None = None,
    dry_run: bool = False,
) -> FastJudgeService:
    return FastJudgeService(
        config,
        HubClient(config.hub),
        FastJudgeStore(config.state_dir),
        lambda: now,
        dry_run=dry_run,
        from_id=from_id,
    )


def records(config: FastJudgeConfig) -> list[dict[str, Any]]:
    return FastJudgeStore(config.state_dir).read_records()


def state(config: FastJudgeConfig) -> dict[str, Any]:
    return json.loads((config.state_dir / "state.json").read_text(encoding="utf-8"))


def runner_log(tmp_path: Path, name: str = "runner.log") -> list[dict[str, Any]]:
    path = tmp_path / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def trigger(
    trigger_id: int,
    *,
    ts: str = "2026-11-03T09:39:00+08:00",
    kind: str = "card_execute",
    card_id: int | None = 1,
    code: str | None = "600519.SH",
    to_state: str = "execute",
    reason: str = "条件满足",
    context_ready: bool = True,
) -> dict[str, Any]:
    return {
        "id": trigger_id,
        "ts": ts,
        "kind": kind,
        "card_id": card_id,
        "code": code,
        "name": "贵州茅台",
        "from_state": "await_confirm",
        "to_state": to_state,
        "reason": reason,
        "context_ready": context_ready,
        "judged": False,
    }


def context(trigger_row: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "trigger": trigger_row or trigger(1),
        "card": {"id": 1, "code": "600519.SH", "state": "execute", "thesis": "测试用作战卡"},
        "review": {"date": "2026-11-03", "env_label": "neutral", "mainline": "测试主线"},
        "snapshot": {
            "quote": {"price": 1500.0, "change_pct": 1.2, "vwap_dev_pct": 0.1, "limit_distance_pct": 8.8},
            "sector": {"code": "BK0477", "name": "白酒", "rank": 3, "change_pct": 1.0},
            "market": {"regime": "neutral", "breadth": 0.52, "amount_yuan": 800000000000},
        },
        "holdings_relation": {"held": False, "weight_pct": None, "single_cap_pct": None, "total_room_pct": None},
        "discipline": {"paused": False, "mood_today": {"pre": "calm", "mid": None, "post": None}},
        "thresholds": {},
        "today": {"trigger_count": 1, "fast_judgements_used": 0},
        "missing": [],
    }
    payload.update(extra)
    return payload


def base_config_dict(tmp_path: Path, hub: str, *, mode: str = "ok") -> dict[str, Any]:
    return {
        "hub": hub,
        "state_dir": "state",
        "poll_seconds": 0.5,
        "prompt_template": str(TEMPLATE),
        "limits": {
            "max_runs_per_day": 20,
            "cooldown_seconds": 600,
            "max_trigger_age_seconds": 120,
            "run_timeout_seconds": 5,
            "max_queue": 3,
        },
        "runner": {
            "command": [sys.executable, str(FAKE_RUNNER), "{prompt}"],
            "env": {
                "FAKE_RUNNER_MODE": mode,
                "FAKE_RUNNER_LOG": str(tmp_path / "runner.log"),
            },
            "cwd": ".",
        },
    }


def write_config(
    tmp_path: Path, payload: Mapping[str, Any], name: str = "fastjudge.yaml"
) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_cli(
    config_path: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, "CHIVES_HUB_URL": "", **(env or {})}
    merged["PYTHONPATH"] = str(PKG / "src") + (
        os.pathsep + merged["PYTHONPATH"] if merged.get("PYTHONPATH") else ""
    )
    return subprocess.run(
        [sys.executable, "-m", "hub_trigger", "--config", str(config_path), *args],
        cwd=str(PKG),
        env=merged,
        capture_output=True,
        text=True,
        timeout=60,
    )
