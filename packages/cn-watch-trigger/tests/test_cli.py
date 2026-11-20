from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from cn_watch_trigger.engine import EngineClient, EngineError

from support import (
    ALERTS,
    REPO,
    base_config_dict,
    run_cli,
    runner_log,
    write_config,
)

NOW_TEXT = "2026-11-03T09:40:00+08:00"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_engine_paginates_to_latest(engine_factory) -> None:
    alerts = [
        {
            "id": index,
            "ts": "2026-11-03T09:30:00+08:00",
            "code": "002553.SZ",
            "name": "南方精工",
            "rule_id": "pct_up_3",
        }
        for index in range(1, 502)
    ]
    engine = engine_factory(alerts)
    client = EngineClient(engine.url)
    assert client.latest_alert_id() == 501
    page = client.alerts_after(498)
    assert [row["id"] for row in page] == [499, 500, 501]


def test_engine_returns_sorted_rows(engine_factory) -> None:
    alerts = [dict(ALERTS[0]), dict(ALERTS[1])]
    alerts.reverse()
    engine = engine_factory(alerts)
    assert [row["id"] for row in EngineClient(engine.url).alerts_after(0)] == [1, 2]


def test_engine_unreachable() -> None:
    with pytest.raises(EngineError):
        EngineClient(f"http://127.0.0.1:{free_port()}", timeout=0.5).alerts_after(0)


def test_cli_first_start_baseline(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory(ALERTS)
    cfg = write_config(tmp_path, base_config_dict(tmp_path, engine.url))
    result = run_cli(cfg, "--once", "--now", NOW_TEXT)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "基线" in result.stderr
    assert state_from(cfg)["last_alert_id"] == 5
    assert not (tmp_path / "state/analyses.jsonl").exists()
    assert runner_log(tmp_path) == []


def test_cli_from_id_analyses_and_exits(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory(ALERTS)
    cfg = write_config(tmp_path, base_config_dict(tmp_path, engine.url))
    assert run_cli(cfg, "--once", "--now", NOW_TEXT).returncode == 0
    result = run_cli(cfg, "--once", "--from-id", "2", "--now", NOW_TEXT)
    assert result.returncode == 0
    rows = records_from(cfg)
    assert [row["alert_id"] for row in rows] == [3, 4, 5]
    assert all(row["status"] == "done" for row in rows)
    assert len(runner_log(tmp_path)) == 3


def test_cli_dry_run_starts_nothing(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory(ALERTS)
    cfg = write_config(tmp_path, base_config_dict(tmp_path, engine.url))
    result = run_cli(cfg, "--once", "--from-id", "2", "--now", NOW_TEXT, "--dry-run")
    assert result.returncode == 0
    rows = records_from(cfg)
    assert [(row["alert_id"], row["reason"]) for row in rows] == [
        (3, "dry_run"),
        (4, "dry_run"),
        (5, "dry_run"),
    ]
    assert runner_log(tmp_path) == []


def test_cli_env_is_scrubbed(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory(ALERTS)
    cfg = write_config(tmp_path, base_config_dict(tmp_path, engine.url))
    result = run_cli(
        cfg,
        "--once",
        "--from-id",
        "2",
        "--now",
        NOW_TEXT,
        env={"MY_API_KEY": "secret", "FAKE_SECRET_TOKEN": "secret", "KEEP_ME": "ok"},
    )
    assert result.returncode == 0
    names = set(runner_log(tmp_path)[0]["env_names"])
    assert "MY_API_KEY" not in names
    assert "FAKE_SECRET_TOKEN" not in names
    assert "KEEP_ME" in names
    assert "FAKE_RUNNER_MODE" in names


def test_cli_stop_consumes_without_replay(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory(ALERTS)
    cfg = write_config(tmp_path, base_config_dict(tmp_path, engine.url))
    (tmp_path / "state").mkdir()
    stop_path = tmp_path / "state/STOP"
    stop_path.write_text("stop", encoding="utf-8")
    assert run_cli(cfg, "--once", "--from-id", "2", "--now", NOW_TEXT).returncode == 0
    rows = records_from(cfg)
    assert [row["reason"] for row in rows] == ["kill_switch", "kill_switch", "kill_switch"]
    stop_path.unlink()
    assert run_cli(cfg, "--once", "--now", NOW_TEXT).returncode == 0
    assert len(records_from(cfg)) == 3
    assert runner_log(tmp_path) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(engine="http://10.1.2.3:8865"),
        lambda p: p.update(engine="http://127.0.0.1.evil.com:8865"),
        lambda p: p.update(prompt_template=str(Path("/nonexistent/template.md"))),
        lambda p: p.update(prompt_template=str(REPO / "README.md")),
        lambda p: p.update(triggers=[]),
        lambda p: p.update(poll_seconds=0),
        lambda p: p["limits"].update(max_runs_per_day=0),
        lambda p: p["limits"].update(run_timeout_seconds=0),
        lambda p: p["runner"].update(command=["echo", "hi"]),
        lambda p: p["runner"].update(command="echo {prompt}"),
        lambda p: p["runner"].update(command=["x", "{prompt}", "{prompt}"]),
    ],
)
def test_cli_invalid_config_exits_2(tmp_path: Path, mutate) -> None:
    payload = base_config_dict(tmp_path, "http://127.0.0.1:8865")
    mutate(payload)
    cfg = write_config(tmp_path, payload)
    result = run_cli(cfg, "--once", "--dry-run")
    assert result.returncode == 2, result.stderr
    assert "配置错误" in result.stderr


def test_cli_bad_now_exits_2(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, base_config_dict(tmp_path, "http://127.0.0.1:8865"))
    result = run_cli(cfg, "--once", "--now", "not-a-time")
    assert result.returncode == 2
    assert "--now" in result.stderr


def test_cli_negative_from_id_exits_2(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, base_config_dict(tmp_path, "http://127.0.0.1:8865"))
    result = run_cli(cfg, "--once", "--from-id", "-1")
    assert result.returncode == 2


def test_cli_engine_unavailable_exits_1(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, base_config_dict(tmp_path, f"http://127.0.0.1:{free_port()}"))
    result = run_cli(cfg, "--once", "--from-id", "0")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "运行失败" in result.stderr


def state_from(config_path: Path) -> dict:
    path = config_path.parent / "state/state.json"
    return json.loads(path.read_text(encoding="utf-8"))


def records_from(config_path: Path) -> list[dict]:
    path = config_path.parent / "state/analyses.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
