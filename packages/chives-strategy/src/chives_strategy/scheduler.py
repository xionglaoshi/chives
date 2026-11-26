"""After-close scheduler: daily store update, engine step, alert table fill."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Protocol

from cn_daily_store import DailyStore

from .service import HubService

logger = logging.getLogger(__name__)


class EngineRunner(Protocol):
    def latest_trading_day(self) -> str | None: ...

    def last_calculated(self) -> str | None: ...

    def has_state(self) -> bool: ...

    def update(self, day: str | None = None) -> None: ...

    def step(self, day: str) -> None: ...

    def replay(self, start: str, end: str) -> None: ...


class SubprocessRunner:
    """Runs the two local CLIs; strategy-hub never fetches market data itself."""

    def __init__(
        self,
        *,
        daily_db: Path,
        surge_db: Path,
        surge_state: Path,
        python: str | None = None,
    ) -> None:
        self.daily_db = Path(daily_db)
        self.surge_db = Path(surge_db)
        self.surge_state = Path(surge_state)
        self.python = python or sys.executable

    def _run(self, args: list[str]) -> None:
        completed = subprocess.run(
            [self.python, *args],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit {completed.returncode}"
            raise RuntimeError(f"{args[1]} 失败：{tail}")

    def latest_trading_day(self) -> str | None:
        try:
            store = DailyStore(self.daily_db)
        except FileNotFoundError:
            return None
        try:
            latest = store.latest_trading_day()
        finally:
            store.close()
        return None if latest is None else latest.isoformat()

    def has_state(self) -> bool:
        return self.surge_state.is_file()

    def last_calculated(self) -> str | None:
        if not self.surge_db.is_file():
            return None
        import sqlite3

        conn = sqlite3.connect(f"file:{self.surge_db}?mode=ro", uri=True, timeout=10.0)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='last_date'").fetchone()
        finally:
            conn.close()
        return None if row is None else str(row[0])

    def update(self, day: str | None = None) -> None:
        args = ["-m", "cn_daily_store", "--db", str(self.daily_db), "update"]
        if day:
            args.extend(["--date", day])
        self._run(args)

    def step(self, day: str) -> None:
        self._run(
            [
                "-m",
                "surge_engine",
                "--db",
                str(self.daily_db),
                "--output",
                str(self.surge_db),
                "--state",
                str(self.surge_state),
                "step",
                "--date",
                day,
            ]
        )

    def replay(self, start: str, end: str) -> None:
        self._run(
            [
                "-m",
                "surge_engine",
                "--db",
                str(self.daily_db),
                "--output",
                str(self.surge_db),
                "--state",
                str(self.surge_state),
                "replay",
                "--start",
                start,
                "--end",
                end,
                "--no-csv",
            ]
        )


class Scheduler:
    def __init__(
        self,
        service: HubService,
        runner: EngineRunner,
        *,
        schedule: time = time(15, 35),
        retries: int = 3,
        retry_delay_seconds: float = 30.0,
        start_date: str = "2020-01-01",
        clock: Any = None,
    ) -> None:
        self.service = service
        self.runner = runner
        self.schedule = schedule
        self.retries = max(1, retries)
        self.retry_delay_seconds = retry_delay_seconds
        self.start_date = start_date
        self.clock = clock or (lambda: datetime.now())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "idle"
        self._last_run: str | None = None
        self._last_success: str | None = None
        self._last_error: str | None = None
        self._attempts = 0

    # -- state ------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "last_run": self._last_run,
            "last_success": self._last_success,
            "last_error": self._last_error,
            "attempts": self._attempts,
            "schedule": self.schedule.strftime("%H:%M"),
            "retries": self.retries,
        }

    def _record(self, *, status: str, day: str, error: str | None = None, attempts: int = 0) -> None:
        self._status = status
        self._last_run = day
        self._attempts = attempts
        self._last_error = error
        if status == "success":
            self._last_success = day
            self.service.alerts.set_meta("scheduler.last_success", day)
        if error is not None:
            self.service.alerts.set_meta("scheduler.last_error", error)
        self.service.alerts.set_meta("scheduler.status", status)
        self.service.alerts.set_meta("scheduler.last_run", day)

    # -- startup ----------------------------------------------------------
    def catch_up(self) -> bool:
        latest = self.runner.latest_trading_day()
        if latest is None:
            self._record(status="failed", day="", error="交易日历为空或日线库不存在")
            return False
        last = self.runner.last_calculated()
        if last is not None and last >= latest:
            self._status = "idle"
            self._last_success = last
            return False
        self._status = "running"
        try:
            if last is None or not self.runner.has_state():
                self.runner.replay(self.start_date, latest)
            else:
                self.runner.step(latest)
            self.service.ingest_events(latest)
        except Exception as exc:  # noqa: BLE001 - reported through /health
            logger.exception("chives-strategy catch-up failed")
            self._record(status="failed", day=latest, error=str(exc), attempts=1)
            return False
        self._record(status="success", day=latest)
        return True

    # -- scheduled run ----------------------------------------------------
    def run_day(self, day: str, *, force: bool = False) -> bool:
        date.fromisoformat(day)  # validate YYYY-MM-DD
        stored = self.service.alerts.get_meta("scheduler.last_success")
        if not force and stored == day:
            return True
        calculated = self.runner.last_calculated()
        if not force and calculated is not None and calculated >= day and self.runner.has_state():
            # A replay or a previous daemon already produced this day; only fill alerts.
            written = self.service.ingest_events(day)
            logger.info("chives-strategy %s already computed, %s alerts", day, written)
            self._record(status="success", day=day)
            return True
        last_error: str | None = None
        for attempt in range(1, self.retries + 1):
            self._status = "running"
            self._attempts = attempt
            try:
                self.runner.update(day)
                latest = self.runner.latest_trading_day()
                if latest is None or latest < day:
                    self._record(status="not_trading_day", day=day, attempts=attempt)
                    return True
                if self.runner.has_state():
                    self.runner.step(day)
                else:
                    self.runner.replay(self.start_date, day)
                written = self.service.ingest_events(day)
                logger.info("chives-strategy %s computed, %s alerts", day, written)
                self._record(status="success", day=day, attempts=attempt)
                return True
            except Exception as exc:  # noqa: BLE001 - retried then reported
                last_error = str(exc)
                logger.warning("chives-strategy %s attempt %s/%s failed: %s", day, attempt, self.retries, exc)
                if attempt < self.retries:
                    self._stop.wait(self.retry_delay_seconds)
        self._record(status="failed", day=day, error=last_error, attempts=self.retries)
        return False

    def tick(self, now: datetime | None = None) -> bool:
        current = now or self.clock()
        if current.weekday() >= 5:
            return False
        if current.time() < self.schedule:
            return False
        day = current.date().isoformat()
        if self.service.alerts.get_meta("scheduler.last_run") == day:
            return False
        return self.run_day(day)

    # -- thread -----------------------------------------------------------
    def start(self, poll_seconds: float = 15.0) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, args=(poll_seconds,), name="chives-strategy-scheduler", daemon=True)
        self._thread.start()

    def _loop(self, poll_seconds: float) -> None:
        try:
            self.catch_up()
        except Exception:  # noqa: BLE001 - daemon must keep serving
            logger.exception("catch-up crashed")
        while not self._stop.wait(poll_seconds):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - keep the daemon alive
                logger.exception("scheduler tick crashed")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
