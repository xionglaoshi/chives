from __future__ import annotations

from datetime import date, timedelta

import pytest

from portfolio_mcp.gateway import GatewayError, resolve_gateway_url
from portfolio_mcp.kline import (
    GatewayKlineClient,
    KlineError,
    adjust_for,
    parse_bars_payload,
)

from helpers import FakeKlineServer, kline_rows


def _days(count: int) -> list[str]:
    start = date(2026, 1, 1)
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _env(monkeypatch: pytest.MonkeyPatch, server: FakeKlineServer) -> None:
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", server.base)


def test_stock_requests_qfq_daily_bars(monkeypatch) -> None:
    days = _days(3)
    server = FakeKlineServer({"sh600000": {"qfqday": kline_rows(days, [10.0, 10.5, 10.2])}})
    _env(monkeypatch, server)
    try:
        series = GatewayKlineClient().fetch("sh600000", bars=8, kind="stock")
    finally:
        server.close()
    assert series.dates == days
    assert series.closes == [10.0, 10.5, 10.2]
    assert series.last_date == days[-1]
    assert len(series) == 3
    assert server.params[0] == {
        "code": "sh600000",
        "interval": "1d",
        "adjust": "qfq",
        "limit": 8,
    }


def test_index_requests_unadjusted_daily_bars(monkeypatch) -> None:
    days = _days(2)
    server = FakeKlineServer({"sh000300": {"day": kline_rows(days, [4000.0, 4010.0])}})
    _env(monkeypatch, server)
    try:
        series = GatewayKlineClient().fetch("sh000300", bars=5, kind="index")
    finally:
        server.close()
    assert series.closes == [4000.0, 4010.0]
    assert server.params[0]["adjust"] == "none"
    assert adjust_for("stock") == "qfq"
    assert adjust_for("index") == "none"


def test_unavailable_envelope_raises_kline_missing(monkeypatch) -> None:
    server = FakeKlineServer({})
    _env(monkeypatch, server)
    try:
        with pytest.raises(KlineError) as excinfo:
            GatewayKlineClient().fetch("sh600000", bars=5, kind="stock")
        assert excinfo.value.code == "kline_missing"
    finally:
        server.close()


def test_stock_without_qfqday_is_unavailable(monkeypatch) -> None:
    days = _days(2)
    server = FakeKlineServer({"sh600000": {"day": kline_rows(days, [10.0, 11.0])}})
    _env(monkeypatch, server)
    try:
        with pytest.raises(KlineError) as excinfo:
            GatewayKlineClient().fetch("sh600000", bars=5, kind="stock")
        assert excinfo.value.code == "kline_missing"
    finally:
        server.close()


def test_gateway_unreachable_raises_upstream_error(monkeypatch) -> None:
    server = FakeKlineServer({})
    base = server.base
    server.close()
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", base)
    with pytest.raises(KlineError) as excinfo:
        GatewayKlineClient(timeout=0.5).fetch("sh600000", bars=5, kind="stock")
    assert excinfo.value.code == "upstream_error"


def test_redirect_is_not_followed(monkeypatch) -> None:
    server = FakeKlineServer({}, status=302, location="http://127.0.0.1:9/evil")
    _env(monkeypatch, server)
    try:
        with pytest.raises(KlineError) as excinfo:
            GatewayKlineClient(timeout=2.0).fetch("sh600000", bars=5, kind="stock")
        assert excinfo.value.code == "redirect_refused"
    finally:
        server.close()


def test_bars_with_invalid_rows_are_filtered() -> None:
    payload = {
        "status": "ok",
        "data": {
            "bars": [
                {"time": "2026-01-01", "close": 10.0},
                {"time": "2026-01-02", "close": "n/a"},
                {"time": "2026-01-03", "close": 0},
                {"time": "not-a-date", "close": 11.0},
                {"time": "2026-01-05", "close": 12.0},
            ]
        },
    }
    series = parse_bars_payload(payload, "sh600000")
    assert series.dates == ["2026-01-01", "2026-01-05"]
    assert series.closes == [10.0, 12.0]


def test_payload_without_bars_raises_kline_missing() -> None:
    with pytest.raises(KlineError) as excinfo:
        parse_bars_payload({"status": "ok", "data": {}}, "sh600000")
    assert excinfo.value.code == "kline_missing"


def test_default_url_and_configuration() -> None:
    assert resolve_gateway_url({}) == "http://127.0.0.1:8868"
    for bad in ("http://example.com:80", "http://127.0.0.1", "http://127.0.0.1:9/api"):
        with pytest.raises(GatewayError):
            resolve_gateway_url({"PORTFOLIO_GATEWAY_URL": bad})


class _AdvancingClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_requests_are_throttled_by_injected_clock(monkeypatch) -> None:
    days = _days(2)
    data = {
        symbol: {"qfqday": kline_rows(days, [10.0, 11.0])}
        for symbol in ("sh600000", "sh600001", "sh600002")
    }
    server = FakeKlineServer(data)
    _env(monkeypatch, server)
    clock = _AdvancingClock()
    try:
        client = GatewayKlineClient(clock=clock, sleeper=clock.sleep)
        for symbol in data:
            client.fetch(symbol, bars=5, kind="stock")
        assert clock.sleeps == [pytest.approx(0.15), pytest.approx(0.15)]
        assert client.requests == 3
    finally:
        server.close()


def test_request_cap_and_begin_call(monkeypatch) -> None:
    days = _days(2)
    server = FakeKlineServer({"sh600000": {"qfqday": kline_rows(days, [10.0, 11.0])}})
    _env(monkeypatch, server)
    try:
        client = GatewayKlineClient(min_interval=0.0)
        for _ in range(101):
            client.fetch("sh600000", bars=5, kind="stock")
        with pytest.raises(KlineError) as excinfo:
            client.fetch("sh600000", bars=5, kind="stock")
        assert excinfo.value.code == "too_many_requests"
        client.begin_call()
        assert client.requests == 0
        assert len(client.fetch("sh600000", bars=5, kind="stock")) == 2
    finally:
        server.close()


def test_invalid_arguments(monkeypatch) -> None:
    with pytest.raises(KlineError):
        GatewayKlineClient().fetch("sh600000", bars=5, kind="etf")
    with pytest.raises(KlineError):
        GatewayKlineClient().fetch("sh600000", bars=0, kind="stock")
    with pytest.raises(KlineError):
        GatewayKlineClient().fetch("sh600000", bars=1001, kind="stock")
