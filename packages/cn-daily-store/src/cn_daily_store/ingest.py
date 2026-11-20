"""Backfill and daily update.

Every stock is fetched serially through one throttled HTTP client (at most three
requests per second).  Progress is stored per code in ``meta`` so an interrupted
backfill resumes where it stopped.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from .db import connect, init_schema, meta_get, meta_set, now_iso
from .http import FetchError, HttpClient, RateLimiter
from .sources import ExchangeListSource, RawBar, SinaFactorSource, TencentKlineSource

DEFAULT_START = date(2019, 1, 1)
FACTOR_TOLERANCE = 1e-4
MAX_ATTEMPTS = 3


@dataclass
class IngestStats:
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    rows: int = 0
    factor_refetch: int = 0


def _log(message: str) -> None:
    print(message, flush=True)


def factor_rows(raw: list[RawBar], qfq: list[RawBar]) -> list[tuple[RawBar, float]]:
    """Pair unadjusted bars with ``raw_close / qfq_close`` adjustment factors."""
    adjusted = {bar.date: bar.close for bar in qfq}
    out: list[tuple[RawBar, float]] = []
    last_factor = 1.0
    for bar in raw:
        qfq_close = adjusted.get(bar.date)
        if qfq_close is not None and qfq_close > 0:
            last_factor = round(qfq_close / bar.close, 8)
        out.append((bar, last_factor))
    return out


def factor_rows_from_points(raw: list[RawBar], points: list[tuple[date, float]]) -> list[tuple[RawBar, float]]:
    """Apply a dated adjustment factor (qfq/raw) to unadjusted bars."""
    ordered = sorted(points, key=lambda pair: pair[0])
    if not ordered:
        return [(bar, 1.0) for bar in raw]
    out: list[tuple[RawBar, float]] = []
    index = 0
    current = ordered[0][1]
    for bar in raw:
        while index < len(ordered) and ordered[index][0] <= bar.date:
            current = ordered[index][1]
            index += 1
        out.append((bar, current))
    return out


def rows_with_factors(
    kline: TencentKlineSource,
    sina: SinaFactorSource | None,
    code: str,
    raw: list[RawBar],
) -> list[tuple[RawBar, float]]:
    if not raw:
        return []
    points = sina.fetch(code) if sina is not None else []
    if points:
        return factor_rows_from_points(raw, points)
    qfq = kline.fetch_stock(code, adjust="qfq")
    if len(qfq) >= len(raw) - 2:
        return factor_rows(raw, qfq)
    # Tencent qfq is capped at 640 rows; walk backwards for older chunks.
    merged = {bar.date: bar for bar in qfq}
    cursor = min(merged) - timedelta(days=1) if merged else max(bar.date for bar in raw)
    earliest = min(bar.date for bar in raw)
    while cursor >= earliest:
        chunk = kline.fetch_stock_range(code, end=cursor, count=640, adjust="qfq")
        if not chunk:
            break
        for bar in chunk:
            merged[bar.date] = bar
        cursor = min(bar.date for bar in chunk) - timedelta(days=1)
    return factor_rows(raw, [merged[key] for key in sorted(merged)])


def _write_full(conn: sqlite3.Connection, code: str, rows: Iterable[tuple[RawBar, float]], start: date, end: date) -> int:
    payload = [
        (
            code,
            bar.date.isoformat(),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.amount,
            factor,
        )
        for bar, factor in rows
        if start <= bar.date <= end
    ]
    if not payload:
        return 0
    conn.execute("DELETE FROM bars WHERE code=?", (code,))
    conn.executemany(
        "INSERT INTO bars(code, date, open, high, low, close, volume, amount, adj_factor) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    return len(payload)


def _write_incremental(conn: sqlite3.Connection, code: str, rows: Iterable[tuple[RawBar, float]], after: date, end: date) -> int:
    payload = [
        (
            code,
            bar.date.isoformat(),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.amount,
            factor,
        )
        for bar, factor in rows
        if after < bar.date <= end
    ]
    conn.executemany(
        "INSERT INTO bars(code, date, open, high, low, close, volume, amount, adj_factor) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(code, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
        "low=excluded.low, close=excluded.close, volume=excluded.volume, "
        "amount=excluded.amount, adj_factor=excluded.adj_factor",
        payload,
    )
    return len(payload)


def _progress(conn: sqlite3.Connection, code: str) -> dict[str, object]:
    raw = meta_get(conn, f"progress:{code}")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_default(value: object) -> str:
    if isinstance(value, (date,)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _set_progress(conn: sqlite3.Connection, code: str, **values: object) -> None:
    data = _progress(conn, code)
    data.update(values)
    data["updated_at"] = now_iso()
    meta_set(
        conn,
        f"progress:{code}",
        json.dumps(data, ensure_ascii=False, sort_keys=True, default=_json_default),
    )


def ensure_calendar(conn: sqlite3.Connection, source: TencentKlineSource, *, full: bool = False) -> int:
    today = date.today()
    existing = conn.execute("SELECT COUNT(*) AS n FROM calendar").fetchone()["n"]
    days: set[date] = set()
    if full or not existing:
        for year in range(2018, today.year + 1):
            days.update(source.fetch_calendar_year(year, today))
        meta_set(conn, "calendar_source", "Tencent sh000001 daily bars (exchange calendar)")
    else:
        days.update(source.fetch_calendar_latest(30))
    conn.executemany(
        "INSERT INTO calendar(date) VALUES(?) ON CONFLICT(date) DO NOTHING",
        [(day.isoformat(),) for day in sorted(days)],
    )
    conn.commit()
    return len(days)


def ensure_securities(conn: sqlite3.Connection, source: ExchangeListSource, *, force: bool = False) -> dict[str, int]:
    stamp = meta_get(conn, "securities_refreshed_at")
    count = conn.execute("SELECT COUNT(*) AS n FROM securities").fetchone()["n"]
    stale = True
    if stamp:
        try:
            stale = (now_iso()[:10] > stamp[:10])
        except ValueError:
            stale = True
    if not force and count and not stale:
        return {}
    return source.refresh(conn)


def _selected_codes(conn: sqlite3.Connection, codes: list[str] | None, start: date) -> list[str]:
    if codes:
        return sorted(set(codes))
    rows = conn.execute(
        "SELECT code, list_date, delist_date FROM securities ORDER BY code"
    )
    out = []
    for row in rows:
        delist = row["delist_date"]
        if delist and str(delist) < start.isoformat():
            continue
        out.append(str(row["code"]))
    return out


def _update_codes(conn: sqlite3.Connection, codes: list[str] | None, target: date) -> list[str]:
    if codes:
        return sorted(set(codes))
    rows = conn.execute(
        "SELECT s.code, s.list_date, s.delist_date, "
        "EXISTS(SELECT 1 FROM bars b WHERE b.code=s.code) AS has_bars "
        "FROM securities s ORDER BY s.code"
    )
    out: list[str] = []
    for row in rows:
        list_date = row["list_date"]
        if list_date and str(list_date) > target.isoformat():
            continue
        delist = row["delist_date"]
        if delist and str(delist) < target.isoformat():
            continue
        recent = bool(list_date) and str(list_date) >= (target - timedelta(days=30)).isoformat()
        if row["has_bars"] or recent:
            out.append(str(row["code"]))
    return out


def _progress_line(stats: IngestStats, started: float, total: int) -> str:
    elapsed = max(0.001, time.monotonic() - started)
    rate = stats.done / elapsed
    remaining = max(0, total - stats.done - stats.skipped - stats.failed)
    eta = remaining / rate if rate > 0 else 0.0
    return (
        f"progress {stats.done}/{total} done, skipped {stats.skipped}, failed {stats.failed}, "
        f"bars {stats.rows}, {rate:.2f} stocks/s, eta {eta/60:.1f} min"
    )


def backfill(
    db_path: Path | str,
    *,
    start: date = DEFAULT_START,
    end: date | None = None,
    codes: list[str] | None = None,
    limit: int | None = None,
    force: bool = False,
    full_calendar: bool = True,
    refresh_securities: bool = True,
    client: HttpClient | None = None,
    kline_source: TencentKlineSource | None = None,
    exchange_source: ExchangeListSource | None = None,
    sina_source: SinaFactorSource | None = None,
    workers: int = 1,
) -> IngestStats:
    end = end or date.today()
    conn = connect(db_path, readonly=False)
    init_schema(conn)
    http = client or HttpClient()
    try:
        kline = kline_source or TencentKlineSource(http)
        exchange = exchange_source or ExchangeListSource(http)
        sina = sina_source
        if sina is None and kline_source is None:
            sina = SinaFactorSource(http)
        _log("refreshing trading calendar")
        ensure_calendar(conn, kline, full=full_calendar)
        if refresh_securities:
            _log("refreshing SSE/SZSE security lists")
            counts = ensure_securities(conn, exchange, force=True)
            _log(f"securities by board: {counts}")
        selected = _selected_codes(conn, codes, start)
        if limit is not None:
            selected = selected[:limit]
        stats = IngestStats(total=len(selected))
        started = time.monotonic()
        pending: list[str] = []
        priors: dict[str, dict[str, object]] = {}
        starts: dict[str, date] = {}
        for code in selected:
            prior = _progress(conn, code)
            priors[code] = prior
            if not force and prior.get("status") in {"done", "empty"}:
                stats.skipped += 1
                continue
            if not force and int(prior.get("attempts") or 0) >= MAX_ATTEMPTS:
                stats.skipped += 1
                continue
            row = conn.execute("SELECT list_date FROM securities WHERE code=?", (code,)).fetchone()
            code_start = start
            if row is not None and row["list_date"]:
                code_start = max(start, date.fromisoformat(str(row["list_date"])))
            pending.append(code)
            starts[code] = code_start

        def write_rows(code: str, rows: list[tuple[RawBar, float]]) -> None:
            try:
                written = _write_full(conn, code, rows, starts[code], end)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            stats.rows += written
            stats.done += 1
            _set_progress(
                conn, code, status="done" if written else "empty",
                last_date=max((bar.date for bar, _ in rows if starts[code] <= bar.date <= end), default=None),
                rows=written, attempts=0,
            )
            conn.commit()

        def fail(code: str, exc: Exception) -> None:
            attempts = int(priors[code].get("attempts") or 0) + 1
            stats.failed += 1
            _set_progress(conn, code, status="failed", attempts=attempts, error=str(exc)[:300])
            conn.commit()
            _log(f"{code} failed ({attempts}/{MAX_ATTEMPTS}): {exc}")

        if workers > 1 and pending:
            local = threading.local()
            shared_limiter = RateLimiter(1.0 / 3.0)

            def worker_sources() -> tuple[TencentKlineSource, SinaFactorSource]:
                if not hasattr(local, "kline"):
                    client = HttpClient(min_interval=1.0 / 3.0, limiter=shared_limiter)
                    local.kline = TencentKlineSource(client)
                    local.sina = SinaFactorSource(client)
                return local.kline, local.sina

            def task(code: str) -> list[tuple[RawBar, float]]:
                source, sina_source = worker_sources()
                raw = source.fetch_stock(code, adjust="none")
                return rows_with_factors(source, sina_source, code, raw)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(task, code): code for code in pending}
                for index, future in enumerate(as_completed(futures), start=1):
                    code = futures[future]
                    try:
                        write_rows(code, future.result())
                    except Exception as exc:  # noqa: BLE001 - keep the batch alive
                        fail(code, exc)
                    if index % 25 == 0 or index == len(pending):
                        _log(_progress_line(stats, started, len(selected)))
        else:
            for index, code in enumerate(pending, start=1):
                try:
                    raw = kline.fetch_stock(code, adjust="none")
                    write_rows(code, rows_with_factors(kline, sina, code, raw))
                except (FetchError, ValueError, OSError) as exc:
                    fail(code, exc)
                if index % 25 == 0 or index == len(pending):
                    _log(_progress_line(stats, started, len(selected)))
        latest_bar = conn.execute("SELECT MAX(date) AS d FROM bars").fetchone()["d"]
        meta_set(conn, "last_update_date", str(latest_bar or end.isoformat()))
        meta_set(conn, "last_backfill_at", now_iso())
        meta_set(conn, "backfill_start", start.isoformat())
        meta_set(conn, "backfill_end", end.isoformat())
        meta_set(conn, "data_source", "Tencent newfqkline raw + Sina qfq factor (Tencent qfq fallback)")
        meta_set(conn, "version", "1")
        conn.commit()
        return stats
    finally:
        conn.close()


def _stored_latest(conn: sqlite3.Connection, code: str) -> tuple[date, float] | None:
    row = conn.execute(
        "SELECT date, adj_factor FROM bars WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
    ).fetchone()
    if row is None:
        return None
    return date.fromisoformat(str(row["date"])), float(row["adj_factor"])


def update(
    db_path: Path | str,
    *,
    target: date | None = None,
    codes: list[str] | None = None,
    limit: int | None = None,
    refresh_securities: bool = True,
    client: HttpClient | None = None,
    kline_source: TencentKlineSource | None = None,
    exchange_source: ExchangeListSource | None = None,
    sina_source: SinaFactorSource | None = None,
) -> IngestStats:
    conn = connect(db_path, readonly=False)
    init_schema(conn)
    http = client or HttpClient()
    try:
        kline = kline_source or TencentKlineSource(http)
        exchange = exchange_source or ExchangeListSource(http)
        sina = sina_source
        if sina is None and kline_source is None:
            sina = SinaFactorSource(http)
        ensure_calendar(conn, kline, full=False)
        if refresh_securities:
            ensure_securities(conn, exchange, force=False)
        target = target or conn.execute("SELECT MAX(date) AS d FROM calendar").fetchone()["d"]
        target = date.fromisoformat(str(target))
        selected = _update_codes(conn, codes, target)
        if limit is not None:
            selected = selected[:limit]
        stats = IngestStats(total=len(selected))
        started = time.monotonic()
        for index, code in enumerate(selected, start=1):
            prior = _progress(conn, code)
            if int(prior.get("attempts") or 0) >= MAX_ATTEMPTS and not prior.get("last_date"):
                stats.skipped += 1
                continue
            stored = _stored_latest(conn, code)
            if stored is not None and stored[0] >= target:
                stats.skipped += 1
                continue
            row = conn.execute("SELECT list_date FROM securities WHERE code=?", (code,)).fetchone()
            list_start = DEFAULT_START
            if row is not None and row["list_date"]:
                list_start = max(DEFAULT_START, date.fromisoformat(str(row["list_date"])))
            try:
                if stored is None:
                    raw = kline.fetch_stock(code, adjust="none")
                    rows = rows_with_factors(kline, sina, code, raw)
                    written = _write_full(conn, code, rows, list_start, target)
                    stats.rows += written
                    stats.done += 1
                    _set_progress(conn, code, status="done" if written else "empty", last_date=target, rows=written, attempts=0)
                    conn.commit()
                    continue
                last_date, last_factor = stored
                raw = kline.fetch_stock(code, adjust="none", count=20)
                rows = rows_with_factors(kline, sina, code, raw)
                fresh = {bar.date: factor for bar, factor in rows}
                if last_date not in fresh:
                    raw = kline.fetch_stock(code, adjust="none")
                    rows = rows_with_factors(kline, sina, code, raw)
                    fresh = {bar.date: factor for bar, factor in rows}
                new_factor = fresh.get(last_date)
                changed = new_factor is not None and abs(new_factor / last_factor - 1.0) > FACTOR_TOLERANCE
                if changed:
                    raw = kline.fetch_stock(code, adjust="none")
                    rows = rows_with_factors(kline, sina, code, raw)
                    written = _write_full(conn, code, rows, list_start, target)
                    stats.factor_refetch += 1
                else:
                    written = _write_incremental(conn, code, rows, last_date, target)
                if written:
                    stats.rows += written
                    stats.done += 1
                else:
                    stats.skipped += 1
                _set_progress(
                    conn, code, status="done", last_date=max(last_date, target).isoformat(),
                    rows=int(prior.get("rows") or 0) + written, attempts=0,
                )
                conn.commit()
            except (FetchError, ValueError, OSError) as exc:
                attempts = int(prior.get("attempts") or 0) + 1
                stats.failed += 1
                _set_progress(conn, code, status="failed", attempts=attempts, error=str(exc)[:300])
                conn.commit()
                _log(f"[{index}/{len(selected)}] {code} failed ({attempts}/{MAX_ATTEMPTS}): {exc}")
            if index % 100 == 0 or index == len(selected):
                _log(_progress_line(stats, started, len(selected)))
        meta_set(conn, "last_update_date", target.isoformat())
        conn.commit()
        return stats
    finally:
        conn.close()
