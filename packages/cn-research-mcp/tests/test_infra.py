from __future__ import annotations

import http.client
import time

import pytest
import requests

from cn_research_mcp import infra
from cn_research_mcp.infra import (
    ALLOWED_FUNCTIONS,
    RateLimiter,
    TTLCache,
    UpstreamClient,
    UpstreamError,
    audit_sources_text,
    check_sources_whitelist,
    is_connection_error,
    is_rate_limited,
    run_with_timeout,
)


def test_whitelist_has_no_spot_or_push2():
    assert not any("_spot_em" in n or "push2" in n for n in ALLOWED_FUNCTIONS)
    assert len(ALLOWED_FUNCTIONS) == 25


def test_real_sources_file_passes_audit():
    check_sources_whitelist()


def test_audit_flags_disallowed_attribute():
    assert audit_sources_text("import akshare as ak\nak.stock_zh_a_spot_em()\n")


@pytest.mark.parametrize(
    "name", ["bond_cov_comparison", "fund_etf_spot_em", "stock_ggcg_em", "stock_zh_a_spot_em"]
)
def test_audit_flags_disallowed_literal_call(name):
    assert audit_sources_text(f'def f():\n    return _ak("{name}")\n')


def test_audit_flags_non_literal_call():
    assert audit_sources_text("def f(n):\n    return _ak(n)\n")


def test_audit_flags_push2_string():
    assert audit_sources_text('URL = "https://push2.eastmoney.com/api"\n')


def test_audit_flags_spot_em_string():
    assert audit_sources_text('NAME = "fund_etf_spot_em"\n')


def test_audit_flags_eval_exec():
    assert audit_sources_text("eval('1')\n")
    assert audit_sources_text("exec('1')\n")


def test_audit_accepts_allowed_calls():
    assert audit_sources_text('def f():\n    return _ak("stock_value_em", symbol="1")\n') == []


def test_check_raises_on_bad_file(tmp_path):
    bad = tmp_path / "s.py"
    bad.write_text("import akshare as ak\nak.stock_zh_a_spot_em()\n")
    with pytest.raises(infra.SourcesAuditError):
        check_sources_whitelist(bad)


def test_ak_runtime_rejects_unlisted_function():
    from cn_research_mcp import sources

    with pytest.raises(UpstreamError):
        sources._ak("stock_zh_a_spot_em")


def test_cache_expiry():
    now = [0.0]
    cache = TTLCache(clock=lambda: now[0])
    cache.set("k", 1, ttl=10)
    assert cache.get("k") == (True, 1)
    now[0] = 9.9
    assert cache.get("k") == (True, 1)
    now[0] = 10.0
    assert cache.get("k") == (False, None)


def test_cache_clear():
    cache = TTLCache()
    cache.set("k", 1, 10)
    cache.clear()
    assert cache.get("k")[0] is False


def test_rate_limiter_spaces_same_host():
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(1.0, clock=lambda: now[0], sleep=sleep)
    limiter.wait("a")
    now[0] += 0.25
    limiter.wait("a")
    assert sleeps == [pytest.approx(0.75)]


def test_rate_limiter_hosts_independent():
    sleeps: list[float] = []
    limiter = RateLimiter(1.0, clock=lambda: 5.0, sleep=sleeps.append)
    limiter.wait("a")
    limiter.wait("b")
    assert sleeps == []


def test_run_with_timeout_returns_value():
    assert run_with_timeout(lambda: 7, 1) == 7


def test_run_with_timeout_raises_upstream_timeout():
    with pytest.raises(UpstreamError) as err:
        run_with_timeout(lambda: time.sleep(2), 0.1)
    assert err.value.code == "upstream_timeout"


def test_run_with_timeout_propagates_exception():
    def boom():
        raise KeyError("x")

    with pytest.raises(KeyError):
        run_with_timeout(boom, 1)


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionResetError(),
        http.client.RemoteDisconnected("closed"),
        requests.exceptions.ConnectionError("x"),
        requests.exceptions.ChunkedEncodingError("x"),
    ],
)
def test_connection_errors_detected(exc):
    assert is_connection_error(exc)


def test_connection_error_in_cause_chain():
    try:
        try:
            raise ConnectionResetError()
        except ConnectionResetError as inner:
            raise ValueError("wrapped") from inner
    except ValueError as outer:
        assert is_connection_error(outer)


@pytest.mark.parametrize("exc", [ValueError("x"), KeyError("k"), RuntimeError("boom")])
def test_other_errors_not_connection(exc):
    assert not is_connection_error(exc)


def test_rate_limit_detection():
    assert is_rate_limited(RuntimeError("HTTP 429 Too Many Requests"))
    assert not is_rate_limited(RuntimeError("boom"))


def _client() -> UpstreamClient:
    return UpstreamClient(RateLimiter(0, sleep=lambda _s: None))


def test_retry_once_on_connection_error_then_success():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionResetError()
        return "ok"

    assert _client().call("h", fn, 1) == "ok"
    assert len(calls) == 2


def test_retry_is_at_most_one():
    calls = []

    def fn():
        calls.append(1)
        raise ConnectionResetError()

    with pytest.raises(UpstreamError) as err:
        _client().call("h", fn, 1)
    assert len(calls) == 2 and err.value.code == "upstream_error"


def test_no_retry_for_non_connection_error():
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("bad")

    with pytest.raises(UpstreamError):
        _client().call("h", fn, 1)
    assert len(calls) == 1


def test_no_retry_on_timeout():
    calls = []

    def fn():
        calls.append(1)
        time.sleep(1)

    with pytest.raises(UpstreamError) as err:
        _client().call("h", fn, 0.1)
    assert len(calls) == 1 and err.value.code == "upstream_timeout"


def test_rate_limited_not_retried():
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError("429 Too Many Requests")

    with pytest.raises(UpstreamError) as err:
        _client().call("h", fn, 1)
    assert len(calls) == 1 and err.value.code == "rate_limited"


def test_limiter_consulted_on_each_attempt():
    waits: list[str] = []

    class Spy(RateLimiter):
        def wait(self, host: str) -> None:
            waits.append(host)

    calls = []

    def fn():
        calls.append(1)
        raise ConnectionResetError()

    with pytest.raises(UpstreamError):
        UpstreamClient(Spy()).call("host-x", fn, 1)
    assert waits == ["host-x", "host-x"]
