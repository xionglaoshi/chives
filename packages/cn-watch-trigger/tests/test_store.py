from __future__ import annotations

import json
from pathlib import Path

import pytest

from cn_watch_trigger.store import AnalysisStore, State, StateError


def test_state_roundtrip_is_atomic(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path / "state")
    store.save_state(State(last_alert_id=7, last_run_ts={"002553.SZ|pct_up_3": "2026-11-03T09:33:00+08:00"}))
    loaded = store.load_state()
    assert loaded == State(7, {"002553.SZ|pct_up_3": "2026-11-03T09:33:00+08:00"})
    assert not (store.state_dir / ".state.json.tmp").exists()
    assert json.loads(store.state_path.read_text(encoding="utf-8"))["last_alert_id"] == 7


def test_missing_state_returns_none(tmp_path: Path) -> None:
    assert AnalysisStore(tmp_path / "state").load_state() is None


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps([]),
        json.dumps({"last_alert_id": -1}),
        json.dumps({"last_alert_id": True}),
        json.dumps({"last_alert_id": "5"}),
        json.dumps({"last_alert_id": 5, "last_run_ts": []}),
        json.dumps({"last_alert_id": 5, "last_run_ts": {"x": 1}}),
    ],
)
def test_invalid_state_raises(tmp_path: Path, payload: str) -> None:
    store = AnalysisStore(tmp_path / "state")
    store.state_path.write_text(payload, encoding="utf-8")
    with pytest.raises(StateError):
        store.load_state()


def test_records_append_and_skip_bad_lines(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path / "state")
    store.append_record({"alert_id": 1, "status": "skipped", "reason": "dry_run"})
    store.append_record({"alert_id": 2, "status": "done"})
    with store.analyses_path.open("a", encoding="utf-8") as handle:
        handle.write("broken\n")
    assert [row["alert_id"] for row in store.read_records()] == [1, 2]


def test_analysis_write_is_atomic(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path / "state")
    path = store.write_analysis(3, "hello\n")
    assert path == store.state_dir / "analysis-3.md"
    assert path.read_text(encoding="utf-8") == "hello\n"
    assert not (store.state_dir / ".analysis-3.md.tmp").exists()


def test_stop_file_detection(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path / "state")
    assert not store.stop_requested()
    store.stop_path.write_text("stop", encoding="utf-8")
    assert store.stop_requested()
