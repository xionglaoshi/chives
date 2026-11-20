"""robots.txt handling and per-domain politeness."""

from __future__ import annotations

import threading
import time
from typing import Callable
from urllib.robotparser import RobotFileParser

from scrape_mcp.ssrf import Target

DEFAULT_TTL_SECONDS = 3600.0


class RateLimitError(RuntimeError):
    """The politeness delay would exceed the caller's remaining budget."""


class DomainPacer:
    """Enforce a minimum delay between requests to the same origin."""

    def __init__(
        self,
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = max(0.0, interval_seconds)
        self._clock = clock
        self._sleep = sleep
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, origin: str, *, budget: float | None = None) -> float:
        with self._lock:
            now = self._clock()
            start = max(now, self._next.get(origin, now))
            delay = start - now
            if budget is not None and delay > budget:
                raise RateLimitError(
                    f"per-domain minimum interval for {origin} would exceed the request timeout"
                )
            self._next[origin] = start + self._interval
        if delay > 0:
            self._sleep(delay)
        return delay


class RobotsCache:
    """Cache robots.txt decisions per origin for one hour.

    A robots.txt that cannot be fetched is treated as "allowed", as the task
    requires.  Parsing failures are treated the same way.
    """

    def __init__(
        self,
        fetch: Callable[[str], tuple[int, str]],
        *,
        user_agent: str,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._user_agent = user_agent
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, RobotFileParser | None]] = {}
        self._origin_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def check(self, target: Target) -> tuple[bool, str | None]:
        """Return ``(allowed, warning)`` for the target URL."""

        parser = self._parser_for(target)
        if parser is None:
            return True, None
        try:
            allowed = parser.can_fetch(self._user_agent, target.url)
        except Exception:
            return True, f"robots.txt for {target.host} could not be parsed; assuming allowed"
        if allowed:
            return True, None
        return False, f"robots.txt disallows {target.url} for {self._user_agent}"

    def _lock_for(self, origin: str) -> threading.Lock:
        with self._lock:
            return self._origin_locks.setdefault(origin, threading.Lock())

    def _parser_for(self, target: Target) -> RobotFileParser | None:
        origin = target.origin
        # One lock per origin: a parallel batch cannot stampede robots.txt, and
        # the first thread's result is reused by the others (no single-flight
        # cache expiry race).
        with self._lock_for(origin):
            now = self._clock()
            with self._lock:
                entry = self._entries.get(origin)
                if entry is not None and now < entry[0]:
                    return entry[1]
            parser: RobotFileParser | None = None
            try:
                status, text = self._fetch(f"{origin}/robots.txt")
            except Exception:
                status, text = 0, ""
            if 200 <= status < 300:
                parser = RobotFileParser()
                try:
                    parser.parse(text.splitlines())
                except Exception:
                    parser = None
            with self._lock:
                self._entries[origin] = (now + self._ttl, parser)
            return parser
