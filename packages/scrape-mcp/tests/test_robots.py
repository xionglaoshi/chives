from __future__ import annotations

import time

import pytest

from scrape_mcp.robots import DomainPacer, RateLimitError, RobotsCache
from scrape_mcp.ssrf import parse_target

PUBLIC_V4 = "93.184.216.34"


def _target(url: str = "https://example.com/page"):
    return parse_target(url, resolver=lambda host, port: (PUBLIC_V4,))


def test_robots_allows_when_file_is_missing() -> None:
    cache = RobotsCache(lambda url: (404, ""), user_agent="dsh-finance-scrape/0.1.0")
    allowed, warning = cache.check(_target())
    assert allowed is True
    assert warning is None


def test_robots_disallow_is_reported() -> None:
    cache = RobotsCache(
        lambda url: (200, "User-agent: *\nDisallow: /\n"),
        user_agent="dsh-finance-scrape/0.1.0",
    )
    allowed, warning = cache.check(_target())
    assert allowed is False
    assert warning is not None and "disallows" in warning


def test_robots_unavailable_is_allowed() -> None:
    def fetch(url: str) -> tuple[int, str]:
        raise RuntimeError("network down")

    cache = RobotsCache(fetch, user_agent="dsh-finance-scrape/0.1.0")
    allowed, warning = cache.check(_target())
    assert allowed is True
    assert warning is None


def test_robots_are_cached_for_one_hour() -> None:
    calls = {"count": 0}

    def fetch(url: str) -> tuple[int, str]:
        calls["count"] += 1
        return 200, "User-agent: *\nAllow: /\n"

    cache = RobotsCache(fetch, user_agent="dsh-finance-scrape/0.1.0")
    cache.check(_target())
    cache.check(_target("https://example.com/other"))
    assert calls["count"] == 1


def test_robots_cache_expires() -> None:
    calls = {"count": 0}
    now = {"value": 1000.0}

    def fetch(url: str) -> tuple[int, str]:
        calls["count"] += 1
        return 200, "User-agent: *\nAllow: /\n"

    cache = RobotsCache(
        fetch,
        user_agent="dsh-finance-scrape/0.1.0",
        ttl_seconds=3600.0,
        clock=lambda: now["value"],
    )
    cache.check(_target())
    now["value"] += 3601
    cache.check(_target())
    assert calls["count"] == 2


def test_robots_uses_our_user_agent() -> None:
    cache = RobotsCache(
        lambda url: (200, "User-agent: dsh-finance-scrape\nDisallow: /private\n"),
        user_agent="dsh-finance-scrape/0.1.0",
    )
    assert cache.check(_target("https://example.com/private/page"))[0] is False
    assert cache.check(_target("https://example.com/public"))[0] is True


def test_pacer_spaces_requests_per_origin() -> None:
    sleep_calls: list[float] = []
    now = {"value": 100.0}

    pacer = DomainPacer(
        1.0,
        clock=lambda: now["value"],
        sleep=lambda seconds: (sleep_calls.append(seconds), now.__setitem__("value", now["value"] + seconds)),
    )
    pacer.wait("https://example.com")
    now["value"] += 0.25
    delay = pacer.wait("https://example.com")
    assert delay == pytest.approx(0.75)
    assert sleep_calls == [pytest.approx(0.75)]


def test_pacer_rejects_wait_beyond_budget() -> None:
    now = {"value": 100.0}
    pacer = DomainPacer(10.0, clock=lambda: now["value"], sleep=lambda seconds: None)
    pacer.wait("https://example.com")
    with pytest.raises(RateLimitError):
        pacer.wait("https://example.com", budget=1.0)


def test_pacer_isolates_origins() -> None:
    now = {"value": 100.0}
    pacer = DomainPacer(5.0, clock=lambda: now["value"], sleep=lambda seconds: None)
    pacer.wait("https://a.example")
    assert pacer.wait("https://b.example") == 0.0
