from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from cn_watch import cli
from support import BASE_CONFIG, DAY0, quote


def write_config(tmp_path: Path, **overrides) -> Path:
    raw = dict(BASE_CONFIG)
    raw.update(overrides)
    target = tmp_path / "config.yaml"
    target.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return target


def run_cli(*args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "cn_watch", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_check_config_exit_codes(tmp_path: Path):
    good = write_config(tmp_path)
    result = run_cli("--config", good, "--check-config")
    assert result.returncode == 0
    assert result.stdout.strip() == "OK"

    bad = tmp_path / "bad.yaml"
    bad.write_text(good.read_text(encoding="utf-8").replace("threshold_pct: 3.0", "threshold_pct: -3.0"), encoding="utf-8")
    result = run_cli("--config", bad, "--check-config")
    assert result.returncode == 2
    assert "配置错误" in result.stderr

    result = run_cli("--config", tmp_path / "missing.yaml", "--check-config")
    assert result.returncode == 2


def test_invalid_flag_combinations(tmp_path: Path):
    cfg = write_config(tmp_path)
    assert run_cli("--config", cfg, "--serve").returncode == 2
    assert run_cli("--config", cfg, "--once", "--replay", "x.jsonl").returncode == 2


def replay_file(tmp_path: Path) -> Path:
    moment = DAY0 + timedelta(seconds=3)
    row = {
        "t": moment.isoformat(),
        "quotes": {
            "002553.SZ": {
                "name": "南方精工",
                "price": 15.5,
                "prev_close": 15.0,
                "open": 15.0,
                "high": 15.5,
                "low": 15.0,
                "volume_lots": 1000,
                "amount_yuan": 15_500_000.0,
                "exch_time": moment.strftime("%Y%m%d%H%M%S"),
                "limit_up": 16.5,
                "limit_down": 13.5,
            }
        },
    }
    target = tmp_path / "replay.jsonl"
    target.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def test_replay_cli_writes_outputs(tmp_path: Path):
    cfg = write_config(tmp_path)
    out = tmp_path / "out"
    result = run_cli("--config", cfg, "--replay", replay_file(tmp_path), "--out-dir", out)
    assert result.returncode == 0
    alerts = [json.loads(line) for line in (out / "alerts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(alerts) == 1
    assert alerts[0]["rule_id"] == "pct_up_3"
    assert json.loads((out / "state.json").read_text(encoding="utf-8"))["quotes"]["002553.SZ"]["name"] == "南方精工"
    assert (out / "polls.jsonl").exists()


def test_once_prints_one_json_object(tmp_path: Path, monkeypatch, capsys):
    cfg = write_config(tmp_path)
    out = tmp_path / "once"

    class FakeGatewaySource:
        def __init__(self, gateway_url: str = "", timeout: float = 3.0) -> None:
            self.gateway_url = gateway_url
            self.timeout = timeout

        def fetch(self, codes, now):
            return {code: quote(price=15.0, exch=now) for code in codes}

    monkeypatch.setattr(cli, "GatewaySource", FakeGatewaySource)
    code = cli.main(["--config", str(cfg), "--once", "--out-dir", str(out)])
    captured = capsys.readouterr()
    assert code == 0
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert "snapshot_time" in payload and "quotes" in payload and "alerts" in payload
    assert "002553.SZ" in payload["quotes"]
    assert (out / "state.json").exists()


def test_live_path_passes_the_config_path_to_the_engine(monkeypatch):
    """Regression: `_run_live` once referenced an undefined `args`, so a restarted engine crashed at startup."""
    import threading

    from cn_watch import cli

    seen = {}

    class FakeEngine:
        def __init__(self, config, source, clock, store, calendar=None, config_path=None):
            seen["config_path"] = config_path

        def run(self, stop):
            seen["ran"] = True

    monkeypatch.setattr(cli, "Engine", FakeEngine)
    monkeypatch.setattr(cli, "GatewaySource", lambda gateway_url="", timeout=None: object())
    monkeypatch.setattr(cli, "RealClock", lambda stop=None: object())
    monkeypatch.setattr(cli, "start_server", lambda engine, host, port: (object(), object()))
    monkeypatch.setattr(cli, "stop_server", lambda httpd, thread: None)

    class Cfg:
        class polling:
            timeout_seconds = 3

        gateway_url = "http://127.0.0.1:8868"

        class api:
            host = "127.0.0.1"
            port = 0

    assert cli._run_live(Cfg, object(), threading.Event(), None, "watch.yaml") == 0
    assert seen == {"config_path": "watch.yaml", "ran": True}
