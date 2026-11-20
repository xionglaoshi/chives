"""Read API used by the surge rule engine (T155).

``DailyStore`` opens the SQLite file read-only and caches the calendar, the
security master and each code's latest adjustment factor.  Adjusted prices are
computed, never stored twice.
"""

from __future__ import annotations

import bisect
import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from .db import connect, default_db_path, init_schema
from .limits import (
    ALL_BOARDS,
    is_delisting_name,
    is_st_name,
    limit_price_from,
    limit_ratio_for,
    round_half_up_to_cent,
    round_price,
)


@dataclass(frozen=True)
class Bar:
    code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None
    adj_factor: float


def _as_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


class DailyStore:
    def __init__(self, db_path: Path | str | None = None, *, readonly: bool = True) -> None:
        self.path = Path(db_path).expanduser() if db_path else default_db_path()
        self.conn = connect(self.path, readonly=readonly)
        if not readonly:
            init_schema(self.conn)
        try:
            self._calendar = [
                date.fromisoformat(row["date"])
                for row in self.conn.execute("SELECT date FROM calendar ORDER BY date")
            ]
        except sqlite3.OperationalError as exc:
            raise RuntimeError(f"database is not initialized: {self.path}") from exc
        self._securities: dict[str, sqlite3.Row] = {
            str(row["code"]): row for row in self.conn.execute("SELECT * FROM securities")
        }
        self._names: dict[str, list[tuple[str, str]]] = {}
        for row in self.conn.execute("SELECT code, start_date, name FROM names ORDER BY code, start_date"):
            self._names.setdefault(str(row["code"]), []).append((str(row["start_date"]), str(row["name"])))
        self._latest_factor: dict[str, float] = {}
        self._all_latest_factors: dict[str, float] | None = None

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DailyStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- calendar / master -------------------------------------------------
    def calendar(self, start: date | str | None = None, end: date | str | None = None) -> list[date]:
        days = self._calendar
        low = 0 if start is None else bisect.bisect_left(days, _as_date(start))
        high = len(days) if end is None else bisect.bisect_right(days, _as_date(end))
        return days[low:high]

    def latest_trading_day(self, on_or_before: date | str | None = None) -> date | None:
        if not self._calendar:
            return None
        if on_or_before is None:
            return self._calendar[-1]
        idx = bisect.bisect_right(self._calendar, _as_date(on_or_before))
        return self._calendar[idx - 1] if idx else None

    def trading_days_since(self, list_date: date | str, day: date | str) -> int:
        start = _as_date(list_date)
        end = _as_date(day)
        return bisect.bisect_right(self._calendar, end) - bisect.bisect_left(self._calendar, start)

    def security(self, code: str) -> sqlite3.Row | None:
        return self._securities.get(code)

    def all_codes(self) -> list[str]:
        return sorted(self._securities)

    def name_on(self, code: str, day: date | str | None = None) -> str | None:
        target = None if day is None else _as_date(day).isoformat()
        rows = self._names.get(code) or []
        chosen: str | None = None
        for start, name in rows:
            if target is None or start <= target:
                chosen = name
            else:
                break
        if chosen:
            return chosen
        row = self._securities.get(code)
        return None if row is None else str(row["name"])

    def is_st(self, code: str, day: date | str) -> bool:
        return is_st_name(self.name_on(code, day))

    def universe(self, day: date | str) -> list[str]:
        target = _as_date(day)
        target_iso = target.isoformat()
        out: list[str] = []
        for code in sorted(self._securities):
            row = self._securities[code]
            if str(row["board"]) not in ALL_BOARDS:
                continue
            list_date = row["list_date"]
            if not list_date or str(list_date) > target_iso:
                continue
            delist_date = row["delist_date"]
            if delist_date and str(delist_date) < target_iso:
                continue
            name = self.name_on(code, target)
            if is_st_name(name) or is_delisting_name(name):
                continue
            if self.trading_days_since(str(list_date), target) < 60:
                continue
            out.append(code)
        return out

    # -- bars --------------------------------------------------------------
    def _latest_factor_for(self, code: str) -> float | None:
        if code in self._latest_factor:
            return self._latest_factor[code]
        row = self.conn.execute(
            "SELECT adj_factor FROM bars WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        if row is None:
            return None
        self._latest_factor[code] = float(row["adj_factor"])
        return self._latest_factor[code]

    def _all_factors(self) -> dict[str, float]:
        if self._all_latest_factors is None:
            rows = self.conn.execute(
                "SELECT b.code, b.adj_factor FROM bars b "
                "JOIN (SELECT code, MAX(date) AS md FROM bars GROUP BY code) m "
                "ON b.code=m.code AND b.date=m.md"
            )
            self._all_latest_factors = {str(row["code"]): float(row["adj_factor"]) for row in rows}
        return self._all_latest_factors

    def _to_bar(self, row: sqlite3.Row, latest_factor: float | None) -> Bar:
        factor = float(row["adj_factor"])
        scale = 1.0 if latest_factor is None else factor / latest_factor
        if scale == 1.0:
            prices = (float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))
        else:
            prices = tuple(float(round_price(float(row[key]) * scale)) for key in ("open", "high", "low", "close"))
        return Bar(
            code=str(row["code"]),
            date=date.fromisoformat(str(row["date"])),
            open=prices[0],
            high=prices[1],
            low=prices[2],
            close=prices[3],
            volume=int(row["volume"]),
            amount=None if row["amount"] is None else float(row["amount"]),
            adj_factor=factor,
        )

    def bars(
        self,
        code: str,
        start: date | str | None = None,
        end: date | str | None = None,
        adjust: str = "qfq",
    ) -> list[Bar]:
        if adjust not in ("qfq", "none"):
            raise ValueError("adjust must be 'qfq' or 'none'")
        clauses = ["code=?"]
        params: list[object] = [code]
        if start is not None:
            clauses.append("date>=?")
            params.append(_as_date(start).isoformat())
        if end is not None:
            clauses.append("date<=?")
            params.append(_as_date(end).isoformat())
        sql = f"SELECT * FROM bars WHERE {' AND '.join(clauses)} ORDER BY date"
        rows = list(self.conn.execute(sql, params))
        latest: float | None = None
        if adjust == "qfq":
            latest = self._latest_factor_for(code)
            if latest is None:
                return []
        return [self._to_bar(row, latest) for row in rows]

    def bars_on(
        self,
        day: date | str,
        codes: list[str] | None = None,
        adjust: str = "qfq",
    ) -> dict[str, Bar]:
        if adjust not in ("qfq", "none"):
            raise ValueError("adjust must be 'qfq' or 'none'")
        day_iso = _as_date(day).isoformat()
        factors = self._all_factors() if adjust == "qfq" else {}
        out: dict[str, Bar] = {}
        if codes is None:
            rows = self.conn.execute("SELECT * FROM bars WHERE date=?", (day_iso,))
            for row in rows:
                code = str(row["code"])
                latest = None if adjust == "none" else factors.get(code)
                out[code] = self._to_bar(row, latest)
            return out
        for offset in range(0, len(codes), 900):
            chunk = codes[offset : offset + 900]
            marks = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"SELECT * FROM bars WHERE date=? AND code IN ({marks})", [day_iso, *chunk]
            )
            for row in rows:
                code = str(row["code"])
                latest = None if adjust == "none" else factors.get(code)
                out[code] = self._to_bar(row, latest)
        return out

    def previous_bar(self, code: str, day: date | str) -> Bar | None:
        row = self.conn.execute(
            "SELECT * FROM bars WHERE code=? AND date<? ORDER BY date DESC LIMIT 1",
            (code, _as_date(day).isoformat()),
        ).fetchone()
        return None if row is None else self._to_bar(row, None)

    def latest_date(self, code: str) -> date | None:
        row = self.conn.execute("SELECT MAX(date) AS md FROM bars WHERE code=?", (code,)).fetchone()
        return None if row is None or row["md"] is None else date.fromisoformat(str(row["md"]))

    # -- limit-up ----------------------------------------------------------
    def limit_ratio(self, code: str, day: date | str) -> Decimal | None:
        target = _as_date(day)
        row = self._securities.get(code)
        if row is None:
            return None
        list_date = row["list_date"]
        if not list_date or self.trading_days_since(str(list_date), target) <= 5:
            return None
        return limit_ratio_for(str(row["board"]), target, self.is_st(code, target))

    def limit_up_price(self, code: str, day: date | str) -> float | None:
        ratio = self.limit_ratio(code, day)
        if ratio is None:
            return None
        prev = self.previous_bar(code, day)
        if prev is None:
            return None
        return float(limit_price_from(prev.close, ratio))

    def is_limit_up(self, code: str, day: date | str) -> bool:
        target = _as_date(day)
        row = self.conn.execute(
            "SELECT close FROM bars WHERE code=? AND date=?", (code, target.isoformat())
        ).fetchone()
        if row is None:
            return False
        price = self.limit_up_price(code, target)
        if price is None:
            return False
        return round_half_up_to_cent(float(row["close"])) == round_half_up_to_cent(price)
