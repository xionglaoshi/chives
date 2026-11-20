from __future__ import annotations

from datetime import date, timedelta

from cn_daily_store.db import connect
from cn_daily_store.quality import run_check, summary_lines

from conftest import add_bar, add_security, make_db


def weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


class FakeGateway:
    def __init__(self, codes: set[str] | None = None, status: str = "ok") -> None:
        self.codes = codes or set()
        self.status = status
        self.calls = 0

    def limit_pool(self, day):
        self.calls += 1
        return self.status, sorted(self.codes), len(self.codes)


def test_check_detects_ohlc_negative_calendar_and_change(tmp_path):
    calendar = weekdays(date(2019, 1, 2), 200)
    days = calendar[60:]
    outside = date(2020, 2, 1)  # Saturday, not in the calendar
    path = make_db(tmp_path, calendar=calendar)
    conn = connect(path, readonly=False)
    add_security(conn, "600000.SH", "sh_main", calendar[0].isoformat(), "测试股")
    add_bar(conn, "600000.SH", days[0].isoformat(), 10.0, factor=1.0)
    add_bar(conn, "600000.SH", days[1].isoformat(), 12.0, factor=1.0)  # +20% > 10.5%
    add_bar(conn, "600000.SH", days[2].isoformat(), 9.0, factor=1.4)  # ex-rights, qfq +5%
    add_bar(conn, "600000.SH", days[3].isoformat(), 11.0, high=10.0)  # high < close
    add_bar(conn, "600000.SH", days[4].isoformat(), -1.0)  # negative
    add_bar(conn, "600000.SH", outside.isoformat(), 11.0)  # outside calendar
    conn.commit()
    conn.close()
    report = run_check(path, pool_days=15, gateway=FakeGateway())
    counts = report["issue_counts"]
    assert counts.get("calendar", 0) >= 1
    assert counts.get("ohlc", 0) >= 1
    assert counts.get("negative", 0) >= 1
    assert counts.get("daily_change", 0) >= 1
    assert report["annotation_counts"].get("ex_rights", 0) >= 1
    assert report["securities"] == 1
    assert report["limit_pool"]["overall_agreement"] == 1.0
    assert summary_lines(report)


def test_limit_pool_mismatch_reports_both_sides(tmp_path):
    days = weekdays(date(2020, 1, 2), 120)
    path = make_db(tmp_path, calendar=days)
    conn = connect(path, readonly=False)
    add_security(conn, "600000.SH", "sh_main", days[0].isoformat(), "测试股")
    for day in days[:30]:
        add_bar(conn, "600000.SH", day.isoformat(), 10.0)
    conn.commit()
    conn.close()
    gateway = FakeGateway({"600000.SH"})
    report = run_check(path, pool_days=1, gateway=gateway)
    item = report["limit_pool"]["days"][0]
    assert item["theirs"] == 1
    assert item["ours"] == 0
    assert item["agreement"] == 0.0
    assert item["theirs_only"] == ["600000.SH"]
    assert item["reasons"]["theirs_only"][0]["reason"]


def test_limit_pool_skips_unavailable_dates(tmp_path):
    days = weekdays(date(2020, 1, 2), 120)
    path = make_db(tmp_path, calendar=days)
    conn = connect(path, readonly=False)
    add_security(conn, "600000.SH", "sh_main", days[0].isoformat(), "测试股")
    add_bar(conn, "600000.SH", days[0].isoformat(), 10.0)
    conn.commit()
    conn.close()
    report = run_check(path, pool_days=5, gateway=FakeGateway(status="unavailable"))
    assert report["limit_pool"]["days"] == []
    assert report["limit_pool"]["overall_agreement"] is None
