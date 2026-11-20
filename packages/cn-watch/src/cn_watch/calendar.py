"""Trading calendars for cn-watch.

The engine only asks two questions: is this a trading day, and how trustworthy
is the answer (``ok`` or ``degraded``).  Dates are always interpreted in the
fixed China Standard Time zone; no module here reads the system clock, so the
engine's injected clock remains the only time source.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol

from .models import CalendarConfig, to_cn

AKSHARE_CACHE_NAME = "trade_calendar.json"


class TradingCalendar(Protocol):
    status: str

    def is_trading_day(self, moment: datetime) -> bool: ...


class WeekdayCalendar:
    """Monday through Friday are trading days; legal holidays are not handled."""

    status = "ok"

    def is_trading_day(self, moment: datetime) -> bool:
        return to_cn(moment).weekday() < 5


class DateSetCalendar:
    """An explicit, exhaustive set of trading days (``source: file``)."""

    def __init__(self, dates: Iterable[date]) -> None:
        self._dates = frozenset(dates)
        self.status = "ok"

    def is_trading_day(self, moment: datetime) -> bool:
        return to_cn(moment).date() in self._dates


def load_akshare_dates() -> list[date]:
    """Fetch the Sina trade-date history through AKShare.

    Imported lazily so the package keeps working (and its tests stay offline)
    when AKShare is not installed.
    """
    import akshare as ak

    frame = ak.tool_trade_date_hist_sina()
    column = "trade_date" if "trade_date" in frame.columns else frame.columns[0]
    return [value for value in (_as_date(item) for item in frame[column].tolist()) if value]


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


class AkshareCalendar:
    """AKShare trading days with a one-refresh-per-day disk cache.

    Fallback order when the loader fails: in-memory data, then the disk cache,
    then plain weekdays with ``status == "degraded"``.
    """

    def __init__(
        self,
        cache_path: str | Path,
        loader: Optional[Callable[[], Iterable[Any]]] = None,
    ) -> None:
        self.cache_path = Path(cache_path)
        self._loader = loader or load_akshare_dates
        self._dates: Optional[frozenset[date]] = None
        self._attempted_on: Optional[date] = None
        self.status = "ok"

    def is_trading_day(self, moment: datetime) -> bool:
        local = to_cn(moment).date()
        self._ensure(local)
        if self._dates is None:
            return local.weekday() < 5
        return local in self._dates

    def _ensure(self, today: date) -> None:
        if self._attempted_on == today:
            return
        self._attempted_on = today
        try:
            dates = frozenset(
                value
                for value in (_as_date(item) for item in self._loader())
                if value is not None
            )
            if not dates:
                raise ValueError("empty trading calendar")
        except Exception:  # noqa: BLE001 - any loader/network failure means fallback
            self._fallback()
            return
        self._dates = dates
        self.status = "ok"
        self._write_cache(dates)

    def _fallback(self) -> None:
        if self._dates is not None:
            self.status = "ok"
            return
        cached = self._read_cache()
        if cached is not None:
            self._dates = cached
            self.status = "ok"
        else:
            self.status = "degraded"

    def _read_cache(self) -> Optional[frozenset[date]]:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, list):
            return None
        dates = {
            parsed
            for parsed in (_as_date(item) for item in raw)
            if parsed is not None
        }
        return frozenset(dates) if dates else None

    def _write_cache(self, dates: frozenset[date]) -> None:
        payload = json.dumps(sorted(day.isoformat() for day in dates), indent=2)
        tmp = self.cache_path.with_name(self.cache_path.name + ".tmp")
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(payload + "\n", encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass


def build_calendar(
    config: CalendarConfig,
    out_dir: str | Path,
    *,
    loader: Optional[Callable[[], Iterable[Any]]] = None,
) -> TradingCalendar:
    if config.source == "file":
        return DateSetCalendar(config.dates)
    if config.source == "akshare":
        cache_path = config.cache_path or Path(out_dir) / AKSHARE_CACHE_NAME
        return AkshareCalendar(cache_path, loader=loader)
    return WeekdayCalendar()
