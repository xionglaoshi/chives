from __future__ import annotations

from datetime import date, timedelta

import pytest

from cn_daily_store.db import connect
from cn_daily_store.store import DailyStore

from conftest import add_bar, add_security, make_db


def weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def seed(tmp_path, *, board="sh_main", name="测试股", list_date="2020-01-02"):
    days = weekdays(date(2020, 1, 2), 120)
    path = make_db(tmp_path, calendar=days)
    conn = connect(path, readonly=False)
    add_security(conn, "600000.SH", board, list_date, name)
    for index, day in enumerate(days[:80]):
        add_bar(conn, "600000.SH", day.isoformat(), 10.0 + index * 0.01)
    conn.commit()
    conn.close()
    return path, days


def test_qfq_conversion_and_suspension(tmp_path):
    path = tmp_path / "x.sqlite"
    days = weekdays(date(2020, 1, 2), 5)
    from cn_daily_store.db import init_schema

    conn = connect(path, readonly=False)
    init_schema(conn)
    conn.executemany("INSERT INTO calendar(date) VALUES(?)", [(d.isoformat(),) for d in days])
    add_security(conn, "600000.SH", "sh_main", "2019-01-02")
    add_bar(conn, "600000.SH", days[0].isoformat(), 10.0, factor=1.0)
    add_bar(conn, "600000.SH", days[1].isoformat(), 11.0, factor=1.1)
    conn.commit()
    conn.close()
    store = DailyStore(path)
    try:
        qfq = store.bars("600000.SH", adjust="qfq")
        assert [bar.close for bar in qfq] == [9.091, 11.0]
        raw = store.bars("600000.SH", adjust="none")
        assert [bar.close for bar in raw] == [10.0, 11.0]
        # days[2] has no bar: suspension is the absence of a row.
        assert store.bars("600000.SH", days[2], days[4]) == []
        assert store.previous_bar("600000.SH", days[3]).date == days[1]
    finally:
        store.close()


def test_universe_rules(tmp_path):
    days = weekdays(date(2020, 1, 2), 120)
    path = make_db(tmp_path, calendar=days)
    conn = connect(path, readonly=False)
    add_security(conn, "600000.SH", "sh_main", days[0].isoformat(), "正常股")
    add_security(conn, "600001.SH", "sh_main", days[0].isoformat(), "ST 风险")
    add_security(conn, "600002.SH", "sh_main", days[-1].isoformat(), "次新股")
    add_security(conn, "600003.SH", "sh_main", days[0].isoformat(), "退市海润", delist=days[-1].isoformat())
    add_security(conn, "300001.SZ", "chinext", days[0].isoformat(), "创业板股")
    conn.commit()
    conn.close()
    store = DailyStore(path)
    try:
        universe = store.universe(days[70])
        assert "600000.SH" in universe
        assert "300001.SZ" in universe
        assert "600001.SH" not in universe  # ST
        assert "600002.SH" not in universe  # listed < 60 trading days
        assert "600003.SH" not in universe  # delisting name
        assert store.universe(days[-1]) == ["300001.SZ", "600000.SH"]
    finally:
        store.close()


def test_limit_up_prices_main_and_st(tmp_path):
    days = weekdays(date(2021, 1, 4), 70)
    path = make_db(tmp_path, calendar=days)
    conn = connect(path, readonly=False)
    add_security(conn, "600000.SH", "sh_main", days[0].isoformat(), "正常股")
    add_security(conn, "600001.SH", "sh_main", days[0].isoformat(), "ST 风险")
    for index, day in enumerate(days[:11]):
        add_bar(conn, "600000.SH", day.isoformat(), 9.99 if index == 10 else 10.0)
        add_bar(conn, "600001.SH", day.isoformat(), 9.99 if index == 10 else 10.0)
    add_bar(conn, "600000.SH", days[11].isoformat(), 10.99)
    add_bar(conn, "600001.SH", days[11].isoformat(), 10.49)
    conn.commit()
    conn.close()
    store = DailyStore(path)
    try:
        assert store.limit_up_price("600000.SH", days[11]) == 10.99
        assert store.limit_up_price("600001.SH", days[11]) == 10.49
        assert store.is_limit_up("600000.SH", days[11]) is True
        assert store.is_limit_up("600001.SH", days[11]) is True
        assert store.is_st("600001.SH", days[11]) is True
        assert store.limit_ratio("600000.SH", days[2]) is None  # first five trading days
    finally:
        store.close()


def test_chinext_switch_and_star(tmp_path):
    days = weekdays(date(2020, 8, 3), 70)
    path = make_db(tmp_path, calendar=days)
    conn = connect(path, readonly=False)
    add_security(conn, "300001.SZ", "chinext", "2019-01-02")
    add_security(conn, "688001.SH", "star", "2019-01-02")
    for day in days:
        add_bar(conn, "300001.SZ", day.isoformat(), 10.0)
        add_bar(conn, "688001.SH", day.isoformat(), 10.0)
    conn.commit()
    conn.close()
    store = DailyStore(path)
    try:
        before = date(2020, 8, 21)
        after = date(2020, 8, 24)
        assert store.limit_up_price("300001.SZ", before) == 11.0
        assert store.limit_up_price("300001.SZ", after) == 12.0
        assert store.limit_up_price("688001.SH", after) == 12.0
    finally:
        store.close()


def test_name_history_picks_effective_name(tmp_path):
    path, days = seed(tmp_path)
    conn = connect(path, readonly=False)
    conn.execute(
        "INSERT INTO names(code, start_date, name) VALUES('600000.SH', ?, 'ST 测试')",
        (days[40].isoformat(),),
    )
    conn.commit()
    conn.close()
    store = DailyStore(path)
    try:
        assert store.name_on("600000.SH", days[30]) == "测试股"
        assert store.name_on("600000.SH", days[50]) == "ST 测试"
        assert store.is_st("600000.SH", days[50]) is True
        assert store.is_st("600000.SH", days[30]) is False
    finally:
        store.close()


def test_calendar_and_bars_on(tmp_path):
    path, days = seed(tmp_path)
    store = DailyStore(path)
    try:
        assert store.calendar(days[2], days[4]) == days[2:5]
        snapshot = store.bars_on(days[3])
        assert "600000.SH" in snapshot
        assert snapshot["600000.SH"].date == days[3]
        assert store.latest_trading_day(days[10]) == days[10]
    finally:
        store.close()
