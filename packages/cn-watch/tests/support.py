"""Shared helpers for the offline test-suite."""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

from cn_watch.config import parse_config
from cn_watch.market_context import MarketSnapshot
from cn_watch.models import CN_TZ, Quote, WatchConfig, parse_exch_time

DAY0 = datetime(2026, 11, 3, 9, 30, 0, tzinfo=CN_TZ)

BASE_CONFIG: dict[str, Any] = {
    "watchlist": ["002553.SZ"],
    "polling": {
        "base_seconds": 3.0,
        "fast_seconds": 1.0,
        "hot_band_pct": 0.3,
        "fast_hold_seconds": 30,
        "idle_seconds": 30,
        "jitter_pct": 0,
        "timeout_seconds": 3,
        "backoff_seconds": [3, 6, 12, 30],
        "stale_after_seconds": 15,
    },
    "alerts": {"cooldown_seconds": 300, "rearm_pct": 0.5},
    "active_windows": ["09:30:00-11:30:00", "13:00:00-14:57:00"],
    "rules": [
        {"id": "pct_up_3", "type": "pct_change", "direction": "up", "threshold_pct": 3.0}
    ],
    "api": {"host": "127.0.0.1", "port": 8865},
}


def config(**overrides: Any) -> WatchConfig:
    raw = copy.deepcopy(BASE_CONFIG)
    for key, value in overrides.items():
        raw[key] = value
    return parse_config(raw)


def rule(**fields: Any) -> dict[str, Any]:
    return dict(fields)


def plan(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "plan-1",
        "code": "002553.SZ",
        "market": [],
        "sector": [],
        "stock": [],
        "policy": "all",
        "giveup": [],
        "stop_price": None,
        "held": False,
        "expires_at": None,
        "label": "",
    }
    payload.update(overrides)
    return payload


def at(price: float, *, now: datetime, **fields: Any) -> Quote:
    return quote(price, exch=now, **fields)


class FakeMarket:
    def __init__(
        self,
        snapshot: Optional[MarketSnapshot] = None,
        *,
        error: Optional[BaseException] = None,
    ) -> None:
        self.snapshot_value = snapshot or MarketSnapshot(
            ok=True,
            age_s=0.0,
            regime="strong",
            indexes={
                "000001.SH": 1.0,
                "399001.SZ": 0.5,
                "399006.SZ": 0.8,
                "000300.SH": 0.6,
                "000852.SH": 0.2,
                "000688.SH": 0.1,
            },
            sectors={
                "BK0433": {"change_pct": 2.0, "rank": 1},
                "BK0477": {"change_pct": -1.0, "rank": 28},
            },
        )
        self.error = error
        self.refresh_calls: list[datetime] = []
        self.snapshot_calls: list[datetime] = []

    def refresh(self, now: datetime) -> None:
        self.refresh_calls.append(now)
        if self.error is not None:
            raise self.error

    def snapshot(self, now: datetime) -> MarketSnapshot:
        self.snapshot_calls.append(now)
        return self.snapshot_value


def quote(
    price: float = 15.0,
    *,
    code: str = "002553.SZ",
    name: str = "南方精工",
    prev_close: float = 15.0,
    open_: Optional[float] = None,
    high: Optional[float] = None,
    low: Optional[float] = None,
    volume_lots: int = 1000,
    amount_yuan: Optional[float] = None,
    exch: datetime | str | None = None,
    limit_up: float = 16.5,
    limit_down: float = 13.5,
    volume_ratio: Optional[float] = None,
) -> Quote:
    moment = DAY0 if exch is None else (exch if isinstance(exch, datetime) else parse_exch_time(exch))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CN_TZ)
    amount = price * volume_lots * 100.0 if amount_yuan is None else amount_yuan
    return Quote(
        code=code,
        name=name,
        price=price,
        prev_close=prev_close,
        open=price if open_ is None else open_,
        high=price if high is None else high,
        low=price if low is None else low,
        volume_lots=volume_lots,
        amount_yuan=amount,
        exch_time=moment,
        limit_up=limit_up,
        limit_down=limit_down,
        volume_ratio=volume_ratio,
    )


class StepClock:
    def __init__(self, start: datetime = DAY0) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += timedelta(seconds=max(0.0, seconds))

    def advance(self, seconds: float) -> None:
        self.sleep(seconds)


class ScriptedSource:
    """Returns successive steps; the last step repeats."""

    def __init__(self, steps: list[Any]) -> None:
        if not steps:
            raise ValueError("at least one step")
        self.steps = steps
        self.calls: list[datetime] = []

    def fetch(self, codes: list[str], now: datetime) -> dict[str, Quote]:
        self.calls.append(now)
        step = self.steps[min(len(self.calls) - 1, len(self.steps) - 1)]
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            step = step(now)
        return {code: value for code, value in step.items() if code in codes}


class MemoryStore:
    def __init__(self, alerts: Optional[list[dict[str, Any]]] = None) -> None:
        self.alerts: list[dict[str, Any]] = list(alerts or [])
        self.polls: list[dict[str, Any]] = []
        self.states: list[dict[str, Any]] = []

    def existing_alerts(self) -> list[dict[str, Any]]:
        return list(self.alerts)

    def write_alert(self, alert: dict[str, Any]) -> None:
        self.alerts.append(dict(alert))

    def write_poll(self, row: dict[str, Any]) -> None:
        self.polls.append(dict(row))

    def write_state(self, state: dict[str, Any]) -> None:
        self.states.append(copy.deepcopy(state))


def stop_event() -> threading.Event:
    return threading.Event()
