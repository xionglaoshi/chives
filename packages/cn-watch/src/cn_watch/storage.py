"""Append-only JSONL logs and atomic state snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_TMP_NAME = ".state.json.tmp"


class FileStore:
    def __init__(self, out_dir: str | Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.out_dir / "alerts.jsonl"
        self.polls_path = self.out_dir / "polls.jsonl"
        self.state_path = self.out_dir / "state.json"

    def existing_alerts(self) -> list[dict[str, Any]]:
        if not self.alerts_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.alerts_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _append(self, path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, allow_nan=False))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def write_alert(self, alert: dict[str, Any]) -> None:
        self._append(self.alerts_path, alert)

    def write_poll(self, row: dict[str, Any]) -> None:
        self._append(self.polls_path, row)

    def write_state(self, state: dict[str, Any]) -> None:
        tmp = self.out_dir / STATE_TMP_NAME
        data = json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2)
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
