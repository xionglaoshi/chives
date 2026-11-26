from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

from chives_signals.calendar import TradingCalendar
from chives_signals.snapshots import SnapshotService
from chives_signals.store import HubStore
from tests.support import NOW, FakePortfolio, at


def make_service(tmp_path: Path, calendar: TradingCalendar | None = None, *, close=time(15, 5), enabled=True):
    store = HubStore(tmp_path / "hub.db")
    portfolio = FakePortfolio()
    portfolio.snapshot = {
        "market_value_cny": 21000.0,
        "total_assets_cny": 26000.0,
        "pnl_cny": 1000.0,
        "day_pnl_cny": 500.0,
        "quote_time": "2026-11-04 15:00:00",
    }
    service = SnapshotService(
        store,
        portfolio,
        calendar or TradingCalendar.from_file(None),
        close_time=close,
        enabled=enabled,
    )
    return store, portfolio, service


def test_before_close_no_snapshot(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path)
    assert service.maybe_write(at(14, 59)) is None
    assert store.get_snapshot(date(2026, 11, 4)) is None


def test_at_close_writes(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path)
    row = service.maybe_write(at(15, 5))
    assert row is not None
    assert row["market_value_cny"] == 21000.0
    assert row["quote_time"] == "2026-11-04 15:00:00"


def test_idempotent(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path)
    assert service.maybe_write(at(15, 5)) is not None
    assert service.maybe_write(at(15, 6)) is None
    assert store.count_snapshots() == 1


def test_weekend_skipped(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path)
    assert service.maybe_write(at(15, 30, day=7)) is None
    assert store.count_snapshots() == 0


def test_holiday_skipped(tmp_path: Path) -> None:
    calendar_path = tmp_path / "cal.json"
    calendar_path.write_text(json.dumps(["2026-11-03", "2026-11-05"]), encoding="utf-8")
    calendar = TradingCalendar.from_file(calendar_path)
    store, _, service = make_service(tmp_path, calendar)
    assert service.maybe_write(at(15, 30, day=4)) is None
    assert service.maybe_write(at(15, 30, day=5)) is not None


def test_disabled(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path, enabled=False)
    assert service.maybe_write(at(16)) is None
    assert store.count_snapshots() == 0


def test_no_backfill(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path)
    assert service.maybe_write(at(15, 30, day=5)) is not None
    assert store.get_snapshot(date(2026, 11, 4)) is None
    assert store.get_snapshot(date(2026, 11, 5)) is not None


def test_missing_portfolio_values(tmp_path: Path) -> None:
    store, portfolio, service = make_service(tmp_path)
    portfolio.snapshot = None
    assert service.maybe_write(at(15, 30)) is None
    assert store.count_snapshots() == 0


def test_due_flag(tmp_path: Path) -> None:
    _, _, service = make_service(tmp_path)
    assert not service.due(at(14, 0))
    assert service.due(at(15, 5))


def test_custom_close_time(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path, close=time(14, 30))
    assert service.maybe_write(at(14, 29)) is None
    assert service.maybe_write(at(14, 30)) is not None


def test_today_only_after_close(tmp_path: Path) -> None:
    store, _, service = make_service(tmp_path)
    assert service.maybe_write(at(9, 0)) is None
    assert store.count_snapshots() == 0
