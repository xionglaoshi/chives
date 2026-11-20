"""Cursor state must be atomic and records must stay append-only."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hub_trigger.store import FastJudgeStore, State, StateError


def test_missing_state_returns_none(tmp_path: Path) -> None:
    assert FastJudgeStore(tmp_path / "state").load_state() is None


def test_state_roundtrip(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.save_state(State(last_trigger_id=12, last_run_ts={"card|1|execute": "2026-11-03T09:39:00+08:00"}))
    loaded = store.load_state()
    assert loaded is not None
    assert loaded.last_trigger_id == 12
    assert loaded.last_run_ts["card|1|execute"].startswith("2026-11-03")


def test_state_payload_key(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.save_state(State(last_trigger_id=0))
    payload = json.loads(store.state_path.read_text(encoding="utf-8"))
    assert payload == {"last_trigger_id": 0, "last_run_ts": {}}


def test_no_temp_file_left_after_save(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.save_state(State(last_trigger_id=1))
    assert not (store.state_dir / ".state.json.tmp").exists()


def test_state_alias_last_alert_id(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.state_path.write_text('{"last_alert_id": 9}', encoding="utf-8")
    loaded = store.load_state()
    assert loaded is not None
    assert loaded.last_trigger_id == 9


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "x",
        {"last_trigger_id": -1},
        {"last_trigger_id": True},
        {"last_trigger_id": 1.5},
        {"last_trigger_id": "1"},
        {"last_trigger_id": 1, "last_run_ts": []},
        {"last_trigger_id": 1, "last_run_ts": {"a": 1}},
    ],
)
def test_corrupt_state_is_rejected(tmp_path: Path, payload: object) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.state_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StateError):
        store.load_state()


def test_invalid_json_state_is_rejected(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.state_path.write_text("{", encoding="utf-8")
    with pytest.raises(StateError):
        store.load_state()


def test_failed_replace_keeps_previous_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.save_state(State(last_trigger_id=3))
    before = store.state_path.read_text(encoding="utf-8")

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.save_state(State(last_trigger_id=4))
    assert store.state_path.read_text(encoding="utf-8") == before
    assert not (store.state_dir / ".state.json.tmp").exists()


def test_append_and_read_records(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.append_record({"trigger_id": 1, "status": "done"})
    store.append_record({"trigger_id": 2, "status": "skipped", "reason": "cooldown"})
    rows = store.read_records()
    assert [row["trigger_id"] for row in rows] == [1, 2]


def test_malformed_record_lines_are_skipped(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.records_path.write_text('not-json\n{"trigger_id": 2}\n\n', encoding="utf-8")
    assert store.read_records() == [{"trigger_id": 2}]


def test_missing_records_file_is_empty(tmp_path: Path) -> None:
    assert FastJudgeStore(tmp_path / "state").read_records() == []


def test_stop_file_detection(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    assert store.stop_requested() is False
    store.stop_path.write_text("", encoding="utf-8")
    assert store.stop_requested() is True


def test_state_dir_is_created(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "state"
    store = FastJudgeStore(target)
    assert target.is_dir()
    assert store.state_path.parent == target


def test_unicode_state_is_written(tmp_path: Path) -> None:
    store = FastJudgeStore(tmp_path / "state")
    store.save_state(State(last_trigger_id=1, last_run_ts={"观察": "2026-11-03T09:39:00+08:00"}))
    text = store.state_path.read_text(encoding="utf-8")
    assert "观察" in text
