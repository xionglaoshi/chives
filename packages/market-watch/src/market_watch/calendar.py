"""Trading calendar and trading-state helpers.

``config/trade_calendar.json`` is read-only (the same file cn-watch uses); when
it is absent the engine degrades to weekdays, which is why ``status`` is
exposed.  No function here reads the system clock.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional, Protocol

from .models import CN_TZ

logger = logging.getLogger("market_watch.calendar")

OPEN = time(9, 30)
CLOSE_AM = time(11, 30)
OPEN_PM = time(13, 0)
CLOSE = time(15, 0)
REFRESH_BEFORE = timedelta(minutes=5)
REFRESH_AFTER = timedelta(minutes=5)


class TradingCalendar(Protocol):
    status: str

    def is_trading_day(self, moment: datetime) -> bool: ...


class WeekdayCalendar:
    status = "ok"

    def is_trading_day(self, moment: datetime) -> bool:
        return moment.astimezone(CN_TZ).weekday() < 5


class DateSetCalendar:
    def __init__(self, days: Iterable[date]) -> None:
        self._days = frozenset(days)
        self.status = "ok"

    def is_trading_day(self, moment: datetime) -> bool:
        return moment.astimezone(CN_TZ).date() in self._days


class DegradedCalendar:
    status = "degraded"

    def is_trading_day(self, moment: datetime) -> bool:
        return moment.astimezone(CN_TZ).weekday() < 5


def load_calendar_file(path: str | Path) -> frozenset[date]:
    target = Path(path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"交易日历必须是非空 JSON 数组: {target}")
    days: set[date] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"交易日历元素必须是 YYYY-MM-DD 字符串: {item!r}")
        days.add(date.fromisoformat(item.strip()[:10]))
    return frozenset(days)


def build_calendar(source: str, path: Optional[Path]) -> TradingCalendar:
    if source == "file":
        if path is None:
            raise ValueError("calendar.source=file 但未配置 calendar.file")
        try:
            return DateSetCalendar(load_calendar_file(path))
        except (OSError, ValueError) as exc:
            logger.warning("交易日历不可用，降级为工作日判断: %s", exc)
            return DegradedCalendar()
    return WeekdayCalendar()


def trading_state(now: datetime, calendar: TradingCalendar) -> str:
    local = now.astimezone(CN_TZ)
    if not calendar.is_trading_day(local):
        return "holiday"
    clock = local.time()
    if clock < OPEN:
        return "pre_open"
    if clock < CLOSE_AM:
        return "open"
    if clock < OPEN_PM:
        return "lunch"
    if clock < CLOSE:
        return "open"
    return "closed"


def is_trading_state(state: str) -> bool:
    return state == "open"


def in_refresh_window(now: datetime, calendar: TradingCalendar) -> bool:
    """True in the 5 minutes before the open and after the close (weekends too)."""
    local = now.astimezone(CN_TZ)
    if local.weekday() >= 5:
        return False
    clock = local.time()
    morning = datetime.combine(local.date(), OPEN, tzinfo=CN_TZ)
    evening = datetime.combine(local.date(), CLOSE, tzinfo=CN_TZ)
    return (morning - REFRESH_BEFORE <= local < morning) or (evening <= local < evening + REFRESH_AFTER)


def in_alert_suppression(
    now: datetime,
    *,
    open_minutes: int = 15,
    close_minutes: int = 5,
) -> bool:
    """First ``open_minutes`` of the session and last ``close_minutes`` before 15:00."""
    local = now.astimezone(CN_TZ)
    clock = local.time()
    if clock < OPEN:
        return False
    open_dt = datetime.combine(local.date(), OPEN, tzinfo=CN_TZ)
    if local < open_dt + timedelta(minutes=open_minutes):
        return True
    close_dt = datetime.combine(local.date(), CLOSE, tzinfo=CN_TZ)
    return local >= close_dt - timedelta(minutes=close_minutes)
