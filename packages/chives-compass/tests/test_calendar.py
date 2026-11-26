from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from chives_compass.calendar import (
    DateSetCalendar,
    DegradedCalendar,
    WeekdayCalendar,
    build_calendar,
    in_alert_suppression,
    in_refresh_window,
    load_calendar_file,
    trading_state,
)
from chives_compass.models import CN_TZ


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=CN_TZ)


CAL = DateSetCalendar([date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)])


@pytest.mark.parametrize(
    "moment,expected",
    [
        (at(2026, 11, 3, 9, 0), "pre_open"),
        (at(2026, 11, 3, 9, 30), "open"),
        (at(2026, 11, 3, 11, 29), "open"),
        (at(2026, 11, 3, 11, 30), "lunch"),
        (at(2026, 11, 3, 13, 0), "open"),
        (at(2026, 11, 3, 14, 59), "open"),
        (at(2026, 11, 3, 15, 0), "closed"),
        (at(2026, 11, 7, 10, 0), "holiday"),
    ],
)
def test_trading_state(moment, expected):
    assert trading_state(moment, CAL) == expected


def test_weekday_calendar():
    calendar = WeekdayCalendar()
    assert calendar.is_trading_day(at(2026, 11, 3, 10)) is True
    assert calendar.is_trading_day(at(2026, 11, 7, 10)) is False


def test_degraded_calendar_status():
    assert DegradedCalendar().status == "degraded"


def test_build_calendar_file(tmp_path):
    path = tmp_path / "cal.json"
    path.write_text(json.dumps(["2026-11-02", "2026-11-03"]), encoding="utf-8")
    calendar = build_calendar("file", path)
    assert calendar.status == "ok"
    assert calendar.is_trading_day(at(2026, 11, 3, 10)) is True
    assert calendar.is_trading_day(at(2026, 11, 4, 10)) is False


def test_build_calendar_missing_file_degrades(tmp_path):
    calendar = build_calendar("file", tmp_path / "missing.json")
    assert calendar.status == "degraded"
    assert calendar.is_trading_day(at(2026, 11, 3, 10)) is True


def test_build_calendar_weekdays():
    assert isinstance(build_calendar("weekdays", None), WeekdayCalendar)


def test_load_calendar_file_invalid(tmp_path):
    path = tmp_path / "cal.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        load_calendar_file(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_calendar_file(path)
    path.write_text('["bad"]', encoding="utf-8")
    with pytest.raises(ValueError):
        load_calendar_file(path)


def test_refresh_windows():
    assert in_refresh_window(at(2026, 11, 3, 9, 26), CAL) is True
    assert in_refresh_window(at(2026, 11, 3, 9, 20), CAL) is False
    assert in_refresh_window(at(2026, 11, 3, 15, 2), CAL) is True
    assert in_refresh_window(at(2026, 11, 3, 15, 10), CAL) is False
    assert in_refresh_window(at(2026, 11, 7, 9, 26), CAL) is False


def test_alert_suppression_open_and_close():
    assert in_alert_suppression(at(2026, 11, 3, 9, 40), open_minutes=15) is True
    assert in_alert_suppression(at(2026, 11, 3, 9, 46), open_minutes=15) is False
    assert in_alert_suppression(at(2026, 11, 3, 14, 56), close_minutes=5) is True
    assert in_alert_suppression(at(2026, 11, 3, 14, 50), close_minutes=5) is False
    assert in_alert_suppression(at(2026, 11, 3, 12, 0)) is False
