from __future__ import annotations

from datetime import datetime

import pytest

from chives_data.transport import UpstreamError
from fakes import CN, FakeSources, make_service, tencent_fixture_rows


def _service():
    sources = FakeSources()
    sources.quote_tencent = tencent_fixture_rows()
    return make_service(sources), sources


def test_quote_tencent_units_and_fields():
    service, _ = _service()
    out = service.call("market_quote", {"codes": ["600000"]})
    assert out["status"] == "ok"
    quote = out["data"]["quotes"][0]
    assert quote["code"] == "600000.SH"
    assert quote["volume_shares"] == 842508 * 100
    assert quote["amount_yuan"] == pytest.approx(85331 * 10000)
    assert quote["turnover_pct"] == pytest.approx(0.25)
    assert quote["pe_ttm"] == pytest.approx(6.53)
    assert quote["pb_mrq"] == pytest.approx(0.45)
    assert quote["quote_time"].endswith("+08:00")
    assert out["as_of"].startswith("2026-11-02")


def test_quote_partial_when_a_field_is_missing():
    service, _ = _service()
    out = service.call("market_quote", {"codes": ["002553"]})
    assert out["status"] == "partial"
    assert any(item["field"] == "pe_ttm" for item in out["missing"])


def test_quote_dedupes_and_accepts_bj():
    service, sources = _service()
    out = service.call("market_quote", {"codes": ["920418.BJ", "920418"]})
    assert len(out["data"]["quotes"]) == 1
    assert sources.calls.count("tencent_quotes") == 1


def test_quote_falls_back_to_sina():
    service, sources = _service()
    sources.quote_tencent_error = UpstreamError("upstream_network", circuit=True)
    sources.quote_sina = {
        "sh600000": {
            "name": "浦发银行",
            "price": 10.15,
            "prev_close": 10.02,
            "open": 10.0,
            "high": 10.2,
            "low": 9.98,
            "change_pct": 1.3,
            "volume_shares": 84250800,
            "amount_yuan": 853310000.0,
            "quote_time": datetime(2026, 11, 2, 13, 52, 37, tzinfo=CN),
        }
    }
    out = service.call("market_quote", {"codes": ["600000"]})
    assert out["status"] == "partial"
    assert out["data"]["quotes"][0]["volume_shares"] == 84250800
    assert any(item["field"] == "pe_ttm" for item in out["missing"])


def test_quote_all_sources_fail_is_unavailable():
    service, sources = _service()
    sources.quote_tencent_error = UpstreamError("upstream_network", circuit=True)
    sources.quote_sina_error = UpstreamError("upstream_network", circuit=True)
    out = service.call("market_quote", {"codes": ["600000"]})
    assert out["status"] == "unavailable"
    assert "稍后再试" in out["message"]


def test_quote_missing_item_is_partial():
    service, _ = _service()
    out = service.call("market_quote", {"codes": ["600000", "601398"]})
    assert out["status"] == "partial"
    assert any(item.get("item") == "601398.SH" for item in out["missing"])


@pytest.mark.parametrize("codes", [None, "600000", [], ["bad"], [str(i) for i in range(21)]])
def test_quote_argument_errors(codes):
    service, sources = _service()
    out = service.call("market_quote", {} if codes is None else {"codes": codes})
    assert out["status"] == "unavailable"
    assert sources.calls == []


def test_quote_cache_hit_does_not_call_upstream_again():
    service, sources = _service()
    service.call("market_quote", {"codes": ["600000"]})
    service.call("market_quote", {"codes": ["600000"]})
    assert sources.calls.count("tencent_quotes") == 1


def test_index_quote_omits_stock_only_fields_instead_of_reporting_them_missing():
    service, sources = _service()
    sources.quote_tencent = dict(sources.quote_tencent)
    row = dict(next(iter(tencent_fixture_rows().values())))
    row.update({"turnover_pct": None, "volume_ratio": None, "pe": None, "pb": None, "limit_up": None, "limit_down": None})
    sources.quote_tencent["sh000300"] = row
    out = service.call("market_quote", {"codes": ["000300.SH"]})
    quote = out["data"]["quotes"][0]
    assert quote["code"] == "000300.SH"
    for field in ("turnover_pct", "volume_ratio", "pe_ttm", "pb_mrq", "limit_up", "limit_down"):
        assert field not in quote
    assert not any(item.get("item") == "000300.SH" for item in out.get("missing") or [])


def test_names_lose_padding_spaces():
    from chives_data.sources import parse_tencent_quotes

    fields = ["51", "柳    工", "000528"] + ["0"] * 50
    fields[3] = "8.05"
    rows = parse_tencent_quotes('v_sz000528="' + "~".join(fields) + '";')
    assert next(iter(rows.values()))["name"] == "柳工"
