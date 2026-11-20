"""Persistent daily read budget.

Every upstream read reserves units *before* the request and settles to the number of
resources actually returned afterwards.  Reserving first is what makes concurrent
callers unable to overspend; a crash in the middle can only over-count, never under-count.
The state file is replaced atomically and guarded by a file lock so separate server
processes sharing the same file still respect one budget.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Callable, Iterator

try:  # POSIX only; Windows would fall back to the in-process lock.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]


class BudgetError(RuntimeError):
    """The state file could not be read or written."""


@dataclass(frozen=True)
class BudgetSnapshot:
    used_today: int
    remaining: int
    limit: int
    reset_at_epoch: int
    reset_at: str

    def short(self) -> dict[str, int]:
        return {"used_today": self.used_today, "remaining": self.remaining}


def local_now() -> datetime:
    return datetime.now().astimezone()


class DailyBudget:
    def __init__(
        self,
        limit: int,
        path: Path,
        *,
        now: Callable[[], datetime] = local_now,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        self._limit = limit
        self._path = Path(path)
        self._now = now
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def _local_now(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            return current.astimezone()
        return current

    @staticmethod
    def _reset_at(current: datetime) -> datetime:
        tomorrow = current.date() + timedelta(days=1)
        return datetime.combine(tomorrow, dt_time.min, tzinfo=current.tzinfo)

    def _snapshot(self, current: datetime, used: int) -> BudgetSnapshot:
        reset = self._reset_at(current)
        return BudgetSnapshot(
            used_today=used,
            remaining=max(0, self._limit - used),
            limit=self._limit,
            reset_at_epoch=int(reset.timestamp()),
            reset_at=reset.isoformat(timespec="seconds"),
        )

    def _read(self) -> tuple[str, int]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return "", 0
        try:
            value = json.loads(raw)
        except ValueError:
            return "", 0
        if not isinstance(value, dict):
            return "", 0
        date = value.get("date")
        used = value.get("used")
        if not isinstance(date, str) or not date:
            return "", 0
        if isinstance(used, bool) or not isinstance(used, int) or used < 0:
            return "", 0
        return date, min(used, self._limit)

    def _write(self, date: str, used: int) -> None:
        payload = json.dumps({"date": date, "used": used}, separators=(",", ":"))
        parent = self._path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=".budget-", suffix=".tmp", dir=parent)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError as exc:
            raise BudgetError("the X budget state file is not writable") from exc

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(str(self._path) + ".lock", "a+")
        except OSError as exc:
            raise BudgetError("the X budget state file is not writable") from exc
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _current(self, current: datetime) -> tuple[str, int]:
        today = current.date().isoformat()
        date, used = self._read()
        if date != today:
            return today, 0
        return today, used

    def snapshot(self) -> BudgetSnapshot:
        with self._lock, self._file_lock():
            current = self._local_now()
            today, used = self._current(current)
            self._write(today, used)
            return self._snapshot(current, used)

    def reserve(self, count: int) -> tuple[bool, BudgetSnapshot]:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("count must be a non-negative integer")
        with self._lock, self._file_lock():
            current = self._local_now()
            today, used = self._current(current)
            if used + count > self._limit:
                self._write(today, used)
                return False, self._snapshot(current, used)
            used += count
            self._write(today, used)
            return True, self._snapshot(current, used)

    def settle(self, reserved: int, actual: int) -> BudgetSnapshot:
        if actual < 0:
            actual = 0
        with self._lock, self._file_lock():
            current = self._local_now()
            today, used = self._current(current)
            if actual < reserved:
                used = max(0, used - (reserved - actual))
            elif actual > reserved:
                used = min(self._limit, used + (actual - reserved))
            self._write(today, used)
            return self._snapshot(current, used)

    def release(self, reserved: int) -> BudgetSnapshot:
        return self.settle(reserved, 0)
