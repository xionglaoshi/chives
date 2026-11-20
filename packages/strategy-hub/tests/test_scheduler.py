from __future__ import annotations

from datetime import datetime
from pathlib import Path

from strategy_hub.scheduler import Scheduler

from .support import build_service


class FakeRunner:
    def __init__(self, *, latest: str = "2026-11-17", last: str | None = "2026-11-14") -> None:
        self.latest = latest
        self.last = last
        self.calls: list[str] = []
        self.failures = 0
        self.state = True

    def latest_trading_day(self) -> str | None:
        return self.latest

    def last_calculated(self) -> str | None:
        return self.last

    def has_state(self) -> bool:
        return self.state

    def update(self, day: str | None = None) -> None:
        self.calls.append(f"update:{day}")

    def step(self, day: str) -> None:
        self.calls.append(f"step:{day}")
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary engine failure")

    def replay(self, start: str, end: str) -> None:
        self.calls.append(f"replay:{start}:{end}")


def test_catch_up_steps_the_latest_trading_day_and_ingests_alerts(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    runner = FakeRunner()
    scheduler = Scheduler(service, runner, retry_delay_seconds=0)
    assert scheduler.catch_up() is True
    assert runner.calls == ["step:2026-11-17"]
    assert service.alerts_payload(0, 100)["next_id"] == 3
    assert scheduler.snapshot()["status"] == "success"


def test_run_day_does_not_restep_an_already_computed_day(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    runner = FakeRunner(last="2026-11-17")
    scheduler = Scheduler(service, runner, retry_delay_seconds=0)
    assert scheduler.run_day("2026-11-17") is True
    assert runner.calls == []
    assert service.alerts_payload(0, 100)["next_id"] == 3
    assert scheduler.snapshot()["status"] == "success"


def test_catch_up_replays_when_no_state_exists(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    runner = FakeRunner(last=None)
    scheduler = Scheduler(service, runner, start_date="2020-01-01", retry_delay_seconds=0)
    assert scheduler.catch_up() is True
    assert runner.calls == ["replay:2020-01-01:2026-11-17"]


def test_catch_up_replays_when_the_database_has_no_incremental_state(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    runner = FakeRunner(last="2026-11-14")
    runner.state = False
    scheduler = Scheduler(service, runner, start_date="2020-01-01", retry_delay_seconds=0)
    assert scheduler.catch_up() is True
    assert runner.calls == ["replay:2020-01-01:2026-11-17"]


def test_run_day_retries_three_times_then_succeeds(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    runner = FakeRunner()
    runner.failures = 2
    scheduler = Scheduler(service, runner, retry_delay_seconds=0)
    assert scheduler.run_day("2026-11-17", force=True) is True
    assert runner.calls == ["update:2026-11-17", "step:2026-11-17"] * 3
    assert scheduler.snapshot()["attempts"] == 3


def test_schedule_only_runs_on_weekdays_after_1535(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    runner = FakeRunner()
    scheduler = Scheduler(service, runner, retry_delay_seconds=0)
    assert scheduler.tick(datetime(2026, 11, 17, 15, 34)) is False
    assert runner.calls == []
    assert scheduler.tick(datetime(2026, 11, 17, 15, 35)) is True
    assert runner.calls == ["update:2026-11-17", "step:2026-11-17"]
