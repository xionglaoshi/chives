from __future__ import annotations

from datetime import date

import pytest

from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.fields import validate_positions
from portfolio_mcp.gateway import GatewayError, resolve_gateway_url
from portfolio_mcp.quotes import (
    GatewayQuoteClient,
    QuoteError,
    build_url,
    parse_quote_item,
    parse_quote_text,
)
from portfolio_mcp.service import PortfolioService
from portfolio_mcp.store import PortfolioState

from helpers import FakeQuoteServer, quote_line

TODAY = date(2026, 11, 3)
QUOTE_TIME = "2026-11-03T10:30:00+08:00"


def _row(
    code: str,
    qty: int,
    cost: float,
    *,
    name: str = "测试股票",
    available: int | None = None,
    opened: str | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "name": name,
        "qty": qty,
        "available_qty": available,
        "cost_price": cost,
        "opened_date": opened,
    }


def _seed(store, rows: list[dict[str, object]], cash: float | None = None) -> None:
    validated = validate_positions(rows, today=TODAY)
    store.apply(
        lambda state: PortfolioState(positions=validated, cash=cash, as_of="2026-11-03")
    )


def _serve(monkeypatch, quotes: dict[str, str]) -> FakeQuoteServer:
    server = FakeQuoteServer(quotes)
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", server.base)
    return server


@pytest.fixture
def two_stock_server(monkeypatch):
    server = _serve(
        monkeypatch,
        {
            "sh600000": quote_line(
                "sh600000", "浦发银行", 10.0, 9.0, 11.11, quote_time=QUOTE_TIME,
                limit_up=10.0, limit_down=9.0,
            ),
            "sz000001": quote_line(
                "sz000001", "平安银行", 20.0, 19.0, 5.26, quote_time=QUOTE_TIME,
                limit_up=21.0, limit_down=18.0,
            ),
        },
    )
    yield server
    server.close()


def _service(store, quotes=None) -> PortfolioService:
    return PortfolioService(store, quotes=quotes, today=lambda: TODAY)


def test_hand_computed_valuation(store, two_stock_server) -> None:
    _seed(
        store,
        [
            _row("600000", 1000, 8.0, name="浦发银行"),
            _row("000001", 500, 25.0, name="平安银行"),
        ],
        cash=5000.0,
    )
    payload = _service(store, GatewayQuoteClient()).valuation({})
    assert payload["status"] == "ready"
    data = payload["data"]
    first, second = data["positions"]

    assert first["price_cny"] == 10.0
    assert first["market_value_cny"] == 10000.0
    assert first["cost_value_cny"] == 8000.0
    assert first["pnl_cny"] == 2000.0
    assert first["pnl_pct"] == pytest.approx(25.0)
    assert first["weight"] == pytest.approx(0.5)
    assert first["weight_incl_cash"] == pytest.approx(0.4)
    assert first["at_limit_up"] is True
    assert first["at_limit_down"] is False
    assert first["sellable_today"] is True
    assert first["sellable_qty_shares"] == 1000

    assert second["market_value_cny"] == 10000.0
    assert second["cost_value_cny"] == 12500.0
    assert second["pnl_cny"] == -2500.0
    assert second["pnl_pct"] == pytest.approx(-20.0)
    assert second["at_limit_up"] is False

    assert data["total_market_value_cny"] == 20000.0
    assert data["total_cost_cny"] == 20500.0
    assert data["total_pnl_cny"] == -500.0
    assert data["total_pnl_pct"] == pytest.approx(-500 / 20500 * 100)
    assert data["cash_cny"] == 5000.0
    assert data["total_assets_cny"] == 25000.0
    assert data["top1_weight"] == pytest.approx(0.5)
    assert data["top5_weight"] == pytest.approx(1.0)
    assert data["hhi"] == pytest.approx(0.5)
    assert data["effective_n"] == pytest.approx(2.0)
    assert data["top1_weight_incl_cash"] == pytest.approx(0.4)
    assert data["hhi_incl_cash"] == pytest.approx(0.32)
    assert data["effective_n_incl_cash"] == pytest.approx(3.125)
    assert data["quote_time"] == "2026-11-03 10:30:00"
    assert data["fetched_at"]
    assert payload["private"] is True
    assert data["private"] is True


def test_limit_down_and_alias_fields(store, monkeypatch) -> None:
    server = _serve(
        monkeypatch,
        {
            "sz000001": quote_line(
                "sz000001", "平安银行", 18.0, 19.0, -5.26, quote_time=QUOTE_TIME,
                limit_up=21.0, limit_down=18.0,
            )
        },
    )
    try:
        _seed(store, [_row("000001", 1000, 20.0, name="平安银行")])
        item = _service(store, GatewayQuoteClient()).valuation({})["data"]["positions"][0]
        assert item["at_limit_down"] is True
        assert item["at_limit_up"] is False
        assert item["market_value"] == item["market_value_cny"] == 18000.0
        assert item["qty"] == item["qty_shares"] == 1000
        assert item["price"] == item["price_cny"] == 18.0
        assert item["limit_down"] == item["limit_down_cny"] == 18.0
    finally:
        server.close()


def test_t_plus_one_and_available_qty(store, monkeypatch) -> None:
    server = _serve(
        monkeypatch,
        {
            "sh600000": quote_line("sh600000", "浦发银行", 10.0, 9.0, quote_time=QUOTE_TIME),
            "sz000001": quote_line("sz000001", "平安银行", 20.0, 19.0, quote_time=QUOTE_TIME),
            "sz300750": quote_line("sz300750", "宁德时代", 200.0, 190.0, quote_time=QUOTE_TIME),
        },
    )
    try:
        _seed(
            store,
            [
                _row("600000", 1000, 8.0, opened="2026-11-03"),
                _row("000001", 1000, 15.0, available=500, opened="2026-11-03"),
                _row("300750", 100, 150.0, opened="2026-11-02"),
            ],
        )
        items = _service(store, GatewayQuoteClient()).valuation({})["data"]["positions"]
        assert items[0]["sellable_today"] is False
        assert items[0]["sellable_qty_shares"] == 0
        assert items[1]["sellable_today"] is True
        assert items[1]["sellable_qty_shares"] == 500
        assert items[2]["sellable_today"] is True
        assert items[2]["sellable_qty_shares"] == 100
    finally:
        server.close()


def test_unavailable_and_suspended_are_excluded_from_totals(store, monkeypatch) -> None:
    server = _serve(
        monkeypatch,
        {
            "sh600000": quote_line("sh600000", "浦发银行", 10.0, 9.0, quote_time=QUOTE_TIME),
            "sz300750": quote_line("sz300750", "宁德时代", 0.0, 190.0, quote_time=QUOTE_TIME),
        },
    )
    try:
        _seed(
            store,
            [
                _row("600000", 1000, 8.0),
                _row("000001", 500, 25.0),
                _row("300750", 100, 150.0),
            ],
        )
        payload = _service(store, GatewayQuoteClient()).valuation({})
        data = payload["data"]
        assert data["priced_count"] == 1
        assert data["unpriced_count"] == 2
        assert data["total_market_value_cny"] == 10000.0
        assert data["total_cost_cny"] == 8000.0
        items = {item["code"]: item for item in data["positions"]}
        assert items["000001.SZ"]["price_unavailable"] is True
        assert items["000001.SZ"]["market_value_cny"] is None
        assert items["000001.SZ"]["weight"] == 0.0
        assert items["300750.SZ"]["price_unavailable"] is True
        assert "price_unavailable" in payload["warnings"]
    finally:
        server.close()


def test_quote_failure_marks_all_unavailable(store, monkeypatch) -> None:
    server = _serve(monkeypatch, {})
    base = server.base
    server.close()
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", base)
    _seed(store, [_row("600000", 1000, 8.0), _row("000001", 500, 25.0)])
    payload = _service(store, GatewayQuoteClient(timeout=1.0)).valuation({})
    assert payload["status"] == "ready"
    assert "quote_unavailable" in payload["warnings"]
    assert all(item["price_unavailable"] for item in payload["data"]["positions"])
    assert payload["data"]["total_market_value_cny"] == 0.0
    assert payload["data"]["total_cost_cny"] == 0.0


def test_empty_portfolio_does_not_call_quotes(store, two_stock_server) -> None:
    payload = _service(store, GatewayQuoteClient()).valuation({})
    assert payload["status"] == "empty"
    assert two_stock_server.calls == []
    data = payload["data"]
    assert data["count"] == 0
    assert data["total_assets_cny"] == 0.0
    assert data["quote_time"] is None
    assert "empty_portfolio" in payload["warnings"]
    assert payload["private"] is True


def test_stale_quote_warning(store, monkeypatch) -> None:
    server = _serve(
        monkeypatch,
        {"sh600000": quote_line("sh600000", "浦发银行", 10.0, 9.0, quote_time="2020-01-01T10:00:00+08:00")},
    )
    try:
        _seed(store, [_row("600000", 1000, 8.0)])
        payload = _service(store, GatewayQuoteClient()).valuation({})
        assert "stale_quote" in payload["warnings"]
        assert payload["data"]["quote_time"] == "2020-01-01 10:00:00"
    finally:
        server.close()


def test_100_positions_are_split_into_five_20_code_batches(store, monkeypatch) -> None:
    quotes = {}
    rows = []
    for index in range(100):
        code = f"6{index:05d}"
        digit_code = f"sh{code}"
        quotes[digit_code] = quote_line(
            digit_code, f"股票{index}", 10.0 + index, 9.0, quote_time=QUOTE_TIME
        )
        rows.append(_row(code, 100, 9.0))
    server = _serve(monkeypatch, quotes)
    try:
        _seed(store, rows)
        payload = _service(store, GatewayQuoteClient()).valuation({})
        assert payload["data"]["count"] == 100
        assert [len(call["args"]["codes"]) for call in server.calls] == [20, 20, 20, 20, 20]
    finally:
        server.close()


def test_21_codes_are_split_into_20_plus_1(monkeypatch) -> None:
    keys = [f"sh{600000 + index:06d}" for index in range(21)]
    server = _serve(
        monkeypatch, {key: quote_line(key, key, 10.0, 9.0, quote_time=QUOTE_TIME) for key in keys}
    )
    try:
        quotes = GatewayQuoteClient().fetch([key[2:] + ".SH" for key in keys])
        assert len(quotes) == 21
        assert [len(call["args"]["codes"]) for call in server.calls] == [20, 1]
    finally:
        server.close()


def test_partial_envelope_keeps_present_rows(monkeypatch) -> None:
    server = _serve(
        monkeypatch,
        {"sh600000": quote_line("sh600000", "浦发银行", 10.0, 9.0, quote_time=QUOTE_TIME)},
    )
    try:
        quotes = GatewayQuoteClient().fetch(["600000", "000001"])
        assert set(quotes) == {"600000.SH"}
    finally:
        server.close()


@pytest.mark.parametrize("status", ["unavailable", "error"])
def test_non_ok_envelope_raises_quote_error(monkeypatch, status) -> None:
    server = FakeQuoteServer({}, envelope_status=status, message="行情服务暂时不可用")
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", server.base)
    try:
        with pytest.raises(QuoteError) as excinfo:
            GatewayQuoteClient(timeout=2.0).fetch(["600000"])
        assert "行情取不到" in excinfo.value.message
    finally:
        server.close()


def test_gateway_unreachable_raises_quote_error(monkeypatch) -> None:
    server = FakeQuoteServer({})
    base = server.base
    server.close()
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", base)
    with pytest.raises(QuoteError) as excinfo:
        GatewayQuoteClient(timeout=0.5).fetch(["600000"])
    assert excinfo.value.code == "upstream_error"


def test_redirect_is_not_followed(monkeypatch) -> None:
    server = FakeQuoteServer({}, status=302, location="https://evil.example/steal")
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", server.base)
    try:
        with pytest.raises(QuoteError) as excinfo:
            GatewayQuoteClient(timeout=2.0).fetch(["600000"])
        assert excinfo.value.code == "redirect_refused"
    finally:
        server.close()


def test_gateway_url_configuration() -> None:
    assert resolve_gateway_url({}) == "http://127.0.0.1:8868"
    assert (
        resolve_gateway_url({"PORTFOLIO_GATEWAY_URL": "http://127.0.0.1:9999/"})
        == "http://127.0.0.1:9999"
    )
    for bad in (
        "http://example.com:80",
        "http://127.0.0.1",
        "ftp://127.0.0.1:80",
        "http://127.0.0.1:9999/v1/call",
    ):
        with pytest.raises(GatewayError):
            resolve_gateway_url({"PORTFOLIO_GATEWAY_URL": bad})


def test_parse_quote_item_handles_missing_limits_and_time() -> None:
    item = quote_line("sh600000", "浦发银行", 10.0, 9.0, limit_up=None, limit_down=None)
    quote = parse_quote_item("600000.SH", item)
    assert quote.limit_up is None
    assert quote.limit_down is None
    assert quote.time == "2026-11-03 10:30:00"

    item["quote_time"] = ""
    assert parse_quote_item("600000.SH", item).time is None


def test_empty_codes_make_no_request(monkeypatch) -> None:
    server = _serve(monkeypatch, {})
    try:
        assert GatewayQuoteClient().fetch([]) == {}
        assert server.calls == []
    finally:
        server.close()

def test_chives_hub_compatibility_helpers() -> None:
    assert build_url("http://127.0.0.1:9", ["sh600000"]) == "http://127.0.0.1:9/q=sh600000"
    fields = [""] * 50
    fields[1] = "浦发银行"
    fields[3] = "10.0"
    fields[4] = "9.0"
    fields[30] = "20261103103000"
    fields[47] = "-1"
    fields[48] = "-1"
    body = "~".join(fields)
    quotes = parse_quote_text(f'v_sh600000="{body}";')
    assert quotes["600000.SH"].name == "浦发银行"
    assert quotes["600000.SH"].price == 10.0
    assert quotes["600000.SH"].time == "2026-11-03 10:30:00"
