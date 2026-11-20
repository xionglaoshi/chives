"""Market-data adapters for the replay engine.

``DailyStoreSource`` reads the T154 database read-only and reuses its price-limit
rules (``limit_ratio`` plus ``limit_price_from``) for the section 0 limit-up
test.  ``InMemorySource`` is the hand-written-bar adapter used by unit and
property tests, so the state machine itself never touches SQLite.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Protocol

from cn_daily_store import DailyStore
from cn_daily_store.limits import limit_price_from, round_half_up_to_cent

from .state import BarView


class MarketSource(Protocol):
    def calendar(self) -> list[date]: ...

    def universe(self, day: date) -> set[str]: ...

    def qfq_bars(self, day: date) -> dict[str, BarView]: ...

    def raw_closes(self, day: date) -> dict[str, float]: ...

    def is_limit_up(self, code: str, day: date, raw_close: float, prev_raw_close: float | None) -> bool: ...


class DailyStoreSource:
    """Adapter over ``cn_daily_store.DailyStore`` (read-only).

    Spec section 8.3 (v1): ST identity comes from the store's name history; the
    T154 store only has current names, so historical ST status is approximated
    by the current name (documented in the report).
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.store = DailyStore(db_path)
        self._calendar = self.store.calendar()

    def close(self) -> None:
        self.store.close()

    def calendar(self) -> list[date]:
        return self._calendar

    def universe(self, day: date) -> set[str]:
        return set(self.store.universe(day))

    def qfq_bars(self, day: date) -> dict[str, BarView]:
        return {
            code: BarView(close=bar.close, low=bar.low, high=bar.high, volume=bar.volume)
            for code, bar in self.store.bars_on(day, adjust="qfq").items()
        }

    def raw_closes(self, day: date) -> dict[str, float]:
        return {code: bar.close for code, bar in self.store.bars_on(day, adjust="none").items()}

    def is_limit_up(self, code: str, day: date, raw_close: float, prev_raw_close: float | None) -> bool:
        ratio = self.store.limit_ratio(code, day)
        if ratio is None or prev_raw_close is None:
            return False
        expected = limit_price_from(prev_raw_close, ratio)
        return round_half_up_to_cent(raw_close) == expected


class InMemorySource:
    """Deterministic synthetic source for tests (no adjustment factors)."""

    def __init__(
        self,
        calendar: list[date],
        bars: dict[str, dict[date, BarView]],
        universe_by_day: dict[date, set[str]],
        limit_up_days: Iterable[tuple[str, date]] = (),
    ) -> None:
        self._calendar = sorted(calendar)
        self._bars = bars
        self._universe = universe_by_day
        self._limit = set(limit_up_days)

    def calendar(self) -> list[date]:
        return self._calendar

    def universe(self, day: date) -> set[str]:
        return set(self._universe.get(day, set()))

    def qfq_bars(self, day: date) -> dict[str, BarView]:
        return {code: series[day] for code, series in self._bars.items() if day in series}

    def raw_closes(self, day: date) -> dict[str, float]:
        return {code: series[day].close for code, series in self._bars.items() if day in series}

    def is_limit_up(self, code: str, day: date, raw_close: float, prev_raw_close: float | None) -> bool:
        return (code, day) in self._limit
