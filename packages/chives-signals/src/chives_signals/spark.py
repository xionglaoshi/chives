"""Tencent intraday minute lines for sparklines.

The primary upstream is ``web.ifzq.gtimg.cn`` with ``ifzq.gtimg.cn`` as a
same-path fallback: intermittent 5xx or timeouts on the primary are retried
once against the fallback within the same deadline.  Both hosts are fixed and
https-only in production; tests may point them at loopback while
``CHIVES_HUB_TEST_MODE=1``.

Every failure degrades to ``missing`` for that code.  A response whose ``date``
is not today is treated as missing, so an old session is never passed off as
today's line.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time as clock_time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Mapping, Optional, Sequence

from .calendar import TradingCalendar
from .config import IFZQ_FALLBACK_HOST, IFZQ_HOST, TEST_MODE_ENV, HubConfig
from .models import CN_TZ, fmt_iso
from .sources import HttpClient

logger = logging.getLogger("chives_signals.spark")

MAX_SPARK_CODES = 30
MAX_SPARK_POINTS = 60
TRADING_CACHE_SECONDS = 30.0
CLOSED_CACHE_SECONDS = 600.0
MAX_UPSTREAM_CONCURRENCY = 4
TOTAL_UPSTREAM_TIMEOUT = 5.0
PRIMARY_FAILOVER_SECONDS = 60.0
MAX_RAW_CODES_LENGTH = 4096
CLOSE_TIME = time(15, 0)
MINUTE_PATH = "/appstock/app/minute/query"
SPARK_CODE_RE = re.compile(r"^([0-9]{6})\.(SH|SZ)$")


class SparkParamError(ValueError):
    """Invalid ``codes`` parameter; the server answers ``bad_params``."""

    code = "bad_params"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def parse_spark_codes(raw: Optional[str]) -> list[str]:
    """Validate, canonicalize and dedupe ``codes`` while preserving order."""
    if not isinstance(raw, str) or not raw.strip():
        raise SparkParamError("codes 不能为空")
    if len(raw) > MAX_RAW_CODES_LENGTH:
        raise SparkParamError("codes 过长")
    codes: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        if SPARK_CODE_RE.match(token) is None:
            raise SparkParamError("代码必须形如 600519.SH/300750.SZ")
        if token not in seen:
            seen.add(token)
            codes.append(token)
    if not codes:
        raise SparkParamError("codes 不能为空")
    if len(codes) > MAX_SPARK_CODES:
        raise SparkParamError(f"一次最多 {MAX_SPARK_CODES} 个代码")
    return codes


def tencent_symbol(code: str) -> str:
    match = SPARK_CODE_RE.match(code)
    if match is None:
        raise SparkParamError("代码必须形如 600519.SH/300750.SZ")
    prefix = "sh" if match.group(2) == "SH" else "sz"
    return prefix + match.group(1)


def minute_url(base: str, code: str) -> str:
    query = urllib.parse.urlencode({"code": tencent_symbol(code)})
    return base.rstrip("/") + MINUTE_PATH + "?" + query


def downsample_points(points: Sequence[float], limit: int = MAX_SPARK_POINTS) -> list[float]:
    """Pick ``limit`` evenly spaced real points, always keeping both ends."""
    values = list(points)
    if limit <= 1:
        return values[:1]
    if len(values) <= limit:
        return values
    step = (len(values) - 1) / (limit - 1)
    indices = sorted({int(round(index * step)) for index in range(limit)})
    if indices[0] != 0:
        indices.insert(0, 0)
    if indices[-1] != len(values) - 1:
        indices.append(len(values) - 1)
    return [values[index] for index in indices]


@dataclass(frozen=True)
class MinuteData:
    trading_date: date
    points: tuple[float, ...]
    prev_close: Optional[float]
    as_of_minute: str


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valid_stamp(text: str) -> bool:
    if len(text) != 4 or not text.isdigit():
        return False
    return int(text[:2]) <= 23 and int(text[2:]) <= 59


def _prev_close(node: Mapping[str, Any], symbol: str, code: str) -> Optional[float]:
    qt = node.get("qt")
    row: Any = None
    if isinstance(qt, list):
        row = qt
    elif isinstance(qt, str):
        row = qt
    elif isinstance(qt, dict):
        for key in (symbol, code, symbol.upper()):
            value = qt.get(key)
            if isinstance(value, (list, str)):
                row = value
                break
    if isinstance(row, str):
        row = row.split("~")
    if not isinstance(row, list) or len(row) < 5:
        return None
    value = _number(row[4])
    return value if value is not None and value > 0 else None


def parse_minute_payload(payload: Any, code: str, today: date) -> Optional[MinuteData]:
    """Parse one Tencent minute node; ``None`` means the code belongs in ``missing``."""
    if not isinstance(payload, dict):
        return None
    status = payload.get("code")
    if status not in (None, 0, "0"):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    symbol = tencent_symbol(code)
    node = data.get(symbol)
    if not isinstance(node, dict):
        return None
    inner = node.get("data")
    if not isinstance(inner, dict):
        return None
    rows = inner.get("data")
    raw_date = inner.get("date")
    if not isinstance(rows, list) or not isinstance(raw_date, str):
        return None
    try:
        trading_date = datetime.strptime(raw_date, "%Y%m%d").date()
    except ValueError:
        return None
    if trading_date != today:
        return None
    points: list[float] = []
    last_stamp: Optional[str] = None
    for row in rows:
        if not isinstance(row, str):
            continue
        parts = row.split()
        if len(parts) < 2:
            continue
        stamp, price = parts[0], parts[1]
        if not _valid_stamp(stamp):
            continue
        value = _number(price)
        if value is None or value <= 0:
            continue
        points.append(value)
        last_stamp = stamp
    if not points or last_stamp is None:
        return None
    return MinuteData(
        trading_date=trading_date,
        points=tuple(points),
        prev_close=_prev_close(node, symbol, code),
        as_of_minute=f"{last_stamp[:2]}:{last_stamp[2:]}",
    )


def is_trading_session(moment: datetime, calendar: TradingCalendar) -> bool:
    if not calendar.is_trading_day(moment.date()):
        return False
    current = moment.time()
    return time(9, 30) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 0)


class SparkService:
    """Cached, concurrency-capped fetch of today's minute lines."""

    def __init__(
        self,
        config: HubConfig,
        *,
        client: Optional[Any] = None,
        calendar: Optional[TradingCalendar] = None,
        clock: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.config = config
        self.env = os.environ if env is None else env
        self.test_mode = self.env.get(TEST_MODE_ENV) == "1"
        self.client = client or HttpClient(timeout=config.timeout_seconds, env=self.env)
        self.calendar = calendar or TradingCalendar.from_file(config.calendar_file)
        self.base = config.ifzq_base
        self.fallback_base = config.ifzq_fallback_base
        self.allowed_hosts = (IFZQ_HOST, IFZQ_FALLBACK_HOST)
        self.clock = clock or (lambda: datetime.now(CN_TZ))
        self.monotonic = monotonic or clock_time.monotonic
        self._primary_down_until = 0.0
        self.concurrency = MAX_UPSTREAM_CONCURRENCY
        self.total_timeout = TOTAL_UPSTREAM_TIMEOUT
        self._cache: dict[str, tuple[datetime, MinuteData]] = {}
        self._lock = threading.Lock()

    def now(self, value: Optional[datetime] = None) -> datetime:
        moment = self.clock() if value is None else value
        if moment.tzinfo is None:
            return moment.replace(tzinfo=CN_TZ)
        return moment.astimezone(CN_TZ)

    def payload(self, raw_codes: Optional[str], *, now: Optional[datetime] = None) -> dict[str, Any]:
        codes = parse_spark_codes(raw_codes)
        moment = self.now(now)
        trading_date = moment.date()
        result: dict[str, Any] = {
            "ok": True,
            "as_of": fmt_iso(moment),
            "trading_date": trading_date.isoformat(),
        }
        if not self.calendar.is_trading_day(trading_date):
            result["sparks"] = {}
            result["missing"] = list(codes)
            return result

        cached: dict[str, MinuteData] = {}
        pending: list[str] = []
        for code in codes:
            data = self._cache_get(code, moment)
            if data is None:
                pending.append(code)
            else:
                cached[code] = data
        fetched = self._fetch_pending(pending, moment) if pending else {}

        sparks: dict[str, Any] = {}
        missing: list[str] = []
        for code in codes:
            data = cached.get(code) or fetched.get(code)
            if data is None:
                missing.append(code)
            else:
                sparks[code] = self._render(data, moment)
        result["sparks"] = sparks
        result["missing"] = missing
        return result

    def _cache_get(self, code: str, moment: datetime) -> Optional[MinuteData]:
        with self._lock:
            entry = self._cache.get(code)
        if entry is None:
            return None
        fetched_at, data = entry
        if data.trading_date != moment.date():
            return None
        age = (moment - fetched_at).total_seconds()
        ttl = TRADING_CACHE_SECONDS if is_trading_session(moment, self.calendar) else CLOSED_CACHE_SECONDS
        return data if 0 <= age < ttl else None

    def _fetch_pending(self, codes: Sequence[str], moment: datetime) -> dict[str, MinuteData]:
        if not codes:
            return {}
        results: dict[str, MinuteData] = {}
        deadline = self.monotonic() + self.total_timeout
        workers = max(1, min(self.concurrency, len(codes)))
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hub-spark")
        futures = {executor.submit(self._fetch_one, code, moment, deadline): code for code in codes}
        try:
            for future in as_completed(futures, timeout=self.total_timeout):
                code = futures[future]
                try:
                    data = future.result()
                except Exception:  # noqa: BLE001 - one bad code must not fail the batch
                    data = None
                if data is None:
                    continue
                results[code] = data
                with self._lock:
                    self._cache[code] = (moment, data)
        except TimeoutError:
            logger.warning("spark upstream deadline exceeded")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return results

    def _primary_available(self) -> bool:
        with self._lock:
            return self.monotonic() >= self._primary_down_until

    def _mark_primary_down(self) -> None:
        with self._lock:
            self._primary_down_until = self.monotonic() + PRIMARY_FAILOVER_SECONDS

    def _fetch_one(self, code: str, moment: datetime, deadline: float) -> Optional[MinuteData]:
        bases = (
            [self.fallback_base]
            if not self._primary_available()
            else [self.base, self.fallback_base]
        )
        for base in bases:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return None
            timeout = min(remaining, self.config.timeout_seconds)
            data = self._fetch_from(base, code, moment, timeout)
            if data is not None:
                return data
            if base == self.base:
                self._mark_primary_down()
        return None

    def _fetch_from(
        self, base: str, code: str, moment: datetime, timeout: float
    ) -> Optional[MinuteData]:
        try:
            payload = self.client.get_json_public(
                "ifzq_minute",
                minute_url(base, code),
                now=moment,
                test_mode=self.test_mode,
                allowed_hosts=self.allowed_hosts,
                timeout=timeout,
            )
        except Exception:  # noqa: BLE001 - upstream errors become missing
            return None
        try:
            return parse_minute_payload(payload, code, moment.date())
        except Exception:  # noqa: BLE001 - malformed payload becomes missing
            return None

    @staticmethod
    def _render(data: MinuteData, moment: datetime) -> dict[str, Any]:
        last = data.points[-1]
        prev_close = data.prev_close
        change_pct = (
            round((last / prev_close - 1) * 100, 2)
            if prev_close is not None and prev_close > 0
            else None
        )
        return {
            "points": downsample_points(data.points),
            "prev_close": prev_close,
            "last": last,
            "change_pct": change_pct,
            "as_of_minute": data.as_of_minute,
            "complete": moment.date() == data.trading_date and moment.time() >= CLOSE_TIME,
        }
