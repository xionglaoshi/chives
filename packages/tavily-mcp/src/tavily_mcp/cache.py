"""Small TTL cache for successful upstream responses."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable


class TTLCache:
    def __init__(
        self,
        ttl_seconds: float = 300.0,
        *,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        now = self._clock()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                del self._items[key]
                return None
            return copy.deepcopy(value)

    def set(self, key: str, value: Any) -> None:
        now = self._clock()
        with self._lock:
            if len(self._items) >= self._max_entries:
                expired = [k for k, (expires_at, _) in self._items.items() if now >= expires_at]
                for k in expired:
                    del self._items[k]
                if len(self._items) >= self._max_entries:
                    self._items.pop(next(iter(self._items)))
            self._items[key] = (now + self._ttl, copy.deepcopy(value))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
