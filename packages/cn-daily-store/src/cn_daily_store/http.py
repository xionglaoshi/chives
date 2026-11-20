"""Small stdlib HTTP client for the few read-only upstream hosts we use.

A global minimum interval (default 1/3 s, i.e. at most 3 requests per second)
is enforced per process.  Redirects are refused so a host whitelist cannot be
bypassed, and retryable failures use exponential backoff.
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

USER_AGENT = "Mozilla/5.0 (compatible; cn-daily-store/0.1)"
ALLOWED_HOSTS = frozenset(
    {
        "web.ifzq.gtimg.cn",
        "query.sse.com.cn",
        "www.szse.cn",
        "finance.sina.com.cn",
    }
)
FORBIDDEN_MARKERS = ("push" + str(2),)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class FetchError(Exception):
    """Upstream fetch failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RateLimiter:
    """Thread-safe global start-time limiter (at most one start per interval)."""

    def __init__(
        self,
        min_interval: float = 1.0 / 3.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = max(0.0, min_interval)
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                wait = self.min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise FetchError("redirect_refused", f"refused redirect (HTTP {code})")


def check_url(url: str) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if any(marker in host for marker in FORBIDDEN_MARKERS):
        raise FetchError("forbidden_host", "forbidden host marker")
    if parts.scheme not in ("http", "https") or host not in ALLOWED_HOSTS:
        raise FetchError("forbidden_host", "URL left the allowed host list")


def _default_transport(url: str, headers: Mapping[str, str], timeout: float) -> bytes:
    opener = build_opener(_RefuseRedirect())
    request = Request(url, headers=dict(headers))
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise FetchError("response_too_large", "upstream response is too large")
    return body


class HttpClient:
    def __init__(
        self,
        *,
        min_interval: float = 1.0 / 3.0,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = 4,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        transport: Callable[[str, Mapping[str, str], float], bytes] | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.min_interval = max(0.0, min_interval)
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self._clock = clock
        self._sleep = sleeper
        self._transport = transport or _default_transport
        self._limiter = limiter or RateLimiter(self.min_interval, clock=clock, sleeper=sleeper)
        self.requests = 0
        self.failures = 0

    def _throttle(self) -> None:
        self._limiter.wait()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> bytes:
        check_url(url)
        merged = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if headers:
            merged.update(headers)
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            self._throttle()
            self.requests += 1
            try:
                return self._transport(url, merged, self.timeout)
            except FetchError:
                raise
            except HTTPError as exc:
                last_error = exc
                self.failures += 1
                if exc.code not in RETRYABLE_STATUS:
                    raise FetchError("http_error", f"upstream returned HTTP {exc.code}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                self.failures += 1
            if attempt + 1 < self.max_attempts:
                self._sleep(min(8.0, 0.5 * math.pow(2, attempt)))
        raise FetchError("upstream_error", f"upstream failed after retries: {type(last_error).__name__}")

    def get_text(self, url: str, *, headers: Mapping[str, str] | None = None, encoding: str = "utf-8") -> str:
        return self.get(url, headers=headers).decode(encoding, errors="replace")

    def get_json(self, url: str, *, headers: Mapping[str, str] | None = None) -> object:
        text = self.get_text(url, headers=headers)
        try:
            return json.loads(text.lstrip("\ufeff"))
        except (TypeError, ValueError) as exc:
            raise FetchError("invalid_json", "upstream returned invalid JSON") from exc
