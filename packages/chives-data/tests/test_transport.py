from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from chives_data import config
from chives_data.cache import TieredCache
from chives_data.transport import (
    CircuitOpen,
    HostGovernor,
    HostNotAllowed,
    SingleFlight,
    UpstreamError,
)
from fakes import FakeClock, FakeSources, make_service, tencent_fixture_rows


class SleepClock(FakeClock):
    def __init__(self) -> None:
        super().__init__()
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)


def _policy(**overrides):
    values = dict(host="x.test", rate_bucket="x", max_per_minute=100, max_concurrency=2, min_interval=0.0, timeout=1.0)
    values.update(overrides)
    return config.HostPolicy(**values)


def test_push2_and_unknown_hosts_are_rejected_before_any_request():
    governor = HostGovernor()
    with pytest.raises(HostNotAllowed):
        governor.request("push2his.eastmoney.com", "/")
    with pytest.raises(HostNotAllowed):
        governor.request("push2.eastmoney.com", "/")
    with pytest.raises(HostNotAllowed):
        governor.request("evil.example.com", "/")


def test_circuit_opens_half_opens_and_recovers(monkeypatch):
    monkeypatch.setattr(config, "HTTP_RETRIES", 0)
    clock = FakeClock()

    def failing(url, headers, timeout):
        raise ConnectionError("boom")

    governor = HostGovernor(
        clock=clock,
        sleep=lambda seconds: None,
        policies={"x.test": _policy()},
        fetch_fn=failing,
    )
    for _ in range(3):
        with pytest.raises(UpstreamError):
            governor.request("x.test", "/")
    assert governor.health(clock())["upstreams"]["x.test"]["state"] == "open"
    with pytest.raises(CircuitOpen):
        governor.request("x.test", "/")
    clock.advance(301)

    def ok(url, headers, timeout):
        return 200, {}, b"ok"

    governor._fetch_fn = ok
    assert governor.request("x.test", "/") == "ok"
    assert governor.health(clock())["upstreams"]["x.test"]["state"] == "closed"


def test_rate_bucket_waits_and_records_metrics():
    clock = SleepClock()

    def ok(url, headers, timeout):
        return 200, {}, b"ok"

    governor = HostGovernor(
        clock=clock,
        sleep=clock.sleep,
        policies={"x.test": _policy(max_per_minute=2)},
        fetch_fn=ok,
    )
    for _ in range(3):
        governor.request("x.test", "/")
    assert clock.sleeps
    health = governor.health(clock())["upstreams"]["x.test"]
    assert health["requests_total"] == 3


def test_connection_error_retries_once(monkeypatch):
    monkeypatch.setattr(config, "HTTP_RETRIES", 1)
    calls = {"n": 0}

    def fetch(url, headers, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("boom")
        return 200, {}, b"ok"

    governor = HostGovernor(clock=FakeClock(), sleep=lambda seconds: None, policies={"x.test": _policy()}, fetch_fn=fetch)
    assert governor.request("x.test", "/") == "ok"
    assert calls["n"] == 2


def test_single_flight_coalesces_five_threads():
    flight = SingleFlight()
    count = {"n": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(5)

    def work():
        barrier.wait()
        return flight.run("same", compute)

    def compute():
        with lock:
            count["n"] += 1
        import time

        time.sleep(0.2)
        return {"value": 1}

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: work(), range(5)))
    assert count["n"] == 1
    assert results == [{"value": 1}] * 5


def test_cache_hits_stale_window_and_expiry():
    clock = FakeClock()
    cache = TieredCache(clock)
    cache.put("k", {"status": "ok", "as_of": "2026-11-17T10:00:00+08:00", "data": {}, "stale": False}, ttl=3, fallback=60)
    assert cache.get_fresh("k") is not None
    clock.advance(4)
    assert cache.get_fresh("k") is None
    stale = cache.get_stale("k")
    assert stale is not None and stale["stale"] is True
    assert stale["as_of"] == "2026-11-17T10:00:00+08:00"
    clock.advance(61)
    assert cache.get_stale("k") is None


def test_service_serves_stale_when_every_source_fails():
    clock = FakeClock()
    sources = FakeSources()
    sources.quote_tencent = tencent_fixture_rows()
    service = make_service(sources, clock=clock)
    first = service.call("market_quote", {"codes": ["600000"]})
    assert first["stale"] is False
    clock.advance(5)
    sources.quote_tencent_error = UpstreamError("upstream_network", circuit=True)
    sources.quote_sina_error = UpstreamError("upstream_network", circuit=True)
    stale = service.call("market_quote", {"codes": ["600000"]})
    assert stale["stale"] is True
    assert stale["as_of"] == first["as_of"]


def test_service_coalesces_concurrent_identical_requests():
    sources = FakeSources()
    sources.quote_tencent = tencent_fixture_rows()
    sources.quote_delay = 0.1
    service = make_service(sources)
    barrier = threading.Barrier(5)

    def call():
        barrier.wait()
        return service.call("market_quote", {"codes": ["600000"]})

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: call(), range(5)))
    assert all(result["status"] == "ok" for result in results)
    assert sources.calls.count("tencent_quotes") == 1


def test_slow_compute_answers_within_budget_then_serves_the_cached_result(monkeypatch):
    import threading
    import time

    from chives_data import config
    from fakes import FakeSources, make_service

    monkeypatch.setattr(config, "CALL_BUDGET_SECONDS", 0.05)
    service = make_service(FakeSources())
    release = threading.Event()

    def slow():
        release.wait(2)
        return {"status": "ok", "as_of": "2026-11-17", "data": {"v": 1}, "stale": False}

    try:
        service._cached("k", 60, 600, slow)
        raise AssertionError("expected the budget to expire")
    except Exception as exc:  # ToolError
        assert "正在准备" in str(exc)
    release.set()
    for _ in range(100):
        if service.cache.get_fresh("k") is not None:
            break
        time.sleep(0.01)
    assert service._cached("k", 60, 600, slow)["data"] == {"v": 1}


def test_upstream_errors_that_escape_a_tool_become_friendly_unavailable(monkeypatch):
    from chives_data.transport import UpstreamError, UpstreamTimeout
    from fakes import FakeSources, make_service

    service = make_service(FakeSources())

    def boom_timeout(args):
        raise UpstreamTimeout()

    def boom_error(args):
        raise UpstreamError("upstream_http", circuit=False)

    monkeypatch.setattr(service, "_market_quote", boom_timeout)
    out = service.call("market_quote", {"codes": ["600519"]})
    assert out["status"] == "unavailable" and "正在准备" in out["message"]
    monkeypatch.setattr(service, "_market_quote", boom_error)
    out = service.call("market_quote", {"codes": ["600519"]})
    assert out["status"] == "unavailable" and out["message"] == "数据暂时取不到，请稍后再试"
