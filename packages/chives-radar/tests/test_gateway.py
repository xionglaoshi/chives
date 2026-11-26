from __future__ import annotations

from datetime import datetime

import pytest

from chives_radar.config import ConfigError
from chives_radar.engine import SourceError
from chives_radar.sources import MAX_CODES_PER_REQUEST, GatewaySource

from gateway_support import FakeGateway, envelope, quote_item

NOW = datetime.fromisoformat("2026-11-03T09:30:00+08:00")


def _source(server: FakeGateway, timeout: float = 2.0) -> GatewaySource:
    return GatewaySource(server.base, timeout=timeout)


def test_maps_gateway_quote_fields():
    server = FakeGateway(
        lambda tool, args: envelope(
            "ok",
            [
                quote_item(
                    "600000.SH",
                    "浦发银行",
                    10.0,
                    9.0,
                    open_=9.2,
                    high=10.2,
                    low=9.1,
                    volume_shares=12_345_600,
                    amount_yuan=123_456_789.0,
                    limit_up=9.9,
                    limit_down=8.1,
                    volume_ratio=1.5,
                    quote_time="2026-11-03T10:30:00+08:00",
                )
            ],
        )
    )
    try:
        quotes = _source(server).fetch(["600000.SH"], NOW)
    finally:
        server.close()
    assert server.calls[0]["tool"] == "market_quote"
    assert server.calls[0]["args"] == {"codes": ["600000.SH"]}
    quote = quotes["600000.SH"]
    assert quote.name == "浦发银行"
    assert quote.price == 10.0
    assert quote.prev_close == 9.0
    assert quote.open == 9.2
    assert quote.high == 10.2
    assert quote.low == 9.1
    assert quote.volume_lots == 123_456
    assert quote.amount_yuan == 123_456_789.0
    assert quote.limit_up == 9.9
    assert quote.limit_down == 8.1
    assert quote.volume_ratio == 1.5
    assert quote.exch_time == datetime.fromisoformat("2026-11-03T10:30:00+08:00")


def test_missing_optional_fields_do_not_fabricate_values():
    item = quote_item("600000.SH", "浦发银行", 10.0, 9.0)
    for key in ("open", "high", "low", "volume_shares", "amount_yuan", "limit_up", "limit_down", "volume_ratio"):
        item[key] = None
    server = FakeGateway(lambda tool, args: envelope("partial", [item]))
    try:
        quote = _source(server).fetch(["600000.SH"], NOW)["600000.SH"]
    finally:
        server.close()
    assert quote.open == quote.price
    assert quote.high == quote.price
    assert quote.low == quote.price
    assert quote.volume_lots == 0
    assert quote.amount_yuan is None
    assert quote.limit_up == 0.0
    assert quote.limit_down == 0.0
    assert quote.volume_ratio is None


def test_single_missing_code_is_absent_not_invented():
    server = FakeGateway(
        lambda tool, args: envelope(
            "partial", [quote_item("600000.SH", "浦发银行", 10.0, 9.0)]
        )
    )
    try:
        quotes = _source(server).fetch(["600000.SH", "000001.SZ"], NOW)
    finally:
        server.close()
    assert set(quotes) == {"600000.SH"}


def test_quote_without_time_is_treated_as_missing():
    item = quote_item("600000.SH", "浦发银行", 10.0, 9.0, quote_time="")
    server = FakeGateway(lambda tool, args: envelope("ok", [item]))
    try:
        with pytest.raises(SourceError):
            _source(server).fetch(["600000.SH"], NOW)
    finally:
        server.close()


@pytest.mark.parametrize("status", ["unavailable", "", "error"])
def test_non_ok_status_raises_source_error(status: str):
    server = FakeGateway(
        lambda tool, args: envelope(status, message="行情服务暂时不可用")
    )
    try:
        with pytest.raises(SourceError) as excinfo:
            _source(server).fetch(["600000.SH"], NOW)
    finally:
        server.close()
    assert "行情服务暂时不可用" in str(excinfo.value)


def test_gateway_unreachable_raises_source_error():
    server = FakeGateway(lambda tool, args: envelope("ok", []))
    base = server.base
    server.close()
    with pytest.raises(SourceError):
        GatewaySource(base, timeout=0.5).fetch(["600000.SH"], NOW)


def test_more_than_20_codes_are_batched_in_order():
    def respond(tool, args):
        return envelope(
            "ok",
            [quote_item(code, code, 10.0, 9.0) for code in args["codes"]],
        )

    server = FakeGateway(respond)
    codes = [f"{600000 + index}.SH" for index in range(MAX_CODES_PER_REQUEST + 1)]
    try:
        quotes = _source(server).fetch(codes, NOW)
    finally:
        server.close()
    assert [len(call["args"]["codes"]) for call in server.calls] == [20, 1]
    assert list(quotes) == codes


def test_empty_watchlist_makes_no_request():
    server = FakeGateway(lambda tool, args: envelope("ok", []))
    try:
        assert _source(server).fetch([], NOW) == {}
    finally:
        server.close()
    assert server.calls == []


def test_gateway_url_must_be_loopback_and_http():
    with pytest.raises(ConfigError):
        GatewaySource("http://example.com:8868")
    with pytest.raises(ConfigError):
        GatewaySource("ftp://127.0.0.1:8868")
