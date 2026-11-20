"""Per-host rate limiting, circuit breaking, retries and single-flight."""

from __future__ import annotations

import copy
import http.client
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from . import config


class UpstreamError(Exception):
    def __init__(self, code: str, *, circuit: bool = False, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.circuit = circuit
        self.detail = detail


class HostNotAllowed(UpstreamError):
    def __init__(self) -> None:
        super().__init__("host_not_allowed", circuit=False)


class CircuitOpen(UpstreamError):
    def __init__(self) -> None:
        super().__init__("circuit_open", circuit=False)


class RateLimited(UpstreamError):
    def __init__(self) -> None:
        super().__init__("rate_limited", circuit=True)


class UpstreamTimeout(UpstreamError):
    def __init__(self) -> None:
        super().__init__("upstream_timeout", circuit=True)


class ResponseTooLarge(UpstreamError):
    def __init__(self) -> None:
        super().__init__("response_too_large", circuit=False)


class CircuitBreaker:
    """Closed -> open after N consecutive transport failures -> half-open after 300 s."""

    def __init__(
        self,
        *,
        threshold: int = config.CIRCUIT_FAILURE_THRESHOLD,
        open_seconds: float = config.CIRCUIT_OPEN_SECONDS,
    ) -> None:
        self.threshold = threshold
        self.open_seconds = open_seconds
        self._lock = threading.Lock()
        self.failures = 0
        self.state = "closed"
        self.opened_until = 0.0
        self.probe_in_flight = False

    def allow(self, now: float) -> bool:
        with self._lock:
            if self.state == "closed":
                return True
            if self.state == "open":
                if now < self.opened_until:
                    return False
                self.state = "half_open"
                self.probe_in_flight = True
                return True
            if self.probe_in_flight:
                return False
            self.probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            self.state = "closed"
            self.probe_in_flight = False
            self.opened_until = 0.0

    def record_failure(self, now: float) -> None:
        with self._lock:
            self.failures += 1
            self.probe_in_flight = False
            if self.state == "half_open" or self.failures >= self.threshold:
                self.state = "open"
                self.opened_until = now + self.open_seconds

    def snapshot(self, now: float) -> dict[str, Any]:
        with self._lock:
            remaining = max(0.0, self.opened_until - now) if self.state == "open" else 0.0
            return {
                "state": self.state,
                "consecutive_failures": self.failures,
                "open_remaining_s": round(remaining, 1),
            }


@dataclass
class _Bucket:
    capacity: int
    refill_per_second: float
    tokens: float
    updated: float


class HostGovernor:
    """One process-wide governor shared by every bot and every capability."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        policies: Mapping[str, config.HostPolicy] | None = None,
        fetch_fn: Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]] | None = None,
        bytes_fetch_fn: Callable[
            [str, Mapping[str, str], float, int], tuple[int, Mapping[str, str], bytes]
        ]
        | None = None,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self.policies = dict(policies or config.HOST_POLICIES)
        self._fetch_fn = fetch_fn or _urllib_fetch
        self._bytes_fetch_fn = bytes_fetch_fn or _urllib_fetch_bytes
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._breakers = {host: CircuitBreaker() for host in self.policies}
        self._semaphores = {host: threading.Semaphore(policy.max_concurrency) for host, policy in self.policies.items()}
        self._last_request: dict[str, float] = {}
        self._request_times: dict[str, list[float]] = {host: [] for host in self.policies}
        self._total_requests: dict[str, int] = {host: 0 for host in self.policies}
        self._total_failures: dict[str, int] = {host: 0 for host in self.policies}
        self._last_error: dict[str, str] = {}
        self._recent: list[dict[str, Any]] = []

    # -- health ---------------------------------------------------------
    def record_event(self, tool: str, source: str, *, switched: bool, ok: bool, error: str | None = None) -> None:
        with self._lock:
            self._recent.append(
                {
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "tool": tool,
                    "source": source,
                    "switched": bool(switched),
                    "ok": bool(ok),
                    "error": error,
                }
            )
            if len(self._recent) > config.RECENT_EVENTS:
                del self._recent[: len(self._recent) - config.RECENT_EVENTS]

    def health(self, now: float) -> dict[str, Any]:
        with self._lock:
            hosts: dict[str, Any] = {}
            for host, policy in self.policies.items():
                recent = [stamp for stamp in self._request_times[host] if now - stamp < 60]
                entry = {
                    "rate_bucket": policy.rate_bucket,
                    "limit_per_minute": policy.max_per_minute,
                    "requests_last_minute": len(recent),
                    "requests_total": self._total_requests[host],
                    "failures_total": self._total_failures[host],
                    "concurrency_limit": policy.max_concurrency,
                    "min_interval_s": policy.min_interval,
                }
                entry.update(self._breakers[host].snapshot(now))
                if host in self._last_error:
                    entry["last_error"] = self._last_error[host]
                hosts[host] = entry
            return {"upstreams": hosts, "recent": list(self._recent)}

    # -- request path ---------------------------------------------------
    def validate_host(self, host: str) -> config.HostPolicy:
        lowered = host.lower()
        if config.is_forbidden_host(lowered) or lowered not in self.policies:
            raise HostNotAllowed()
        return self.policies[lowered]

    def _bucket(self, bucket: str, policy: config.HostPolicy) -> _Bucket:
        existing = self._buckets.get(bucket)
        if existing is not None:
            return existing
        created = _Bucket(
            capacity=policy.max_per_minute,
            refill_per_second=policy.max_per_minute / 60.0,
            tokens=float(policy.max_per_minute),
            updated=self._clock(),
        )
        self._buckets[bucket] = created
        return created

    def _acquire(self, host: str, policy: config.HostPolicy) -> None:
        while True:
            with self._lock:
                now = self._clock()
                bucket = self._bucket(policy.rate_bucket, policy)
                elapsed = max(0.0, now - bucket.updated)
                bucket.tokens = min(float(bucket.capacity), bucket.tokens + elapsed * bucket.refill_per_second)
                bucket.updated = now
                wait = 0.0
                if bucket.tokens < 1.0 - 1e-9:
                    wait = (1.0 - bucket.tokens) / bucket.refill_per_second
                last = self._last_request.get(host)
                if last is not None and policy.min_interval > 0:
                    wait = max(wait, policy.min_interval - (now - last))
                if wait <= 1e-6:
                    bucket.tokens -= 1.0
                    self._last_request[host] = now
                    self._request_times[host].append(now)
                    self._total_requests[host] += 1
                    return
            self._sleep(min(wait, 5.0))

    def request(
        self,
        host: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> str:
        policy = self.validate_host(host)
        now = self._clock()
        if not self._breakers[host].allow(now):
            raise CircuitOpen()
        semaphore = self._semaphores[host]
        if not semaphore.acquire(timeout=policy.timeout + 5.0):
            raise UpstreamTimeout()
        try:
            self._acquire(host, policy)
            url = self._build_url(host, path, params)
            last_error: UpstreamError | None = None
            for attempt in range(config.HTTP_RETRIES + 1):
                try:
                    status, response_headers, body = self._fetch_fn(url, _request_headers(headers), policy.timeout)
                    if status == 429:
                        raise RateLimited()
                    if status < 200 or status >= 300:
                        raise UpstreamError("upstream_http", circuit=False)
                    if not body:
                        raise UpstreamError("empty_response", circuit=True)
                    if len(body) > config.MAX_RESPONSE_BYTES:
                        raise ResponseTooLarge()
                    text = body.decode(encoding, errors="replace")
                    if not text.strip():
                        raise UpstreamError("empty_response", circuit=True)
                    self._breakers[host].record_success()
                    with self._lock:
                        self._last_error.pop(host, None)
                    return text
                except UpstreamError as exc:
                    last_error = exc
                    if exc.circuit:
                        with self._lock:
                            self._total_failures[host] += 1
                            self._last_error[host] = exc.code
                        self._breakers[host].record_failure(self._clock())
                    if attempt < config.HTTP_RETRIES and exc.circuit:
                        self._sleep(0.05 + random.random() * 0.1)
                        continue
                    raise
                except (ConnectionError, TimeoutError, OSError, http.client.HTTPException) as exc:
                    last_error = UpstreamError("upstream_network", circuit=True, detail=type(exc).__name__)
                    with self._lock:
                        self._total_failures[host] += 1
                        self._last_error[host] = last_error.code
                    self._breakers[host].record_failure(self._clock())
                    if attempt < config.HTTP_RETRIES:
                        self._sleep(0.05 + random.random() * 0.1)
                        continue
                    raise last_error from exc
            raise last_error or UpstreamError("upstream_error")
        finally:
            semaphore.release()

    def _build_url(self, host: str, path: str, params: Mapping[str, Any] | None) -> str:
        if not path.startswith("/"):
            path = "/" + path
        url = f"https://{host}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{query}"
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname != host or parsed.username or parsed.password:
            raise HostNotAllowed()
        return url

    def request_bytes(
        self,
        host: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> tuple[int, Mapping[str, str], bytes]:
        """Fetch a binary body (used for announcement PDFs) with the same host limits."""
        policy = self.validate_host(host)
        limit = config.MAX_RESPONSE_BYTES if max_bytes is None else max_bytes
        now = self._clock()
        if not self._breakers[host].allow(now):
            raise CircuitOpen()
        semaphore = self._semaphores[host]
        if not semaphore.acquire(timeout=policy.timeout + 5.0):
            raise UpstreamTimeout()
        try:
            self._acquire(host, policy)
            url = self._build_url(host, path, None)
            last_error: UpstreamError | None = None
            for attempt in range(config.HTTP_RETRIES + 1):
                try:
                    status, response_headers, body = self._bytes_fetch_fn(
                        url, _request_headers(headers), timeout or policy.timeout, limit
                    )
                    if status == 429:
                        raise RateLimited()
                    if status < 200 or status >= 300:
                        raise UpstreamError("upstream_http", circuit=False)
                    if not body:
                        raise UpstreamError("empty_response", circuit=True)
                    if len(body) > limit:
                        raise ResponseTooLarge()
                    self._breakers[host].record_success()
                    with self._lock:
                        self._last_error.pop(host, None)
                    return status, response_headers, body
                except UpstreamError as exc:
                    last_error = exc
                    if exc.circuit:
                        with self._lock:
                            self._total_failures[host] += 1
                            self._last_error[host] = exc.code
                        self._breakers[host].record_failure(self._clock())
                    if attempt < config.HTTP_RETRIES and exc.circuit:
                        self._sleep(0.05 + random.random() * 0.1)
                        continue
                    raise
                except (ConnectionError, TimeoutError, OSError, http.client.HTTPException) as exc:
                    last_error = UpstreamError("upstream_network", circuit=True, detail=type(exc).__name__)
                    with self._lock:
                        self._total_failures[host] += 1
                        self._last_error[host] = last_error.code
                    self._breakers[host].record_failure(self._clock())
                    if attempt < config.HTTP_RETRIES:
                        self._sleep(0.05 + random.random() * 0.1)
                        continue
                    raise last_error from exc
            raise last_error or UpstreamError("upstream_error")
        finally:
            semaphore.release()

    def request_form(
        self,
        host: str,
        path: str,
        *,
        form: Mapping[str, Any],
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> str:
        """Submit a read-only form (used by the quarterly holdings search)."""
        policy = self.validate_host(host)
        if not self._breakers[host].allow(self._clock()):
            raise CircuitOpen()
        semaphore = self._semaphores[host]
        if not semaphore.acquire(timeout=policy.timeout + 5.0):
            raise UpstreamTimeout()
        try:
            self._acquire(host, policy)
            url = self._build_url(host, path, params)
            body = urllib.parse.urlencode(form).encode("utf-8")
            request_headers = _request_headers(headers)
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
            last_error: UpstreamError | None = None
            for attempt in range(config.HTTP_RETRIES + 1):
                try:
                    status, _response_headers, payload = _urllib_fetch_form(
                        url, request_headers, policy.timeout, body
                    )
                    if status == 429:
                        raise RateLimited()
                    if status < 200 or status >= 300:
                        raise UpstreamError("upstream_http", circuit=False)
                    if not payload:
                        raise UpstreamError("empty_response", circuit=True)
                    if len(payload) > config.MAX_RESPONSE_BYTES:
                        raise ResponseTooLarge()
                    text = payload.decode(encoding, errors="replace")
                    if not text.strip():
                        raise UpstreamError("empty_response", circuit=True)
                    self._breakers[host].record_success()
                    with self._lock:
                        self._last_error.pop(host, None)
                    return text
                except UpstreamError as exc:
                    last_error = exc
                    if exc.circuit:
                        with self._lock:
                            self._total_failures[host] += 1
                            self._last_error[host] = exc.code
                        self._breakers[host].record_failure(self._clock())
                    if attempt < config.HTTP_RETRIES and exc.circuit:
                        self._sleep(0.05 + random.random() * 0.1)
                        continue
                    raise
                except (ConnectionError, TimeoutError, OSError, http.client.HTTPException) as exc:
                    last_error = UpstreamError("upstream_network", circuit=True, detail=type(exc).__name__)
                    with self._lock:
                        self._total_failures[host] += 1
                        self._last_error[host] = last_error.code
                    self._breakers[host].record_failure(self._clock())
                    if attempt < config.HTTP_RETRIES:
                        self._sleep(0.05 + random.random() * 0.1)
                        continue
                    raise last_error from exc
            raise last_error or UpstreamError("upstream_error")
        finally:
            semaphore.release()

    # -- external calls (AKShare) ---------------------------------------
    def run_external(self, host: str, fn: Callable[[], Any], *, timeout: float = config.AKSHARE_TIMEOUT) -> Any:
        policy = self.validate_host(host)
        now = self._clock()
        if not self._breakers[host].allow(now):
            raise CircuitOpen()
        semaphore = self._semaphores[host]
        if not semaphore.acquire(timeout=policy.timeout + 5.0):
            raise UpstreamTimeout()
        try:
            self._acquire(host, policy)
            box: dict[str, Any] = {}
            done = threading.Event()

            def worker() -> None:
                try:
                    box["value"] = fn()
                except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
                    box["error"] = exc
                finally:
                    done.set()

            thread = threading.Thread(target=worker, name="cn-market-gateway-upstream", daemon=True)
            thread.start()
            if not done.wait(timeout):
                with self._lock:
                    self._total_failures[host] += 1
                    self._last_error[host] = "upstream_timeout"
                self._breakers[host].record_failure(self._clock())
                raise UpstreamTimeout()
            if "error" in box:
                exc = box["error"]
                if _is_connection_error(exc):
                    with self._lock:
                        self._total_failures[host] += 1
                        self._last_error[host] = "upstream_network"
                    self._breakers[host].record_failure(self._clock())
                    raise UpstreamError("upstream_network", circuit=True) from exc
                raise UpstreamError("upstream_error", circuit=False) from exc
            self._breakers[host].record_success()
            return box["value"]
        finally:
            semaphore.release()


def _request_headers(extra: Mapping[str, str] | None) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; cn-market-gateway/0.1)",
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "identity",
    }
    if extra:
        headers.update({str(k): str(v) for k, v in extra.items()})
    return headers


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _urllib_fetch(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, Mapping[str, str], bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(config.MAX_RESPONSE_BYTES + 1)
            return int(getattr(response, "status", 200)), response.headers, body
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise UpstreamError("redirect_refused", circuit=False) from exc
        body = exc.read(config.MAX_RESPONSE_BYTES + 1)
        return int(exc.code), exc.headers, body


def _urllib_fetch_bytes(
    url: str, headers: Mapping[str, str], timeout: float, max_bytes: int
) -> tuple[int, Mapping[str, str], bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            return int(getattr(response, "status", 200)), response.headers, body
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise UpstreamError("redirect_refused", circuit=False) from exc
        body = exc.read(max_bytes + 1)
        return int(exc.code), exc.headers, body


def _urllib_fetch_form(
    url: str, headers: Mapping[str, str], timeout: float, body: bytes
) -> tuple[int, Mapping[str, str], bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, headers=dict(headers), data=body, method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(config.MAX_RESPONSE_BYTES + 1)
            return int(getattr(response, "status", 200)), response.headers, payload
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise UpstreamError("redirect_refused", circuit=False) from exc
        payload = exc.read(config.MAX_RESPONSE_BYTES + 1)
        return int(exc.code), exc.headers, payload


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError, http.client.HTTPException, OSError)):
        return True
    try:
        import requests

        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True
    except ImportError:  # pragma: no cover
        pass
    return False


@dataclass
class _Flight:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None


class SingleFlight:
    """Identical (tool, normalized args) calls share one upstream execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: dict[str, _Flight] = {}

    def run(self, key: str, fn: Callable[[], Any]) -> Any:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = _Flight()
                self._flights[key] = flight
        assert flight is not None
        if not leader:
            if not flight.event.wait(timeout=config.MAX_COALESCE_WAIT):
                raise UpstreamTimeout()
            if flight.error is not None:
                raise flight.error
            return copy.deepcopy(flight.result)
        try:
            result = fn()
            flight.result = result
            return result
        except BaseException as exc:  # noqa: BLE001 - propagated to every waiter
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.event.set()
