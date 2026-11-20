from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from cn_daily_store.db import connect
from cn_daily_store.ingest import backfill, factor_rows, update
from cn_daily_store.sources import RawBar, SecurityRow


def weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


DAYS = weekdays(date(2020, 1, 2), 120)


def raw_bar(day: date, close: float) -> RawBar:
    return RawBar(day, close, close + 0.2, close - 0.2, close, 100000, 1_000_000.0)


@dataclass
class FakeKline:
    raw: dict[str, list[RawBar]]
    qfq: dict[str, list[RawBar]]
    days: list[date]

    def fetch_stock(self, code: str, *, adjust: str = "none", count: int = 2000) -> list[RawBar]:
        rows = self.raw.get(code, []) if adjust == "none" else self.qfq.get(code, [])
        return rows[-count:]

    def fetch_calendar_year(self, year: int, today: date) -> list[date]:
        return [day for day in self.days if day.year == year]

    def fetch_calendar_latest(self, days: int = 30) -> list[date]:
        return self.days[-days:]


class FakeExchange:
    def __init__(self, rows: list[SecurityRow]) -> None:
        self.rows = rows
        self.calls = 0

    def refresh(self, conn) -> dict[str, int]:
        self.calls += 1
        conn.executemany(
            "INSERT INTO securities(code, name, board, list_date, delist_date, updated_at) "
            "VALUES(?, ?, ?, ?, ?, '2026-01-01T00:00:00+08:00') "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name",
            [(r.code, r.name, r.board, r.list_date, r.delist_date) for r in self.rows],
        )
        conn.executemany(
            "INSERT INTO names(code, start_date, name) VALUES(?, ?, ?) "
            "ON CONFLICT(code, start_date) DO UPDATE SET name=excluded.name",
            [(r.code, r.list_date or "1990-01-01", r.name) for r in self.rows],
        )
        conn.commit()
        return {"sh_main": len(self.rows)}


def snapshot(raw: list[RawBar], qfq: list[RawBar]):
    return FakeKline({"600000.SH": raw}, {"600000.SH": qfq}, DAYS)


def test_factor_rows_uses_raw_over_qfq():
    raw = [raw_bar(DAYS[0], 10.0), raw_bar(DAYS[1], 11.0)]
    qfq = [raw_bar(DAYS[0], 9.0), raw_bar(DAYS[1], 11.0)]
    rows = factor_rows(raw, qfq)
    assert rows[0][1] == round(9.0 / 10.0, 8)
    assert rows[1][1] == 1.0


def test_backfill_and_idempotent_update(tmp_path):
    raw = [raw_bar(day, 10.0 + i * 0.1) for i, day in enumerate(DAYS[:60])]
    qfq = [replace(bar) for bar in raw]
    kline = snapshot(raw, qfq)
    exchange = FakeExchange([SecurityRow("600000.SH", "测试股", "sh_main", DAYS[0].isoformat(), None)])
    db = tmp_path / "daily.sqlite"
    stats = backfill(
        db, start=DAYS[0], end=DAYS[59], kline_source=kline, exchange_source=exchange,
        refresh_securities=True,
    )
    assert stats.done == 1 and stats.rows == 60
    conn = connect(db, readonly=False)
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 60
    assert conn.execute("SELECT COUNT(*) FROM calendar").fetchone()[0] == len(DAYS)
    conn.close()

    again = backfill(
        db, start=DAYS[0], end=DAYS[59], kline_source=kline, exchange_source=exchange,
        refresh_securities=True,
    )
    assert again.done == 0 and again.skipped == 1

    # A new trading day: update appends exactly one bar, a second run is a no-op.
    kline.raw["600000.SH"].append(raw_bar(DAYS[60], 16.0))
    kline.qfq["600000.SH"].append(raw_bar(DAYS[60], 16.0))
    kline.days = DAYS[:61]
    updated = update(db, target=DAYS[60], kline_source=kline, exchange_source=exchange, refresh_securities=False)
    assert updated.rows == 1
    again_update = update(db, target=DAYS[60], kline_source=kline, exchange_source=exchange, refresh_securities=False)
    assert again_update.rows == 0
    conn = connect(db, readonly=False)
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 61
    conn.close()


def test_factor_change_triggers_full_refetch(tmp_path):
    raw = [raw_bar(day, 10.0) for day in DAYS[:30]]
    qfq = [raw_bar(day, 10.0) for day in DAYS[:30]]
    kline = snapshot(raw, qfq)
    exchange = FakeExchange([SecurityRow("600000.SH", "测试股", "sh_main", DAYS[0].isoformat(), None)])
    db = tmp_path / "daily.sqlite"
    backfill(
        db, start=DAYS[0], end=DAYS[29], kline_source=kline, exchange_source=exchange,
        refresh_securities=True,
    )
    # A dividend rescales the whole forward-adjusted series: factor becomes 2.
    kline.qfq["600000.SH"] = [raw_bar(day, 5.0) for day in DAYS[:30]]
    kline.raw["600000.SH"].append(raw_bar(DAYS[30], 10.0))
    kline.qfq["600000.SH"].append(raw_bar(DAYS[30], 5.0))
    kline.days = DAYS[:31]
    stats = update(db, target=DAYS[30], kline_source=kline, exchange_source=exchange, refresh_securities=False)
    assert stats.factor_refetch == 1
    conn = connect(db, readonly=False)
    rows = conn.execute("SELECT adj_factor FROM bars WHERE code='600000.SH' ORDER BY date").fetchall()
    assert rows[0][0] == 0.5
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 31
    conn.close()


def test_update_handles_suspended_day(tmp_path):
    raw = [raw_bar(day, 10.0) for day in DAYS[:20]]
    qfq = [raw_bar(day, 10.0) for day in DAYS[:20]]
    kline = snapshot(raw, qfq)
    exchange = FakeExchange([SecurityRow("600000.SH", "测试股", "sh_main", DAYS[0].isoformat(), None)])
    db = tmp_path / "daily.sqlite"
    backfill(
        db, start=DAYS[0], end=DAYS[19], kline_source=kline, exchange_source=exchange,
        refresh_securities=True,
    )
    kline.days = DAYS[:21]  # DAYS[20] is a trading day but this stock has no bar
    stats = update(db, target=DAYS[20], kline_source=kline, exchange_source=exchange, refresh_securities=False)
    assert stats.rows == 0
    conn = connect(db, readonly=False)
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 20
    conn.close()


def test_factor_rows_from_points_forward_fill():
    from cn_daily_store.ingest import factor_rows_from_points

    raw = [raw_bar(DAYS[0], 10.0), raw_bar(DAYS[3], 10.0), raw_bar(DAYS[6], 10.0)]
    points = [(DAYS[2], 0.5), (DAYS[5], 0.8)]
    rows = factor_rows_from_points(raw, points)
    assert [factor for _, factor in rows] == [0.5, 0.5, 0.8]
