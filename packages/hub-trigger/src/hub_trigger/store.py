"""Atomic cursor state and append-only judgement records."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

STATE_TMP_NAME = ".state.json.tmp"


class StateError(Exception):
    """Raised when the persisted cursor is unreadable or invalid."""


@dataclass
class State:
    last_trigger_id: int | None = None
    last_run_ts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> "State":
        if not isinstance(payload, dict):
            raise StateError("state.json 必须是对象")
        raw_id = payload.get("last_trigger_id", payload.get("last_alert_id"))
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id < 0:
            raise StateError(f"state.json 的 last_trigger_id 非法: {raw_id!r}")
        raw_last_run = payload.get("last_run_ts", {})
        if not isinstance(raw_last_run, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_last_run.items()
        ):
            raise StateError("state.json 的 last_run_ts 非法")
        return cls(last_trigger_id=raw_id, last_run_ts=dict(raw_last_run))

    def payload(self) -> dict[str, Any]:
        return {
            "last_trigger_id": self.last_trigger_id,
            "last_run_ts": dict(self.last_run_ts),
        }


class FastJudgeStore:
    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "state.json"
        self.records_path = self.state_dir / "analyses.jsonl"
        self.stop_path = self.state_dir / "STOP"

    def load_state(self) -> State | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError(f"无法读取 state.json: {exc}") from exc
        return State.from_payload(payload)

    def save_state(self, state: State) -> None:
        tmp = self.state_dir / STATE_TMP_NAME
        data = json.dumps(state.payload(), ensure_ascii=False, allow_nan=False, indent=2)
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(data)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.state_path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def append_record(self, record: Mapping[str, Any]) -> None:
        with self.records_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(record), ensure_ascii=False, allow_nan=False))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_records(self) -> list[dict[str, Any]]:
        if not self.records_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            text = self.records_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return rows
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def stop_requested(self) -> bool:
        return self.stop_path.exists()
