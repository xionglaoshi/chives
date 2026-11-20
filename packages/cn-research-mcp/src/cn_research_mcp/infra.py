"""Reusable upstream plumbing: AKShare whitelist audit, TTL cache, per-host rate limit,
hard timeout in a worker thread, and a retry policy limited to connection errors.

Later tasks (T119) extend ALLOWED_FUNCTIONS and reuse everything else unchanged.
"""

from __future__ import annotations

import ast
import http.client
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# The only AKShare callables this package may reference (sources.py is audited at startup).
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "stock_profit_forecast_em",
        "stock_profit_forecast_ths",
        "stock_institute_recommend_detail",
        "stock_research_report_em",
        "stock_value_em",
        "stock_industry_pe_ratio_cninfo",
        "stock_index_pe_lg",
        "stock_a_ttm_lyr",
        "stock_yjyg_em",
        "stock_yjkb_em",
        "stock_yjbb_em",
        "stock_yysj_em",
        "stock_news_em",
        "stock_news_global_cls",
        "stock_news_global_em",
        "macro_calendar_baidu",
        "stock_tfp_em",
        "stock_irm_cninfo",
        # T119 instruments. The first three were renamed in AKShare 1.20.65; the current
        # names are listed here and the pre-1.20.65 names are in LEGACY_FUNCTIONS.
        "bond_cb_list_em",
        "bond_cb_realtime_sina",
        "index_zh_daily_em",
        "index_stock_cons_csindex",
        "stock_gdfx_free_top_10_em",
        "stock_fund_stock_holder",
        "stock_zygc_em",
    }
)
# Pre-1.20.41 / pre-1.20.65 names for the same endpoints; only used when the current name is absent.
LEGACY_FUNCTIONS: frozenset[str] = frozenset(
    {
        "stock_info_global_cls",
        "stock_info_global_em",
        "news_economic_baidu",
        "bond_zh_cov",
        "bond_zh_hs_cov_spot",
        "stock_zh_index_daily_em",
    }
)
# Assembled at runtime (not compile-time folded) so neither the source nor the .pyc contains the literals.
FORBIDDEN_MARKERS: tuple[str, ...] = ("_".join(("_spot", "em")), "push" + str(2))
AKSHARE_NAMES = frozenset({"ak", "akshare"})

DEFAULT_TIMEOUT = 20.0
BIG_TABLE_TIMEOUT = 40.0
MIN_HOST_INTERVAL = 1.0
RETRIES = 1


class UpstreamError(Exception):
    """Upstream failure carrying the envelope error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SourcesAuditError(RuntimeError):
    """sources.py references an AKShare function outside the whitelist."""


def audit_sources_text(text: str, allowed: frozenset[str] = ALLOWED_FUNCTIONS) -> list[str]:
    """Return a list of violations found in the source text (empty means clean)."""
    permitted = allowed | LEGACY_FUNCTIONS
    problems: list[str] = []
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for marker in FORBIDDEN_MARKERS:
                if marker in node.value:
                    problems.append(f"line {node.lineno}: forbidden marker {marker!r}")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in AKSHARE_NAMES:
                if node.attr not in permitted:
                    problems.append(f"line {node.lineno}: akshare function {node.attr!r} not allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_ak":
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                problems.append(f"line {node.lineno}: _ak() needs a literal function name")
            elif first.value not in permitted:
                problems.append(f"line {node.lineno}: akshare function {first.value!r} not allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
            "eval",
            "exec",
        }:
            problems.append(f"line {node.lineno}: {node.func.id} is not allowed")
    return problems


def check_sources_whitelist(path: Path | None = None) -> None:
    target = path or Path(__file__).with_name("sources.py")
    problems = audit_sources_text(target.read_text(encoding="utf-8"))
    if problems:
        raise SourcesAuditError("; ".join(problems))


class TTLCache:
    """Process-local cache; values expire `ttl` seconds after being set."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> tuple[bool, Any]:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return False, None
            expires, value = item
            if self._clock() >= expires:
                del self._items[key]
                return False, None
            return True, value

    def set(self, key: Any, value: Any, ttl: float) -> None:
        with self._lock:
            self._items[key] = (self._clock() + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class RateLimiter:
    """Keeps at least `min_interval` seconds between requests to the same host."""

    def __init__(
        self,
        min_interval: float = MIN_HOST_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            last = self._last.get(host)
            if last is not None:
                delay = self._min - (self._clock() - last)
                if delay > 0:
                    self._sleep(delay)
            self._last[host] = self._clock()


def run_with_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    """Run fn in a daemon worker thread; abandon it and raise upstream_timeout on expiry."""
    box: dict[str, Any] = {}
    done = threading.Event()

    def worker() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller thread
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, name="cn-research-upstream", daemon=True)
    thread.start()
    if not done.wait(timeout):
        raise UpstreamError("upstream_timeout", f"upstream call exceeded {timeout:g}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, http.client.RemoteDisconnected, http.client.IncompleteRead)):
        return True
    try:
        import requests

        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError)):
            return True
    except ImportError:  # pragma: no cover - requests ships with akshare
        pass
    try:
        from urllib3.exceptions import ProtocolError

        if isinstance(exc, ProtocolError):
            return True
    except ImportError:  # pragma: no cover
        pass
    cause = exc.__cause__ or exc.__context__
    return cause is not None and cause is not exc and is_connection_error(cause)


_RATE_LIMIT_HINTS = ("429", "too many requests", "rate limit", "请求过于频繁", "访问过于频繁")


def is_rate_limited(exc: BaseException) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        return True
    text = str(exc).lower()
    return any(hint in text for hint in _RATE_LIMIT_HINTS)


class UpstreamClient:
    """Executes upstream callables with rate limiting, timeout and the retry policy."""

    def __init__(self, limiter: RateLimiter | None = None, retries: int = RETRIES) -> None:
        self.limiter = limiter or RateLimiter()
        self.retries = retries

    def call(self, host: str, fn: Callable[[], Any], timeout: float = DEFAULT_TIMEOUT) -> Any:
        attempt = 0
        while True:
            self.limiter.wait(host)
            try:
                return run_with_timeout(fn, timeout)
            except UpstreamError:
                raise
            except Exception as exc:  # noqa: BLE001 - classified below
                if is_rate_limited(exc):
                    raise UpstreamError("rate_limited", f"upstream rate limited ({type(exc).__name__})") from exc
                if is_connection_error(exc) and attempt < self.retries:
                    attempt += 1
                    continue
                raise UpstreamError("upstream_error", f"upstream failed ({type(exc).__name__})") from exc
