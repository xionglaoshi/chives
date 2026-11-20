"""Daily K-line client backed by the local market-data gateway (`market_bars`).

`portfolio_risk` asks for forward-adjusted closes for stocks and unadjusted
index closes; the gateway is reached at `PORTFOLIO_GATEWAY_URL` (loopback only,
default http://127.0.0.1:8868). Requests are serial and throttled, with a cap
per tool call. There is no direct upstream fallback.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping

from portfolio_mcp.gateway import (
    GatewayError,
    call,
    normalize_gateway_url,
    resolve_gateway_url,
)

MAX_REQUESTS = 101
MAX_BARS = 1000
MIN_INTERVAL_SECONDS = 0.15
DEFAULT_TIMEOUT = 8.0


class KlineError(Exception):
    """Daily K-line fetch failure carrying a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class KlineSeries:
    """Valid daily closes for one symbol, sorted ascending, one row per date."""

    symbol: str
    points: tuple[tuple[str, float], ...]

    def __len__(self) -> int:
        return len(self.points)

    @property
    def dates(self) -> list[str]:
        return [point[0] for point in self.points]

    @property
    def closes(self) -> list[float]:
        return [point[1] for point in self.points]

    @property
    def last_date(self) -> str | None:
        return self.points[-1][0] if self.points else None

    def close_on_or_before(self, day: str) -> float | None:
        for point_day, close in reversed(self.points):
            if point_day <= day:
                return close
        return None


def adjust_for(kind: str) -> str:
    """Keep portfolio_risk's existing basis: qfq for stocks, raw for indices."""
    if kind not in ("stock", "index"):
        raise KlineError("invalid_argument", "kind must be 'stock' or 'index'")
    return "qfq" if kind == "stock" else "none"


def parse_bars_payload(payload: Mapping[str, Any], symbol: str) -> KlineSeries:
    data = payload.get("data")
    rows = data.get("bars") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise KlineError("kline_missing", f"kline source has no bars for {symbol}")
    closes: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            day = date.fromisoformat(str(row.get("time")).strip()[:10]).isoformat()
        except (TypeError, ValueError):
            continue
        try:
            close = float(str(row.get("close")).strip())
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        closes[day] = close
    if not closes:
        raise KlineError("kline_missing", f"kline source has no valid closes for {symbol}")
    return KlineSeries(symbol=symbol, points=tuple(sorted(closes.items())))


class GatewayKlineClient:
    """Serial daily K-line fetcher with a minimum interval between requests."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        min_interval: float = MIN_INTERVAL_SECONDS,
    ) -> None:
        self._env = env
        self._base_url = base_url
        self._timeout = timeout
        self._clock = clock
        self._sleep = sleeper
        self._min_interval = min_interval
        self._last_request_at: float | None = None
        self._requests = 0

    @property
    def requests(self) -> int:
        return self._requests

    def begin_call(self) -> None:
        """Reset the per-tool-call request budget and throttle state."""
        self._requests = 0
        self._last_request_at = None

    def _base(self) -> str:
        if self._base_url is not None:
            return normalize_gateway_url(self._base_url)
        return resolve_gateway_url(self._env)

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request_at = now

    def fetch(self, symbol: str, *, bars: int, kind: str = "stock") -> KlineSeries:
        adjust = adjust_for(kind)
        if not isinstance(symbol, str) or not symbol:
            raise KlineError("invalid_argument", "symbol is required")
        if not isinstance(bars, int) or isinstance(bars, bool) or bars <= 0:
            raise KlineError("invalid_argument", "bars must be a positive integer")
        if bars > MAX_BARS:
            raise KlineError("invalid_argument", f"bars must be at most {MAX_BARS}")
        if self._requests >= MAX_REQUESTS:
            raise KlineError(
                "too_many_requests", f"at most {MAX_REQUESTS} K-line requests per tool call"
            )
        base = self._base()

        self._throttle()
        self._requests += 1
        args = {"code": symbol, "interval": "1d", "adjust": adjust, "limit": bars}
        try:
            payload = call(base, "market_bars", args, timeout=self._timeout)
        except GatewayError as exc:
            raise KlineError(exc.code, f"日 K 取不到（{exc.message}）") from exc
        status = payload.get("status")
        if status not in ("ok", "partial"):
            message = str(payload.get("message") or "数据服务没有返回可用日 K")
            raise KlineError("kline_missing", f"日 K 取不到（{message}）")
        return parse_bars_payload(payload, symbol)
