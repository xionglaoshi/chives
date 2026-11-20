"""HTTP client: one pinned upstream, 10 s timeout, no redirects, cache and local rate limit."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from fmp_mcp.config import Settings
from fmp_mcp.redact import redact

TIMEOUT_SECONDS = 10.0
QUOTE_CACHE_TTL = 15.0
DEFAULT_CACHE_TTL = 300.0
RATE_LIMIT_CALLS = 20
RATE_LIMIT_WINDOW = 60.0


class FmpError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RowsResult:
    rows: list[Any] = field(default_factory=list)
    error: FmpError | None = None


class FmpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        timeout: float = TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        quote_ttl: float = QUOTE_CACHE_TTL,
        default_ttl: float = DEFAULT_CACHE_TTL,
        rate_limit_calls: int = RATE_LIMIT_CALLS,
        rate_limit_window: float = RATE_LIMIT_WINDOW,
    ) -> None:
        self.base_url = settings.base_url.rstrip("/")
        self.credential = settings.api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self._clock = clock
        self._quote_ttl = quote_ttl
        self._default_ttl = default_ttl
        self._rate_limit_calls = rate_limit_calls
        self._rate_limit_window = rate_limit_window
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, list[Any]]] = {}
        self._recent_calls: deque[float] = deque()

    # ---------------------------------------------------------------- public API
    def get_rows(self, path: str, params: dict[str, Any], *, quote: bool = False) -> RowsResult:
        if self.credential is None:
            return RowsResult(error=FmpError(
                "missing_key", "未配置 FMP_API_KEY，运行 scripts/install-keys.py"
            ))
        cache_key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
        now = self._clock()
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return RowsResult(rows=list(cached[1]))
        if not self._allow_call(now):
            return RowsResult(error=FmpError(
                "rate_limited", "本地限流：每分钟最多 20 次上游请求，请稍后重试"
            ))
        try:
            rows = self._request(path, params)
        except FmpError as exc:
            return RowsResult(error=exc)
        if rows:
            ttl = self._quote_ttl if quote else self._default_ttl
            self._cache[cache_key] = (now + ttl, list(rows))
        return RowsResult(rows=rows)

    # ---------------------------------------------------------------- internals
    def _allow_call(self, now: float) -> bool:
        while self._recent_calls and now - self._recent_calls[0] >= self._rate_limit_window:
            self._recent_calls.popleft()
        if len(self._recent_calls) >= self._rate_limit_calls:
            return False
        self._recent_calls.append(now)
        return True

    def _request(self, path: str, params: dict[str, Any]) -> list[Any]:
        url = f"{self.base_url}{path}"
        query = dict(params)
        query["apikey"] = self.credential
        try:
            response = self.session.get(
                url, params=query, timeout=self.timeout, allow_redirects=False
            )
        except requests.Timeout as exc:
            raise FmpError("upstream_unreachable", "上游请求超时（10 秒）") from exc
        except requests.RequestException as exc:
            # Exception text may embed the request URL (and therefore the key): never echo it.
            raise FmpError("upstream_unreachable", "无法连接上游 FMP（网络错误）") from exc

        status = int(response.status_code)
        body = response.text or ""
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if status in {301, 302, 303, 307, 308}:
            raise FmpError("upstream_error", "上游返回重定向；为安全起见不跟随")
        if not 200 <= status < 300:
            raise self._error_from_upstream(status, payload, body)
        if isinstance(payload, dict):
            raise self._error_from_upstream(status, payload, body)
        if payload is None:
            raise FmpError("upstream_error", f"上游返回 HTTP {status} 但响应不是 JSON")
        if not isinstance(payload, list):
            return [payload]
        return payload

    def _error_from_upstream(self, status: int, payload: Any, body: str) -> FmpError:
        message = self._message_of(payload, body)
        lowered = message.lower()
        if status in {401, 403} or "invalid api key" in lowered:
            return FmpError("unauthorized", "FMP 认证失败：API Key 无效或未授权")
        if status == 402 or "premium" in lowered or "subscription" in lowered:
            return FmpError("plan_restricted", "当前套餐不含该数据")
        if status == 429 or "limit reach" in lowered or "limit reached" in lowered:
            return FmpError("rate_limited", "上游限流：请稍后重试（免费套餐每日约 250 次）")
        detail = redact(message, self.credential).strip()[:200]
        suffix = f"：{detail}" if detail else ""
        return FmpError("upstream_error", f"上游返回 HTTP {status}{suffix}")

    @staticmethod
    def _message_of(payload: Any, body: str) -> str:
        if isinstance(payload, dict):
            for key in ("Error Message", "error", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return (body or "").strip()[:500]
