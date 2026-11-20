from __future__ import annotations

from datetime import date, timedelta

import pytest

from fakes import FakeCompanySources, company_fixture, make_service


def _series(count: int = 300, start: date = date(2025, 1, 1)) -> list[dict]:
    rows = []
    for index in range(count):
        day = start + timedelta(days=index)
        rows.append(
            {
                "数据日期": day.isoformat(),
                "当日收盘价": 10.0 + index / 100,
                "当日涨跌幅": 1.0,
                "总市值": 1e9,
                "流通市值": 8e8,
                "总股本": 1e8,
                "流通股本": 8e7,
                "PE(TTM)": float(index + 1),
                "PE(静)": float(index + 2),
                "市净率": float(index + 1) / 10,
                "市销率": float(index + 1) / 5,
            }
        )
    return rows


def _service() -> tuple:
    company = FakeCompanySources()
    company.stock_values["002553"] = _series()
    company.industry_rows = company_fixture("industry_pe.json")
    company.index_values["沪深300"] = company_fixture("index_pe_300.json")
    company.all_a = company_fixture("all_a_ttm.json")
    return make_service(company_sources=company), company


def test_stock_valuation_percentiles_are_computed_in_code():
    service, _ = _service()
    payload = service.call("company_valuation", {"scope": "stock", "code": "002553", "years": 3})
    assert payload["status"] == "ok"
    percentile = payload["data"]["percentile"]
    assert percentile["pe_ttm_pctile"] == pytest.approx(100.0)
    assert percentile["pb_mrq_pctile"] == pytest.approx(100.0)
    assert percentile["ps_ttm_pctile"] == pytest.approx(100.0)
    assert percentile["samples"] == 300
    assert payload["data"]["series"][-1]["date"] == "2025-10-27"


def test_nonpositive_current_value_has_a_reason_instead_of_a_percentile():
    service, company = _service()
    company.stock_values["002553"][-1]["PE(TTM)"] = -10.0
    payload = service.call("company_valuation", {"scope": "stock", "code": "002553"})
    assert payload["status"] == "ok"
    assert payload["data"]["percentile"]["pe_ttm_pctile"] is None
    assert "非正" in payload["data"]["percentile"]["reasons"]["pe_ttm"]


def test_second_valuation_source_is_used_with_basis_and_missing_fields():
    company = FakeCompanySources()
    company.stock_value_error = RuntimeError("boom")
    company.baidu["市盈率(TTM)"] = [
        {"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "value": float(i + 1)}
        for i in range(200)
    ]
    company.baidu["市净率"] = [
        {"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "value": float(i + 1) / 10}
        for i in range(200)
    ]
    service = make_service(company_sources=company)
    payload = service.call("company_valuation", {"scope": "stock", "code": "002553"})
    assert payload["status"] == "partial"
    assert {item["field"] for item in payload["missing"]} == {"ps_ttm", "pe_static"}
    assert payload["basis"][0]["field"] == "valuation"


def test_industry_index_and_market_scopes():
    service, _ = _service()
    industry = service.call("company_valuation", {"scope": "industry", "limit": 5})
    assert industry["status"] == "ok"
    assert industry["data"]["date"] == "2026-11-16"
    assert len(industry["data"]["rows"]) == 5
    assert industry["data"]["rows"][0]["total_market_cap_yuan"] == pytest.approx(5.3552557e11)
    assert industry["basis"][0]["field"] == "pe_static_weighted"

    index = service.call("company_valuation", {"scope": "index", "index": "000300.SH"})
    assert index["status"] == "ok"
    assert index["data"]["index"] == "沪深300"
    assert index["data"]["current"]["pe_ttm"] == pytest.approx(12.63)
    assert index["data"]["percentile"]["samples"] > 0

    market = service.call("company_valuation", {"scope": "market"})
    assert market["status"] == "ok"
    assert market["data"]["scope"] == "market"
    assert market["data"]["current"]["pe_ttm_median"] == pytest.approx(32.92)


def test_unknown_index_and_all_failures_are_unavailable():
    service, company = _service()
    payload = service.call("company_valuation", {"scope": "index", "index": "不存在的指数"})
    assert payload["status"] == "unavailable"
    assert payload["message"]

    company.index_value_error = RuntimeError("boom")
    payload = service.call("company_valuation", {"scope": "index", "index": "沪深300"})
    assert payload["status"] == "unavailable"

    company.all_a_error = RuntimeError("boom")
    assert service.call("company_valuation", {"scope": "market"})["status"] == "unavailable"


def test_bj_stock_valuation_is_accepted():
    service, company = _service()
    company.stock_values["920418"] = _series(120, start=date(2026, 1, 1))
    payload = service.call("company_valuation", {"scope": "stock", "code": "920418"})
    assert payload["status"] == "ok"
    assert payload["data"]["code"] == "920418.BJ"


def test_valuation_argument_errors():
    service, _ = _service()
    for args in (
        {"scope": "xx"},
        {"scope": "stock"},
        {"scope": "stock", "code": "002553", "years": 0},
        {"scope": "industry", "limit": 0},
        {"scope": "industry", "date": "2026/11/16"},
    ):
        payload = service.call("company_valuation", args)
        assert payload["status"] == "unavailable", args
        assert payload["message"]
