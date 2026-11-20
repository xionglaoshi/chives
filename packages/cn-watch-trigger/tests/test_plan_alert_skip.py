from __future__ import annotations

from pathlib import Path

import pytest

from cn_watch_trigger.service import _is_plan_alert

from support import (
    default_limits,
    make_config,
    records,
    runner_log,
    service,
    state,
)


def plan_alert(alert_id: int = 1, **overrides):
    row = {
        "id": alert_id,
        "ts": "2026-11-03T09:35:00+08:00",
        "code": "002553.SZ",
        "name": "南方精工",
        "rule_id": "plan:card-1",
        "rule_type": "plan",
        "price": 15.5,
        "severity": "L2",
        "detail": {"plan_id": "card-1", "from": "observe", "to": "execute"},
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "alert,expected",
    [
        ({"rule_type": "plan", "rule_id": "anything"}, True),
        ({"rule_id": "plan:card-1"}, True),
        ({"rule_type": "pct_change", "rule_id": "plan:card-1"}, True),
        ({"rule_type": "pct_change", "rule_id": "pct_up_3"}, False),
        ({"rule_id": "myplan:card-1"}, False),
        ({"rule_type": None, "rule_id": None}, False),
    ],
)
def test_is_plan_alert(alert, expected):
    assert _is_plan_alert(alert) is expected


def test_plan_alert_is_skipped_without_runner(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory([plan_alert()])
    cfg = make_config(tmp_path, engine.url)
    service(cfg, from_id=0).run_cycle()
    rows = records(cfg)
    assert [(row["alert_id"], row["status"], row["reason"]) for row in rows] == [
        (1, "skipped", "plan_alert")
    ]
    assert runner_log(tmp_path) == []
    assert not (tmp_path / "state/analysis-1.md").exists()


def test_rule_id_prefix_is_enough_to_skip(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory([plan_alert(rule_type=None)])
    cfg = make_config(tmp_path, engine.url)
    service(cfg, from_id=0).run_cycle()
    assert records(cfg)[0]["reason"] == "plan_alert"
    assert runner_log(tmp_path) == []


def test_normal_alert_still_runs(tmp_path: Path, engine_factory) -> None:
    normal = plan_alert(rule_type="pct_change", rule_id="pct_up_3")
    name = normal.pop("severity")
    normal.pop("detail")
    engine = engine_factory([normal])
    cfg = make_config(tmp_path, engine.url)
    service(cfg, from_id=0).run_cycle()
    rows = records(cfg)
    assert rows[0]["status"] == "done"
    assert len(runner_log(tmp_path)) == 1


def test_plan_alert_does_not_consume_daily_limit(tmp_path: Path, engine_factory) -> None:
    normal = plan_alert(alert_id=2, rule_type="pct_change", rule_id="pct_up_3")
    normal.pop("severity")
    normal.pop("detail")
    cfg = make_config(
        tmp_path,
        "",
        limits=default_limits(max_runs_per_day=1),
        triggers=None,
    )
    engine = engine_factory([plan_alert(alert_id=1), normal])
    cfg = make_config(
        tmp_path,
        engine.url,
        limits=default_limits(max_runs_per_day=1),
    )
    service(cfg, from_id=0).run_cycle()
    rows = records(cfg)
    assert [(row["alert_id"], row["status"]) for row in rows] == [
        (1, "skipped"),
        (2, "done"),
    ]
    assert rows[0]["reason"] == "plan_alert"
    assert len(runner_log(tmp_path)) == 1


def test_plan_alert_does_not_set_cooldown(tmp_path: Path, engine_factory) -> None:
    normal = plan_alert(alert_id=3, rule_type="pct_change", rule_id="pct_up_3")
    normal.pop("severity")
    normal.pop("detail")
    engine = engine_factory([plan_alert(alert_id=1), normal])
    cfg = make_config(tmp_path, engine.url)
    service(cfg, from_id=0).run_cycle()
    saved = state(cfg)
    assert "002553.SZ|plan:card-1" not in saved["last_run_ts"]
    assert saved["last_run_ts"]["002553.SZ|pct_up_3"] == "2026-11-03T09:35:00+08:00"


def test_plan_alert_advances_cursor(tmp_path: Path, engine_factory) -> None:
    engine = engine_factory([plan_alert(alert_id=7)])
    cfg = make_config(tmp_path, engine.url)
    service(cfg, from_id=0).run_cycle()
    assert state(cfg)["last_alert_id"] == 7
    service(cfg).run_cycle()
    assert len(records(cfg)) == 1


def test_plan_alert_in_queue_overflow_is_still_plan_alert(tmp_path: Path, engine_factory) -> None:
    normal = plan_alert(alert_id=2, rule_type="pct_change", rule_id="pct_up_3")
    normal.pop("severity")
    normal.pop("detail")
    engine = engine_factory([plan_alert(alert_id=1), normal])
    cfg = make_config(
        tmp_path,
        engine.url,
        limits=default_limits(max_queue=1),
    )
    service(cfg, from_id=0).run_cycle()
    rows = records(cfg)
    assert [(row["alert_id"], row["status"], row.get("reason")) for row in rows] == [
        (1, "skipped", "plan_alert"),
        (2, "done", None),
    ]
