"""In-memory result cache and sliding-window rate limiter."""

from __future__ import annotations

import json
import time
from collections import OrderedDict, deque
from typing import Any

import mcp.types as types

from mcp_filter_proxy.config import CacheConfig, RateLimitConfig

WINDOW_SECONDS = 60.0


def cache_key(upstream_tool: str, arguments: dict[str, Any] | None) -> str:
    """Stable key: tool name plus canonical JSON of the arguments (keys sorted)."""
    canonical = json.dumps(
        arguments or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return f"{upstream_tool}\x00{canonical}"


class ResultCache:
    def __init__(self, config: CacheConfig, *, clock=time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, types.CallToolResult]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def ttl_for(self, upstream_tool: str) -> float:
        return self._config.ttl_for(upstream_tool)

    def get(self, key: str) -> types.CallToolResult | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, result = item
        if expires_at <= self._clock():
            del self._items[key]
            return None
        return result.model_copy(deep=True)

    def put(self, key: str, result: types.CallToolResult, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        self._items.pop(key, None)
        self._items[key] = (self._clock() + ttl_seconds, result.model_copy(deep=True))
        while len(self._items) > self._config.max_entries:
            self._items.popitem(last=False)


class SlidingWindowLimiter:
    """Allow at most *max_calls* starts in any rolling 60 second window."""

    def __init__(self, config: RateLimitConfig, *, clock=time.monotonic) -> None:
        self._max_calls = config.max_calls_per_minute
        self._clock = clock
        self._starts: deque[float] = deque()

    @property
    def max_calls(self) -> int:
        return self._max_calls

    def allow(self) -> bool:
        now = self._clock()
        cutoff = now - WINDOW_SECONDS
        while self._starts and self._starts[0] <= cutoff:
            self._starts.popleft()
        if len(self._starts) >= self._max_calls:
            return False
        self._starts.append(now)
        return True
