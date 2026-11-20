"""The trigger pipeline: baseline, filters, budgets, queue, runner and write-back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from hub_trigger.clock import SHANGHAI
from hub_trigger.hub import HubError
from hub_trigger.service import cooldown_key
from hub_trigger.store import FastJudgeStore

from support import (
    NOW,
    context,
    default_limits,
    make_config,
    records,
    runner_config,
    runner_log,
    service,
    state,
    trigger,
)


def _zero_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text('{"last_trigger_id": 0}', encoding="utf-8")


def _seed(
    hub: Any,
    tmp_path: Path,
    *trigger_ids: int,
    context_kwargs: dict[str, Any] | None = None,
) -> None:
    _zero_state(tmp_path)
    for trigger_id in trigger_ids:
        row = trigger(trigger_id, card_id=trigger_id, to_state="execute")
        hub.add(
            row,
            context(row, **(context_kwargs or {})),
        )


def _first_judgement(hub: Any) -> dict[str, Any]:
    return hub.judgements[0]["body"]


def test_first_run_sets_baseline_and_skips_history(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory([trigger(1), trigger(2), trigger(3)])
    config = make_config(tmp_path, hub.url)
    result = service(config).run_cycle()
    assert result.baseline == 3
    assert state(config)["last_trigger_id"] == 3
    assert records(config) == []
    assert hub.judgements == []


def test_first_run_empty_hub_baseline_zero(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory([])
    config = make_config(tmp_path, hub.url)
    assert service(config).run_cycle().baseline == 0
    assert state(config)["last_trigger_id"] == 0


def test_processes_trigger_after_baseline(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory([trigger(1)])
    config = make_config(tmp_path, hub.url)
    svc = service(config)
    svc.run_cycle()
    row = trigger(2, ts="2026-11-03T09:40:00+08:00")
    hub.add(row, context(row))
    result = svc.run_cycle()
    assert result.processed == 1
    assert len(hub.judgements) == 1
    assert _first_judgement(hub)["action"] == "observe"
    rec = records(config)[0]
    assert rec["trigger_id"] == 2
    assert rec["status"] == "done"
    assert rec["result"] == "written"
    assert rec["action"] == "observe"


def test_from_id_replays_history(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1, 2)
    config = make_config(tmp_path, hub.url)
    svc = service(config, from_id=0)
    svc.run_cycle()
    assert len(hub.judgements) == 2


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("观察｜等待量能｜10:30｜跌破 10.2 放弃", "observe"),
        ("等待确认｜量能不足｜10:30｜跌破 10.2 放弃", "await_confirm"),
        ("按预案执行｜条件满足｜10:30｜止损 10.2", "execute"),
        ("放弃｜跌破放弃线｜收盘前｜不再跟", "abandon"),
        ("按计划退出｜跌破止损｜立即｜止损 10.2", "exit"),
    ],
)
def test_action_mapping_to_hub_enum(
    hub_factory: Callable[..., Any], tmp_path: Path, text: str, action: str
) -> None:
    hub = hub_factory([trigger(1)])
    hub.add(trigger(1), context(trigger(1)))
    config = make_config(tmp_path, hub.url, runner=runner_config(tmp_path, mode="text", text=text))
    _zero_state(tmp_path)
    service(config).run_cycle()
    assert _first_judgement(hub)["action"] == action
    assert records(config)[0]["action"] == action


def test_stale_trigger_is_skipped(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory([trigger(1, ts="2026-11-03T09:30:00+08:00")])
    hub.add(trigger(1, ts="2026-11-03T09:30:00+08:00"), context())
    config = make_config(tmp_path, hub.url)
    svc = service(config)
    svc.run_cycle()
    row = trigger(2, ts="2026-11-03T09:30:00+08:00")
    hub.add(row, context(row))
    svc.run_cycle()
    assert records(config)[-1]["reason"] == "stale_trigger"
    assert hub.judgements == []


def test_trigger_at_exact_max_age_is_not_stale(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1, ts="2026-11-03T09:38:00+08:00")
    hub = hub_factory([row])
    hub.add(row, context(row))
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    service(config).run_cycle()
    service(config).run_cycle()
    # First cycle is the baseline; second processes exactly 120 seconds old.
    assert records(config)[0]["status"] == "done"


def test_future_trigger_is_not_stale(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1, ts="2026-11-03T09:45:00+08:00")
    hub = hub_factory([row])
    hub.add(row, context(row))
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    service(config).run_cycle()
    service(config).run_cycle()
    assert records(config)[0]["status"] == "done"


def test_invalid_timestamp_is_skipped(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1, ts="not-a-time")
    hub = hub_factory([row])
    hub.add(row, context(row))
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    service(config).run_cycle()
    service(config).run_cycle()
    assert records(config)[0]["reason"] == "invalid_trigger_ts"


def test_cooldown_same_card_and_state(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    row = trigger(2, ts="2026-11-03T09:40:00+08:00", card_id=1, to_state="execute")
    hub.add(row, context(row))
    svc.run_cycle()
    assert records(config)[-1]["reason"] == "cooldown"
    assert len(hub.judgements) == 1


def test_cooldown_uses_trigger_ts_not_wall_clock(
    hub_factory: Callable[..., Any], tmp_path: Path
) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    # The second trigger's own ts is 10 minutes after the first: cooldown expired.
    row = trigger(2, ts="2026-11-03T09:49:00+08:00", card_id=1, to_state="execute")
    hub.add(row, context(row))
    svc.run_cycle()
    assert records(config)[-1]["status"] == "done"


def test_different_to_state_is_not_cooled_down(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    row = trigger(2, ts="2026-11-03T09:40:00+08:00", card_id=1, to_state="abandon", kind="card_abandon")
    hub.add(row, context(row))
    svc.run_cycle()
    assert records(config)[-1]["status"] == "done"


def test_regime_cooldown_key_is_kind_and_reason(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    first = trigger(1, kind="regime", card_id=None, to_state="observe", reason="环境转弱")
    hub.add(first, context(first))
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    same = trigger(2, kind="regime", card_id=None, to_state="observe", reason="环境转弱", ts="2026-11-03T09:40:00+08:00")
    hub.add(same, context(same))
    svc.run_cycle()
    assert records(config)[-1]["reason"] == "cooldown"
    other = trigger(3, kind="regime", card_id=None, to_state="observe", reason="环境转强", ts="2026-11-03T09:40:30+08:00")
    hub.add(other, context(other))
    svc.run_cycle()
    assert records(config)[-1]["status"] == "done"


def test_cooldown_persists_across_restart(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    service(config).run_cycle()
    service(config).run_cycle()
    row = trigger(2, ts="2026-11-03T09:40:00+08:00", card_id=1, to_state="execute")
    hub.add(row, context(row))
    service(config).run_cycle()
    assert records(config)[-1]["reason"] == "cooldown"


def test_daily_limit(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1, 2)
    config = make_config(tmp_path, hub.url, limits=default_limits(max_runs_per_day=1))
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert [row["status"] for row in records(config)] == ["done", "skipped"]
    assert records(config)[1]["reason"] == "daily_limit"
    assert len(hub.judgements) == 1


def test_daily_limit_counts_failed_runs(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1, 2)
    config = make_config(
        tmp_path,
        hub.url,
        limits=default_limits(max_runs_per_day=1),
        runner=runner_config(tmp_path, mode="fail"),
    )
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["status"] == "failed"
    assert records(config)[1]["reason"] == "daily_limit"


def test_daily_limit_resets_on_next_beijing_date(
    hub_factory: Callable[..., Any], tmp_path: Path
) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url, limits=default_limits(max_runs_per_day=1))
    FastJudgeStore(config.state_dir).append_record(
        {
            "trigger_id": 0,
            "kind": "card_execute",
            "code": "",
            "status": "done",
            "started_at": "2026-11-02T09:40:00+08:00",
        }
    )
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[-1]["status"] == "done"


def test_queue_overflow_keeps_latest(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1, 2, 3, 4, 5)
    config = make_config(tmp_path, hub.url, limits=default_limits(max_queue=2))
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    rows = records(config)
    assert [row["trigger_id"] for row in rows] == [1, 2, 3, 4, 5]
    assert [row.get("reason") for row in rows[:3]] == ["queue_overflow"] * 3
    assert [row["status"] for row in rows[3:]] == ["done", "done"]
    assert [item["id"] for item in hub.judgements] == [4, 5]


def test_stop_file_skips_everything(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1, 2)
    config = make_config(tmp_path, hub.url)
    (config.state_dir / "STOP").parent.mkdir(parents=True, exist_ok=True)
    (config.state_dir / "STOP").write_text("", encoding="utf-8")
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert [row["reason"] for row in records(config)] == ["kill_switch", "kill_switch"]
    assert hub.judgements == []


def test_stop_takes_priority_over_stale(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1, ts="2026-11-03T09:00:00+08:00")
    hub = hub_factory([row])
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    (config.state_dir / "STOP").parent.mkdir(parents=True, exist_ok=True)
    (config.state_dir / "STOP").write_text("", encoding="utf-8")
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["reason"] == "kill_switch"


def test_context_not_ready_is_no_context(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1, context_ready=False)
    hub = hub_factory([row])
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["reason"] == "no_context"
    assert not any("/context" in path for _method, path in hub.requests)
    assert hub.judgements == []


def test_context_http_error_is_no_context(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1)
    hub = hub_factory([row])
    hub.error_ids.add(1)
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["reason"] == "no_context"


def test_context_business_error_is_no_context(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1)
    hub = hub_factory([row])
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["reason"] == "no_context"


def test_no_context_is_not_retried(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1, context_ready=False)
    hub = hub_factory([row])
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    before_contexts = sum(1 for _method, path in hub.requests if "/context" in path)
    svc.run_cycle()
    assert sum(1 for _method, path in hub.requests if "/context" in path) == before_contexts
    assert len(records(config)) == 1


def test_dry_run_does_not_start_runner(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    svc = service(config, dry_run=True)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["reason"] == "dry_run"
    assert runner_log(tmp_path) == []
    assert hub.judgements == []
    assert state(config)["last_trigger_id"] == 1


def test_dry_run_still_applies_stale_check(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    row = trigger(1, ts="2026-11-03T09:00:00+08:00")
    hub = hub_factory([row])
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config, dry_run=True)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["reason"] == "stale_trigger"


def test_dry_run_does_not_count_toward_daily_limit(
    hub_factory: Callable[..., Any], tmp_path: Path
) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url, limits=default_limits(max_runs_per_day=1))
    service(config, dry_run=True).run_cycle()
    row = trigger(2, card_id=2, ts="2026-11-03T09:40:00+08:00")
    hub.add(row, context(row))
    service(config).run_cycle()
    assert records(config)[-1]["status"] == "done"


def test_runner_failure_is_recorded(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url, runner=runner_config(tmp_path, mode="fail"))
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    rec = records(config)[0]
    assert rec["status"] == "failed"
    assert rec["error"] == "runner 退出码 1"
    assert "boom" not in json.dumps(rec, ensure_ascii=False)
    assert hub.judgements == []


def test_runner_timeout_is_recorded(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(
        tmp_path,
        hub.url,
        limits=default_limits(run_timeout_seconds=0.3),
        runner=runner_config(tmp_path, mode="slow"),
    )
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["status"] == "timeout"
    assert hub.judgements == []


def test_unparsed_output_is_recorded_and_not_written(
    hub_factory: Callable[..., Any], tmp_path: Path
) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(
        tmp_path, hub.url, runner=runner_config(tmp_path, mode="text", text="这是一段分析，没有四段格式")
    )
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    rec = records(config)[0]
    assert rec["status"] == "done"
    assert rec["result"] == "unparsed"
    assert "action" not in rec
    assert hub.judgements == []


def test_judgement_rejected_is_recorded(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    hub.reject_ids.add(1)
    config = make_config(tmp_path, hub.url)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    rec = records(config)[0]
    assert rec["result"] == "judgement_rejected"
    assert rec["reason_code"] == "bad_value"


def test_judgement_transport_failure_is_rejected(
    hub_factory: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    svc = service(config)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise HubError("down")

    monkeypatch.setattr(svc.client, "judge", boom)
    svc.run_cycle()
    svc.run_cycle()
    assert records(config)[0]["reason_code"] == "hub_unreachable"


def test_records_do_not_contain_context(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    row = trigger(1)
    hub.add(row, context(row, private_marker="HOLDINGS_SECRET_ABC"))
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    text = (config.state_dir / "analyses.jsonl").read_text(encoding="utf-8")
    assert "HOLDINGS_SECRET_ABC" not in text
    assert "prompt" not in text
    assert "context" not in text
    assert "作战卡全文" not in text


def test_records_do_not_contain_model_output(
    hub_factory: Callable[..., Any], tmp_path: Path
) -> None:
    marker = "MODEL_OUTPUT_MARKER_XYZ"
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(
        tmp_path,
        hub.url,
        runner=runner_config(tmp_path, mode="text", text=f"观察｜{marker}｜10:30｜边界"),
    )
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    text = (config.state_dir / "analyses.jsonl").read_text(encoding="utf-8")
    assert marker not in text


def test_record_has_duration_and_no_prompt_fields(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    rec = records(config)[0]
    assert isinstance(rec["duration_ms"], int)
    assert rec["duration_ms"] >= 0
    assert set(rec).issubset(
        {"trigger_id", "kind", "code", "status", "duration_ms", "started_at", "finished_at", "action", "result", "reason_code", "error"}
    )


def test_skip_record_has_no_started_at(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    svc = service(config, dry_run=True)
    svc.run_cycle()
    svc.run_cycle()
    rec = records(config)[0]
    assert "started_at" not in rec
    assert rec["status"] == "skipped"


def test_restart_does_not_reprocess(hub_factory: Callable[..., Any], tmp_path: Path) -> None:
    hub = hub_factory()
    _seed(hub, tmp_path, 1)
    config = make_config(tmp_path, hub.url)
    service(config).run_cycle()
    service(config).run_cycle()
    before_posts = sum(1 for method, _path in hub.requests if method == "POST")
    service(config).run_cycle()
    assert sum(1 for method, _path in hub.requests if method == "POST") == before_posts
    assert len(records(config)) == 1


def test_large_context_is_truncated_in_prompt(
    hub_factory: Callable[..., Any], tmp_path: Path
) -> None:
    hub = hub_factory()
    row = trigger(1)
    hub.add(row, context(row, blob="汉" * 20000))
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    svc.run_cycle()
    svc.run_cycle()
    prompt = runner_log(tmp_path)[0]["prompt"]
    block = prompt.split("<context_data>", 1)[1].split("</context_data>", 1)[0]
    assert len(block.encode("utf-8")) <= 12 * 1024
    assert prompt.count("汉") < 5000


def test_context_marker_does_not_leak_into_logs(
    hub_factory: Callable[..., Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    hub = hub_factory()
    row = trigger(1)
    hub.add(row, context(row, private_marker="HOLDINGS_SECRET_ABC"))
    config = make_config(tmp_path, hub.url)
    _zero_state(tmp_path)
    svc = service(config)
    with caplog.at_level("INFO"):
        svc.run_cycle()
        svc.run_cycle()
    assert "HOLDINGS_SECRET_ABC" not in caplog.text


def test_cooldown_key_for_cards_and_regime() -> None:
    assert cooldown_key(trigger(1, card_id=7, to_state="execute")) == "card|7|execute"
    assert (
        cooldown_key(trigger(1, kind="regime", card_id=None, reason=" 环境  转弱 "))
        == "regime|环境 转弱"
    )
    assert cooldown_key(trigger(1, kind="emergency", card_id=None, reason="指数下跌")) == "emergency|指数下跌"
