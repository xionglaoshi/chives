"""Trading-calendar helpers (China time, fixed UTC+8).

The optional ``config/trade_calendar.json`` file is a JSON array of
``YYYY-MM-DD`` dates.  When it is missing or unreadable the calendar degrades
to Monday-Friday, matching cn-watch's ``weekdays`` source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from .models import CN_TZ

DEFAULT_CLOSE = time(15, 0)
DEFAULT_OPEN = time(9, 30)


@dataclass(frozen=True)
class TradingCalendar:
    days: frozenset[date]
    source: str
    path: Optional[Path] = None

    @classmethod
    def from_file(cls, path: Optional[Path]) -> "TradingCalendar":
        if path is None or not Path(path).is_file():
            return cls(days=frozenset(), source="weekdays", path=path)
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(days=frozenset(), source="weekdays", path=Path(path))
        if not isinstance(raw, list) or not raw:
            return cls(days=frozenset(), source="weekdays", path=Path(path))
        days: set[date] = set()
        for item in raw:
            if not isinstance(item, str):
                return cls(days=frozenset(), source="weekdays", path=Path(path))
            try:
                days.add(date.fromisoformat(item))
            except ValueError:
                return cls(days=frozenset(), source="weekdays", path=Path(path))
        return cls(days=frozenset(days), source="file", path=Path(path))

    def is_trading_day(self, day: date) -> bool:
        if self.source == "file":
            return day in self.days
        return day.weekday() < 5

    def is_trading_day_at(self, moment: datetime) -> bool:
        return self.is_trading_day(moment.astimezone(CN_TZ).date())

    def next_trading_day(self, day: date, *, include_today: bool = False) -> date:
        current = day if include_today else day + timedelta(days=1)
        for _ in range(370):
            if self.is_trading_day(current):
                return current
            current += timedelta(days=1)
        raise ValueError("no trading day found in the next year")

    def add_trading_days(self, day: date, count: int) -> date:
        current = day
        remaining = max(0, int(count))
        while remaining > 0:
            current = self.next_trading_day(current)
            remaining -= 1
        return current

    @staticmethod
    def open_at(day: date) -> datetime:
        return datetime.combine(day, DEFAULT_OPEN, tzinfo=CN_TZ)

    @staticmethod
    def close_at(day: date) -> datetime:
        return datetime.combine(day, DEFAULT_CLOSE, tzinfo=CN_TZ)


def next_close(calendar: TradingCalendar, now: datetime) -> datetime:
    local = now.astimezone(CN_TZ)
    today_close = calendar.close_at(local.date())
    if calendar.is_trading_day(local.date()) and today_close > local:
        return today_close
    return calendar.close_at(calendar.next_trading_day(local.date()))


def next_open(calendar: TradingCalendar, now: datetime) -> datetime:
    local = now.astimezone(CN_TZ)
    today_open = calendar.open_at(local.date())
    if calendar.is_trading_day(local.date()) and today_open > local:
        return today_open
    return calendar.open_at(calendar.next_trading_day(local.date()))
