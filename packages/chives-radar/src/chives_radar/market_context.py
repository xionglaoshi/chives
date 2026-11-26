"""Read-only market-watch client used by plan rules.

The client polls two public GET endpoints on the loopback market-watch engine
and keeps the last good payload.  A payload older than 30 seconds is treated as
unknown, so a stalled upstream degrades plan conditions instead of the rest of
the watch engine.  Network failures are swallowed here on purpose.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import requests

from .config import MARKET_LOOPBACK_HOSTS
from .models import parse_iso

logger = logging.getLogger("chives_radar.market_context")

DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_STALE_AFTER_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 2.0
REGIME_MAP = {"risk_on": "strong", "risk_off": "weak", "neutral": "neutral"}


def validate_loopback_url(value: str) -> str:
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or host not in MARKET_LOOPBACK_HOSTS:
        raise ValueError("market_watch_url 必须是回环 http(s) 地址")
    if parts.username is not None or parts.password is not None:
        raise ValueError("market_watch_url 不允许包含凭据")
    return value.rstrip("/")


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _payload_time(payload: Mapping[str, Any], now: datetime) -> datetime:
    raw = payload.get("as_of") or payload.get("fetched_at")
    try:
        moment = parse_iso(raw)
    except (TypeError, ValueError):
        return now
    return min(moment, now)


@dataclass(frozen=True)
class MarketSnapshot:
    ok: bool = False
    age_s: Optional[float] = None
    regime: Optional[str] = None
    indexes: Mapping[str, float] = field(default_factory=dict)
    sectors: Mapping[str, Mapping[str, Optional[float]]] = field(default_factory=dict)


class MarketContextClient:
    def __init__(
        self,
        base_url: str,
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = validate_loopback_url(base_url)
        self.interval_seconds = float(interval_seconds)
        self.stale_after_seconds = float(stale_after_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self._last_attempt: Optional[datetime] = None
        self._overview: Mapping[str, Any] = {}
        self._overview_ts: Optional[datetime] = None
        self._overview_ok = False
        self._sectors: Mapping[str, Any] = {}
        self._sectors_ts: Optional[datetime] = None
        self._sectors_ok = False
        self.last_error: Optional[str] = None

    # -- fetching --------------------------------------------------------
    def _get(self, path: str) -> Mapping[str, Any]:
        response = requests.get(
            self.base_url + path,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "chives-radar/0.1", "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("response is not an object")
        if payload.get("ok") is False:
            raise ValueError("market-watch returned ok=false")
        return payload

    def refresh(self, now: datetime) -> None:
        if (
            self._last_attempt is not None
            and (now - self._last_attempt).total_seconds() < self.interval_seconds
        ):
            return
        self._last_attempt = now
        try:
            overview = self._get("/overview")
        except Exception as exc:  # noqa: BLE001 - upstream failure means unknown
            self._overview_ok = False
            self.last_error = f"overview: {type(exc).__name__}: {exc}"[:200]
        else:
            self._overview = overview
            self._overview_ts = _payload_time(overview, now)
            self._overview_ok = True
            self.last_error = None
        try:
            sectors = self._get("/sectors")
        except Exception as exc:  # noqa: BLE001
            self._sectors_ok = False
            self.last_error = f"sectors: {type(exc).__name__}: {exc}"[:200]
        else:
            self._sectors = sectors
            self._sectors_ts = _payload_time(sectors, now)
            self._sectors_ok = True

    # -- reading ---------------------------------------------------------
    def _age(self, moment: Optional[datetime], now: datetime) -> Optional[float]:
        if moment is None:
            return None
        return max(0.0, (now - moment).total_seconds())

    def snapshot(self, now: datetime) -> MarketSnapshot:
        overview_age = self._age(self._overview_ts, now)
        sectors_age = self._age(self._sectors_ts, now)
        overview_fresh = (
            self._overview_ok
            and overview_age is not None
            and overview_age <= self.stale_after_seconds
        )
        sectors_fresh = (
            self._sectors_ok
            and sectors_age is not None
            and sectors_age <= self.stale_after_seconds
        )
        ages = [age for age in (overview_age, sectors_age) if age is not None]
        age_s = round(max(ages), 3) if ages else None

        regime = None
        indexes: dict[str, float] = {}
        if overview_fresh:
            raw_regime = self._overview.get("regime")
            if isinstance(raw_regime, dict):
                raw_regime = raw_regime.get("label")
            if isinstance(raw_regime, str):
                regime = REGIME_MAP.get(raw_regime)
            rows = self._overview.get("indexes")
            if isinstance(rows, list):
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    code = item.get("code")
                    change = _num(item.get("change_pct"))
                    if isinstance(code, str) and change is not None:
                        indexes[code] = change

        sectors: dict[str, dict[str, Optional[float]]] = {}
        if sectors_fresh:
            rows = self._sectors.get("rows")
            if rows is None:
                rows = self._sectors.get("sectors")
            if isinstance(rows, list):
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    code = item.get("code")
                    if not isinstance(code, str):
                        continue
                    sectors[code] = {
                        "change_pct": _num(item.get("change_pct")),
                        "rank": _num(item.get("rank")),
                    }

        return MarketSnapshot(
            ok=bool(overview_fresh),
            age_s=age_s,
            regime=regime,
            indexes=indexes,
            sectors=sectors,
        )


def snapshot_dict(snapshot: MarketSnapshot) -> dict[str, Any]:
    return {
        "ok": snapshot.ok,
        "age_s": snapshot.age_s,
        "regime": snapshot.regime,
    }
