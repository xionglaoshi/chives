from __future__ import annotations

import mcp.types as types

from mcp_filter_proxy.cache import ResultCache, SlidingWindowLimiter, cache_key
from mcp_filter_proxy.config import CacheConfig, RateLimitConfig


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_result(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def test_cache_key_ignores_argument_order():
    assert cache_key("tool", {"b": 2, "a": 1}) == cache_key("tool", {"a": 1, "b": 2})
    assert cache_key("tool", None) == cache_key("tool", {})
    assert cache_key("tool", {"a": 1}) != cache_key("other", {"a": 1})


def test_cache_ttl_and_expiry():
    clock = Clock()
    cache = ResultCache(CacheConfig(max_entries=10, ttl_default=5), clock=clock)
    cache.put("k", make_result("one"), 5)
    assert cache.get("k") is not None
    clock.now += 4.9
    assert cache.get("k") is not None
    clock.now += 0.2
    assert cache.get("k") is None


def test_cache_evicts_oldest_entry():
    clock = Clock()
    cache = ResultCache(CacheConfig(max_entries=2, ttl_default=60), clock=clock)
    cache.put("a", make_result("a"), 60)
    cache.put("b", make_result("b"), 60)
    cache.put("c", make_result("c"), 60)
    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.get("c") is not None


def test_zero_ttl_is_not_cached():
    cache = ResultCache(CacheConfig(max_entries=10, ttl_default=60))
    cache.put("k", make_result("one"), 0)
    assert cache.get("k") is None


def test_cache_returns_an_independent_copy():
    cache = ResultCache(CacheConfig(max_entries=10, ttl_default=60))
    cache.put("k", make_result("original"), 60)
    first = cache.get("k")
    assert first is not None
    first.content[0].text = "mutated"
    second = cache.get("k")
    assert second is not None
    assert second.content[0].text == "original"


def test_sliding_window_rate_limiter():
    clock = Clock()
    limiter = SlidingWindowLimiter(RateLimitConfig(max_calls_per_minute=2), clock=clock)
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False
    clock.now += 59
    assert limiter.allow() is False
    clock.now += 2
    assert limiter.allow() is True
