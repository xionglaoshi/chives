from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from market_watch.models import CN_TZ
from tests.test_engine import OPEN, make_engine

DAY = date(2026, 11, 3)


def seed_points(engine, day, labels, start=(9, 30)):
    hour, minute = start
    for index, label in enumerate(labels):
        engine.store.save_breadth_point(
            day, label, up=100 + index, down=200 + index, flat=5,
            limit_up=10, limit_down=2,
        )


def test_session_minutes_full_has_240_points():
    assert len(make_engine.__globals__["Engine"]._session_minutes(999)) == 240


def test_session_minutes_prefix():
    labels = make_engine.__globals__["Engine"]._session_minutes(3)
    assert labels == ["09:30", "09:31", "09:32"]


def test_breadth_series_empty_is_gap(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "closed"
    payload = engine.breadth_series_dict(DAY.isoformat())
    assert payload["ok"] is True
    assert payload["points"] == []
    assert payload["gaps"] is True
    assert "reason" in payload


def test_breadth_series_points_and_gaps(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "closed"
    seed_points(engine, DAY, ["09:30", "09:31"])
    payload = engine.breadth_series_dict(DAY.isoformat())
    assert len(payload["points"]) == 2
    assert payload["gaps"] is True


def test_breadth_series_full_day_no_gap(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "closed"
    labels = engine._session_minutes(240)
    seed_points(engine, DAY, labels)
    payload = engine.breadth_series_dict(DAY.isoformat())
    assert len(payload["points"]) == 240
    assert payload["gaps"] is False


def test_breadth_series_restart_window_sets_gap(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "closed"
    labels = engine._session_minutes(240)
    seed_points(engine, DAY, labels[30:])
    payload = engine.breadth_series_dict(DAY.isoformat())
    assert payload["gaps"] is True


def test_breadth_series_point_fields(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "closed"
    seed_points(engine, DAY, ["09:30"])
    point = engine.breadth_series_dict(DAY.isoformat())["points"][0]
    assert set(point) == {"t", "up", "down", "flat", "limit_up", "limit_down"}


def test_breadth_series_bad_date(tmp_path):
    engine = make_engine(tmp_path)
    assert engine.breadth_series_dict("2026-02-30")["error"]["code"] == "bad_request"


def test_breadth_series_non_trading_date(tmp_path):
    engine = make_engine(tmp_path)
    assert engine.breadth_series_dict("2026-10-31")["error"]["code"] == "not_trading_day"


def test_record_breadth_point_only_when_open(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    engine.store.save_breadth_point(DAY, "10:30", up=1, down=2, flat=0,
                                    limit_up=3, limit_down=4)
    engine.store.prune_breadth_series(date(2026, 1, 1))
    engine.tick(OPEN + timedelta(seconds=20))
    points = engine.breadth_series_dict(DAY.isoformat())["points"]
    assert any(point["t"] == "10:30" for point in points)


def test_record_breadth_point_ignored_when_closed(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "closed"
    engine.poll_breadth(OPEN)
    assert engine.store.load_breadth_series(DAY) == []


def test_breadth_point_first_sample_wins(tmp_path):
    engine = make_engine(tmp_path)
    engine.store.save_breadth_point(DAY, "09:30", up=1, down=1, flat=0,
                                    limit_up=1, limit_down=1)
    engine.store.save_breadth_point(DAY, "09:30", up=9, down=9, flat=9,
                                    limit_up=9, limit_down=9)
    points = engine.store.load_breadth_series(DAY)
    assert points[0]["up"] == 1


def test_prune_breadth_series(tmp_path):
    engine = make_engine(tmp_path)
    engine.store.save_breadth_point(date(2026, 1, 5), "09:30", up=1, down=1, flat=0,
                                    limit_up=0, limit_down=0)
    engine.store.save_breadth_point(DAY, "09:30", up=1, down=1, flat=0,
                                    limit_up=0, limit_down=0)
    assert engine.store.prune_breadth_series(date(2026, 2, 1)) == 1


def test_breadth_health_reports_points(tmp_path):
    engine = make_engine(tmp_path)
    seed_points(engine, DAY, ["09:30"])
    health = engine.health_dict()
    assert health["sources"]["breadth_series"]["ok"] is True
    assert health["sources"]["breadth_series"]["points"] == 1
