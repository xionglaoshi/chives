"""Process-wide tiered cache with a bounded stale fallback."""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .envelope import with_stale


@dataclass
class CacheEntry:
    payload: dict[str, Any]
    stored_at: float
    ttl: float
    fallback: float


class TieredCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.stale_served = 0
        self.stores = 0

    def get_fresh(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None or self._clock() - entry.stored_at >= entry.ttl:
                self.misses += 1
                return None
            self.hits += 1
            return copy.deepcopy(entry.payload)

    def get_stale(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            age = self._clock() - entry.stored_at
            if age > entry.fallback:
                return None
            self.stale_served += 1
            return with_stale(entry.payload)

    def put(self, key: str, payload: dict[str, Any], ttl: float, fallback: float) -> None:
        with self._lock:
            self._items[key] = CacheEntry(copy.deepcopy(payload), self._clock(), ttl, fallback)
            self.stores += 1

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "stale_served": self.stale_served,
                "stores": self.stores,
                "entries": len(self._items),
            }
