from __future__ import annotations

import copy

import pytest

from chives_data.news_parse import conversion_value, premium_pct
from chives_data.transport import UpstreamError
from fakes import FakeNewsSources, make_service, news_fixture


def _terms() -> list[dict]:
    return news_fixture("cb_terms.json")


def _term(code: str) -> dict:
    return next(copy.deepcopy(row) for row in _terms() if row["SECURITY_CODE"] == code)


def _service() -> tuple:
    news = FakeNewsSources()
    news.term_rows = _terms()
    news.remaining = {
        "118078": {"date": "2026-11-16", "size_yuan": 6_000_000_000.0},
        "127120": {"date": "2026-11-16", "size_yuan": 999_000_000.0},
        "123291": {"date": "2026-11-16", "size_yuan": 1_370_929_700.0},
    }
    return make_service(news_sources=news), news


def test_formulas():
    assert conversion_value(6.42, 6.22) == pytest.approx(100 / 6.42 * 6.22)
    assert premium_pct(133.35, 100 / 6.42 * 6.22) == pytest.approx((133.35 / (100 / 6.42 * 6.22) - 1) * 100)
    assert conversion_value(0, 6.22) is None
    assert premium_pct(0, 100) is None
    assert conversion_value(6.42, None) is None


def test_cb_list_values_and_formula():
    service, _ = _service()
    payload = service.call("convertible_bonds", {"kind": "list", "limit": 2})
    assert payload["status"] == "ok", payload
    rows = payload["data"]["rows"]
    assert [row["bond_code"] for row in rows] == ["118078", "123291"]
    row = next(item for item in rows if item["bond_code"] == "123291")
    assert row["bond_name"] == "佐力转债"
    assert row["underlying_code"] == "300181.SZ"
    assert row["bond_price_yuan"] == pytest.approx(129.58)
    assert row["change_pct"] == pytest.approx(3.0)
    assert row["amount_yuan"] == pytest.approx(562047936.287, rel=1e-9)
    assert row["conversion_price_yuan"] == pytest.approx(13.13)
    assert row["underlying_price_yuan"] == pytest.approx(12.85)
    expected_value = 100 / 13.13 * 12.85
    assert row["conversion_value_yuan"] == pytest.approx(round(expected_value, 4))
    assert row["premium_pct"] == pytest.approx(round((129.58 / expected_value - 1) * 100, 4))
    assert row["maturity_date"] == "2032-10-29"
    assert row["credit_rating"] == "AA"
    assert row["issue_size_yuan"] == pytest.approx(13.709297 * 100_000_000)
    assert row["remaining_size_yuan"] == pytest.approx(1_370_929_700.0)
    assert payload["data"]["total_available"] == 11
    assert "100 / conversion_price_yuan" in payload["data"]["formula"]


def test_cb_list_underlying_filter_and_empty():
    service, _ = _service()
    payload = service.call("convertible_bonds", {"kind": "list", "underlying": "300181"})
    assert [row["bond_code"] for row in payload["data"]["rows"]] == ["123291"]

    service, news = _service()
    news.term_rows = []
    payload = service.call("convertible_bonds", {"kind": "list"})
    assert payload["status"] == "ok"
    assert payload["data"]["rows"] == []


def test_cb_list_missing_underlying_price_and_remaining():
    service, news = _service()
    row = _term("123291")
    row["CONVERT_STOCK_PRICE"] = None
    row["CURRENT_BOND_PRICE"] = None
    row["TRANSFER_START_DATE"] = "2020-01-01 00:00:00"
    news.term_rows = [row]
    news.remaining = {}
    payload = service.call("convertible_bonds", {"kind": "list"})
    item = payload["data"]["rows"][0]
    assert item["conversion_value_yuan"] is None
    assert item["premium_pct"] is None
    assert item["remaining_size_yuan"] is None
    fields = {entry["field"] for entry in payload["missing"]}
    assert {"conversion_value_yuan", "premium_pct", "remaining_size_yuan"} <= fields
    assert payload["status"] == "partial"


def test_cb_list_remaining_before_conversion_period():
    service, news = _service()
    news.remaining = {}
    payload = service.call("convertible_bonds", {"kind": "list", "limit": 1})
    row = payload["data"]["rows"][0]
    assert row["remaining_size_yuan"] == row["issue_size_yuan"]
    assert row["remaining_size_computed"] is True


def test_cb_list_failure_and_arguments():
    service, news = _service()
    news.error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("convertible_bonds", {"kind": "list"})
    assert payload["status"] == "unavailable"

    service, _ = _service()
    for args in (
        {},
        {"kind": "nope"},
        {"kind": "list", "limit": 0},
        {"kind": "list", "underlying": "000300.SH"},
        {"kind": "quote"},
        {"kind": "quote", "codes": []},
        {"kind": "quote", "codes": ["12345"]},
        {"kind": "quote", "codes": [str(i) * 6 for i in range(21)]},
    ):
        payload = service.call("convertible_bonds", args)
        assert payload["status"] == "unavailable", args


def _quote_service() -> tuple:
    service, news = _service()
    news.term_rows = [_term("127120")]
    news.spot_rows = [
        {
            "code": "127120",
            "name": "千红转债",
            "trade": "133.35",
            "changepercent": "3.53",
            "amount": 469350383.488,
            "ticktime": "15:00:01",
        }
    ]
    news.remaining = {}
    return service, news


def test_cb_quote_computes_value_and_premium():
    service, _ = _quote_service()
    payload = service.call("convertible_bonds", {"kind": "quote", "codes": ["127120"]})
    assert payload["status"] == "ok", payload
    row = payload["data"]["rows"][0]
    assert row["bond_code"] == "127120"
    assert row["name"] == "千红转债"
    assert row["bond_price_yuan"] == pytest.approx(133.35)
    assert row["change_pct"] == pytest.approx(3.53)
    assert row["amount_yuan"] == pytest.approx(469350383.49)
    expected_value = 100 / 6.42 * 6.22
    assert row["conversion_value_yuan"] == pytest.approx(round(expected_value, 4))
    assert row["premium_pct"] == pytest.approx(round((133.35 / expected_value - 1) * 100, 4))
    assert row["quote_time"] == "2026-11-17T15:00:01+08:00"
    assert row["maturity_date"] == "2032-10-27"
    assert row["credit_rating"] == "AA"


def test_cb_quote_missing_spot_or_terms():
    service, news = _quote_service()
    news.errors["cb_terms_by_codes"] = UpstreamError("upstream_timeout", circuit=True)
    payload = service.call("convertible_bonds", {"kind": "quote", "codes": ["127120"]})
    assert payload["status"] == "partial"
    assert payload["data"]["rows"][0]["bond_price_yuan"] == pytest.approx(133.35)
    assert payload["data"]["rows"][0]["conversion_value_yuan"] is None
    assert {entry["field"] for entry in payload["missing"]} >= {"terms", "conversion_value_yuan"}

    service, news = _quote_service()
    news.errors["cb_spot"] = UpstreamError("upstream_timeout", circuit=True)
    payload = service.call("convertible_bonds", {"kind": "quote", "codes": ["127120"]})
    assert payload["status"] == "partial"
    assert payload["data"]["rows"][0]["bond_price_yuan"] is None
    assert payload["data"]["rows"][0]["conversion_value_yuan"] is not None

    service, news = _quote_service()
    news.error = UpstreamError("upstream_timeout", circuit=True)
    payload = service.call("convertible_bonds", {"kind": "quote", "codes": ["127120"]})
    assert payload["status"] == "unavailable"
