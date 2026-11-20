from __future__ import annotations

from datetime import date, datetime

import pytest

from market_watch.models import CN_TZ
from market_watch.store import AlertStore

NOW = datetime(2026, 11, 3, 15, 10, tzinfo=CN_TZ)
DAY = date(2026, 11, 3)


def test_pool_day_roundtrip(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_pool_day(DAY, "zt", count=2, rows=[{"code": "600000.SH"}],
                        fetched_at=NOW)
    record = store.load_pool_day(DAY, "zt")
    assert record["count"] == 2 and record["available"] is True
    assert record["rows"] == [{"code": "600000.SH"}]
    assert record["reason"] is None


def test_pool_day_upsert(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_pool_day(DAY, "zt", count=1, rows=[], fetched_at=NOW, available=False,
                        reason="no_data_from_source")
    store.save_pool_day(DAY, "zt", count=3, rows=[{"code": "A"}], fetched_at=NOW)
    record = store.load_pool_day(DAY, "zt")
    assert record["count"] == 3 and record["available"] is True
    assert record["reason"] is None


def test_pool_day_kinds(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    for kind in ("zt", "zb"):
        store.save_pool_day(DAY, kind, count=0, rows=[], fetched_at=NOW, available=False,
                            reason="no_data_from_source")
    assert store.pool_day_kinds(DAY) == {"zt", "zb"}


def test_pool_day_summary(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_pool_day(DAY, "zt", count=1, rows=[{"code": "A"}], fetched_at=NOW)
    summary = store.pool_day_summary()
    assert summary["days"] == 1 and summary["available_rows"] == 1


def test_breadth_series_roundtrip(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_breadth_point(DAY, "09:30", up=1, down=2, flat=3, limit_up=4, limit_down=5)
    rows = store.load_breadth_series(DAY)
    assert rows == [{"t": "09:30", "up": 1, "down": 2, "flat": 3,
                     "limit_up": 4, "limit_down": 5}]


def test_breadth_series_summary(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_breadth_point(DAY, "09:30", up=1, down=2, flat=0, limit_up=0, limit_down=0)
    summary = store.breadth_series_summary()
    assert summary == {"days": 1, "points": 1, "last_day": "2026-11-03"}


def test_day_stats_extended_columns(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_day_stats(DAY, amount_yuan=1e9, limit_up=30, limit_down=2, broken=5,
                         max_streak=4, updated_at=NOW)
    row = store.load_day_stats(DAY)
    assert (row["limit_up"], row["limit_down"], row["broken"], row["max_streak"]) == (
        30, 2, 5, 4
    )


def test_day_stats_keeps_old_non_null(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_day_stats(DAY, amount_yuan=1e9, limit_up=30, updated_at=NOW)
    store.save_day_stats(DAY, amount_yuan=None, limit_up=None, limit_down=2, updated_at=NOW)
    row = store.load_day_stats(DAY)
    assert row["amount_yuan"] == 1e9 and row["limit_up"] == 30
    assert row["limit_down"] == 2


def test_pool_day_before(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_pool_day(date(2026, 11, 2), "zt", count=1, rows=[{"code": "A"}],
                        fetched_at=NOW)
    assert store.pool_day_before(DAY) == "2026-11-02"


def test_breadth_point_fills_missing_limit_counts(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_breadth_point(DAY, "09:30", up=1, down=2, flat=0, limit_up=None, limit_down=None)
    store.save_breadth_point(DAY, "09:30", up=9, down=9, flat=9, limit_up=3, limit_down=1)
    row = store.load_breadth_series(DAY)[0]
    assert (row["up"], row["down"]) == (1, 2)
    assert (row["limit_up"], row["limit_down"]) == (3, 1)
