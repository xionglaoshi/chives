from __future__ import annotations

import json
from pathlib import Path

import pytest

from cn_watch import storage
from cn_watch.storage import FileStore


def test_alert_and_poll_append_and_roundtrip(tmp_path: Path):
    store = FileStore(tmp_path)
    store.write_alert({"id": 1, "code": "002553.SZ", "rule_id": "r"})
    store.write_alert({"id": 2, "code": "002553.SZ", "rule_id": "r"})
    store.write_poll({"t": "2026-11-03T09:30:00+08:00", "ok": True})
    assert [row["id"] for row in store.existing_alerts()] == [1, 2]
    lines = (tmp_path / "polls.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["ok"] is True


def test_existing_alerts_skips_broken_lines(tmp_path: Path):
    path = tmp_path / "alerts.jsonl"
    path.write_text('{"id": 1}\nnot json\n\n{"id": 2}\n', encoding="utf-8")
    assert [row["id"] for row in FileStore(tmp_path).existing_alerts()] == [1, 2]


def test_state_is_written_atomically(tmp_path: Path):
    store = FileStore(tmp_path)
    store.write_state({"updated_at": "t1"})
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["updated_at"] == "t1"
    assert not (tmp_path / storage.STATE_TMP_NAME).exists()


def test_failed_replace_keeps_the_previous_state_and_cleans_up(tmp_path: Path, monkeypatch):
    store = FileStore(tmp_path)
    store.write_state({"updated_at": "good"})

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        store.write_state({"updated_at": "bad"})
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["updated_at"] == "good"
    assert not (tmp_path / storage.STATE_TMP_NAME).exists()
