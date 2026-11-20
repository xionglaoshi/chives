from __future__ import annotations

import pytest

from fakes import FakeCompanySources, company_fixture, make_service


def _service() -> tuple:
    company = FakeCompanySources()
    company.indicators["002553.SZ"] = company_fixture("indicators_002553.json")
    company.statements["income"] = company_fixture("income_002553.json")
    company.statements["balance"] = company_fixture("balance_002553.json")
    company.statements["cashflow"] = company_fixture("cashflow_002553.json")
    return make_service(company_sources=company), company


def test_indicators_match_the_verified_annual_values():
    service, _ = _service()
    payload = service.call("company_financials", {"code": "002553", "periods": 8})
    assert payload["status"] == "ok"
    annual = next(item for item in payload["data"]["periods"] if item["report_date"] == "2025-12-31")
    assert annual["revenue_yuan"] == pytest.approx(854_144_285.25, rel=1e-9)
    assert annual["net_profit_yuan"] == pytest.approx(345_607_066.01, rel=1e-9)
    assert annual["eps_yuan"] == pytest.approx(0.9918)
    assert annual["bps_yuan"] == pytest.approx(4.445744808, rel=1e-6)
    assert annual["roe_pct"] == pytest.approx(26.54)
    assert annual["debt_ratio_pct"] == pytest.approx(17.9468, abs=0.001)
    assert annual["operating_cash_flow_yuan"] is not None


def test_income_statement_uses_yuan_and_percent_units():
    service, _ = _service()
    payload = service.call(
        "company_financials", {"code": "002553.SZ", "statement": "income", "periods": 1}
    )
    assert payload["status"] == "ok"
    period = payload["data"]["periods"][0]
    assert period["report_date"] == "2026-09-30"
    assert period["total_revenue_yuan"] == pytest.approx(653_808_278.6)
    assert period["net_profit_parent_yuan"] == pytest.approx(-35_079_519.0)
    assert period["eps_basic_yuan"] == pytest.approx(-0.0993)


def test_balance_and_cashflow_statements_are_available():
    service, _ = _service()
    balance = service.call(
        "company_financials", {"code": "002553", "statement": "balance", "periods": 1}
    )
    assert balance["status"] == "ok"
    row = balance["data"]["periods"][0]
    assert row["total_assets_yuan"] == pytest.approx(1_818_687_861.45)
    assert row["total_liabilities_yuan"] == pytest.approx(314_708_135.83)

    cashflow = service.call(
        "company_financials", {"code": "002553", "statement": "cashflow", "periods": 1}
    )
    assert cashflow["status"] == "ok"
    row = cashflow["data"]["periods"][0]
    assert row["operating_cash_flow_yuan"] == pytest.approx(149_984_120.75)


def test_missing_cash_flow_is_partial_with_a_reason():
    service, company = _service()
    company.statements["cashflow"] = []
    payload = service.call("company_financials", {"code": "002553", "periods": 2})
    assert payload["status"] == "partial"
    assert payload["missing"][0]["field"] == "operating_cash_flow_yuan"
    assert payload["data"]["periods"][0]["operating_cash_flow_yuan"] is None


def test_upstream_failure_and_bad_arguments_are_unavailable():
    company = FakeCompanySources()
    company.financial_error = RuntimeError("boom")
    service = make_service(company_sources=company)
    assert service.call("company_financials", {"code": "002553"})["status"] == "unavailable"
    for args in ({}, {"code": "002553", "statement": "xx"}, {"code": "002553", "periods": 0}):
        payload = service.call("company_financials", args)
        assert payload["status"] == "unavailable"
        assert payload["message"]


def test_bj_code_is_accepted():
    company = FakeCompanySources()
    company.indicators["920418.BJ"] = company_fixture("indicators_002553.json")[:2]
    service = make_service(company_sources=company)
    payload = service.call("company_financials", {"code": "920418", "periods": 2})
    assert payload["status"] in {"ok", "partial"}
    assert payload["data"]["code"] == "920418.BJ"
