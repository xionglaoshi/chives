"""Per-process token bucket kept well below the official X API rate limits."""

from __future__ import annotations

import threading
import time
from typing import Callable


class TokenBucket:
    def __init__(
        self,
        capacity: int = 30,
        refill_seconds: float = 30.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = capacity
        self._refill_seconds = refill_seconds
        self._clock = clock
        self._tokens = float(capacity)
        self._updated = clock()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated
        if elapsed <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed / self._refill_seconds)
        self._updated = now

    def allow(self) -> bool:
        now = self._clock()
        with self._lock:
            self._refill(now)
            if self._tokens < 1.0:
                return False
            self._tokens -= 1.0
            return True

    def retry_after(self) -> int:
        now = self._clock()
        with self._lock:
            self._refill(now)
            if self._tokens >= 1.0:
                return 0
            return max(1, int((1.0 - self._tokens) * self._refill_seconds + 0.999))
