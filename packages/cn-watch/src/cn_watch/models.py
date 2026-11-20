"""Shared data types and time helpers for cn-watch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# A-share market time never observes DST, so a fixed UTC+8 zone is both correct
# and independent of the host tzdata.
CN_TZ = timezone(timedelta(hours=8))


def to_cn(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(CN_TZ)


def parse_iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected an ISO8601 timestamp")
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        raise ValueError("ISO8601 timestamp must include a timezone offset")
    return to_cn(parsed)


def parse_exch_time(value: Any) -> datetime:
    """Accept either Tencent's YYYYMMDDHHMMSS or an ISO8601 timestamp."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing exchange time")
    text = value.strip()
    if len(text) == 14 and text.isdigit():
        parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
        return parsed.replace(tzinfo=CN_TZ)
    return parse_iso(text)


def fmt_iso(value: datetime) -> str:
    return to_cn(value).isoformat()


@dataclass(frozen=True)
class Quote:
    code: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume_lots: int
    amount_yuan: Optional[float]
    exch_time: datetime
    limit_up: float
    limit_down: float
    volume_ratio: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "prev_close": self.prev_close,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "volume_lots": self.volume_lots,
            "amount_yuan": self.amount_yuan,
            "exch_time": fmt_iso(self.exch_time),
            "limit_up": self.limit_up,
            "limit_down": self.limit_down,
            "volume_ratio": self.volume_ratio,
        }


@dataclass(frozen=True)
class Metrics:
    change_pct: Optional[float]
    vwap: Optional[float]
    vwap_dev_pct: Optional[float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "change_pct": self.change_pct,
            "vwap": self.vwap,
            "vwap_dev_pct": self.vwap_dev_pct,
        }


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    direction: Optional[str] = None
    threshold_pct: Optional[float] = None
    min_amount_yuan: Optional[float] = None
    side: Optional[str] = None
    within_pct: Optional[float] = None
    level: Optional[float] = None
    window_seconds: Optional[float] = None
    multiple: Optional[float] = None
    min_window_amount_yuan: Optional[float] = None
    symbols: Optional[tuple[str, ...]] = None
    codes: Optional[tuple[str, ...]] = None

    def _scope(self) -> Optional[tuple[str, ...]]:
        return self.symbols if self.symbols is not None else self.codes

    def applies_to(self, code: str) -> bool:
        scope = self._scope()
        return scope is None or code in scope

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "type": self.type}
        for key in (
            "direction",
            "threshold_pct",
            "min_amount_yuan",
            "side",
            "within_pct",
            "level",
            "window_seconds",
            "multiple",
            "min_window_amount_yuan",
        ):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        data["symbols"] = list(self.symbols) if self.symbols is not None else None
        if self.codes is not None:
            data["codes"] = list(self.codes)
        return data


@dataclass(frozen=True)
class PollingConfig:
    base_seconds: float
    fast_seconds: float
    hot_band_pct: float
    fast_hold_seconds: float
    idle_seconds: float
    jitter_pct: float
    timeout_seconds: float
    backoff_seconds: tuple[float, ...]
    stale_after_seconds: float
    max_lag_seconds: float


@dataclass(frozen=True)
class AlertsConfig:
    cooldown_seconds: float
    rearm_pct: float


@dataclass(frozen=True)
class ApiConfig:
    host: str
    port: int


@dataclass(frozen=True)
class LimitsConfig:
    max_watchlist: int = 10
    max_rules: int = 30


@dataclass(frozen=True)
class CalendarConfig:
    source: str = "weekdays"
    file: Optional[Path] = None
    cache_path: Optional[Path] = None
    dates: tuple[date, ...] = ()


@dataclass(frozen=True)
class WatchConfig:
    watchlist: tuple[str, ...]
    polling: PollingConfig
    alerts: AlertsConfig
    active_windows: tuple[tuple[Any, Any], ...]
    rules: tuple[Rule, ...]
    api: ApiConfig
    calendar: CalendarConfig = CalendarConfig()
    limits: LimitsConfig = LimitsConfig()
    watchlist_runtime_file: Optional[Path] = None
    config_path: Optional[Path] = None
    market_watch_url: str = "http://127.0.0.1:8866"
    gateway_url: str = "http://127.0.0.1:8868"

    def active_at(self, moment: datetime) -> bool:
        local = to_cn(moment)
        clock = local.time().replace(tzinfo=None)
        return any(start <= clock < end for start, end in self.active_windows)
