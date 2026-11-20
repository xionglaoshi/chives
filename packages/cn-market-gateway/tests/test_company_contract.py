from __future__ import annotations

import json

import pytest

from cn_market_gateway import config
from cn_market_gateway.company_parse import normalize_suggest
from cn_market_gateway.envelope import authored_leaks
from cn_market_gateway.schemas import static_tools
from fakes import FakeCompanySources, company_fixture, make_service


def _service() -> tuple:
    company = FakeCompanySources()
    company.search_rows = normalize_suggest(company_fixture("suggest_nfjg.json"))
    company.indicators["002553.SZ"] = company_fixture("indicators_002553.json")
    company.statements["income"] = company_fixture("income_002553.json")
    company.statements["balance"] = company_fixture("balance_002553.json")
    company.statements["cashflow"] = company_fixture("cashflow_002553.json")
    company.stock_values["002553"] = company_fixture("value_002553.json")
    company.industry_rows = company_fixture("industry_pe.json")
    company.index_values["沪深300"] = company_fixture("index_pe_300.json")
    company.all_a = company_fixture("all_a_ttm.json")
    company.forecast_em = company_fixture("forecast_em.json")
    company.forecast_ths = {
        "预测年报每股收益": company_fixture("forecast_ths_eps_600519.json"),
        "预测年报净利润": company_fixture("forecast_ths_np_600519.json"),
    }
    company.rating_rows = company_fixture("ratings_600519.json")
    company.report_rows = company_fixture("reports_600519.json")
    company.earnings_rows["forecast"] = company_fixture("yjyg.json")
    company.earnings_rows["report"] = company_fixture("yjbb.json")
    company.schedule_rows = company_fixture("yysj.json")
    company.top10["20260930"] = company_fixture("top10_002553.json")
    company.fund_rows = company_fixture("funds_600519.json")
    company.holder_rows = company_fixture("holder_count_002553.json")
    company.lockup_rows = company_fixture("lockup_002553.json")
    company.lockup_market_rows = company_fixture("lockup_market_30d.json")["data"]
    company.segment_rows = company_fixture("segments_002553.json")
    company.org_rows = company_fixture("org_002553.json")
    company.concept_rows = company_fixture("concepts_002553.json")
    company.index_cons["000300"] = company_fixture("index_cons_300.json")
    return make_service(company_sources=company), company


CASES = [
    ("company_search", {"query": "南方精工"}),
    ("company_financials", {"code": "002553", "periods": 2}),
    ("company_valuation", {"scope": "stock", "code": "002553"}),
    ("company_valuation", {"scope": "industry", "limit": 3}),
    ("company_valuation", {"scope": "index", "index": "沪深300"}),
    ("company_valuation", {"scope": "market"}),
    ("company_consensus", {"code": "600519", "limit": 2}),
    ("company_reports", {"code": "600519", "limit": 2}),
    ("company_earnings", {"kind": "forecast", "period": "2026-09-30", "code": "688827"}),
    ("company_earnings", {"kind": "schedule", "period": "2026-09-30", "code": "002107"}),
    ("company_holders", {"code": "002553", "kind": "top10"}),
    ("company_holders", {"code": "600519", "kind": "funds", "limit": 2}),
    ("company_holders", {"code": "002553", "kind": "count", "limit": 2}),
    ("company_holders", {"code": "002553", "kind": "lockup", "limit": 2}),
    ("company_holders", {"kind": "lockup", "limit": 3}),
    ("company_holders", {"kind": "lockup", "sort": "date", "limit": 3}),
    ("company_profile", {"code": "002553"}),
    ("company_profile", {"index": "000300.SH", "limit": 2}),
]


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def test_every_company_tool_returns_a_clean_envelope():
    service, _ = _service()
    for tool, args in CASES:
        payload = service.call(tool, args)
        assert payload["status"] in {"ok", "partial"}, (tool, args)
        assert set(payload) >= {"status", "as_of", "data", "stale"}
        assert "source" not in _keys(payload), (tool, args)
        authored = {key: payload[key] for key in ("basis", "missing", "message") if key in payload}
        text = json.dumps(authored, ensure_ascii=False)
        assert authored_leaks(text) == [], (tool, args, text)


def test_every_company_tool_rejects_bad_arguments_without_protocol_errors():
    service, _ = _service()
    for tool, args in (
        ("company_search", {}),
        ("company_financials", {}),
        ("company_valuation", {"scope": "stock"}),
        ("company_consensus", {}),
        ("company_reports", {}),
        ("company_earnings", {"kind": "xx"}),
        ("company_holders", {}),
        ("company_profile", {}),
        ("company_financials", {"code": "000300.SH"}),
        ("company_valuation", {"scope": "stock", "code": "000300.SH"}),
    ):
        payload = service.call(tool, args)
        assert payload["status"] == "unavailable", tool
        assert isinstance(payload.get("message"), str) and payload["message"]


def test_company_tool_descriptions_name_no_source():
    for tool in static_tools():
        assert authored_leaks(json.dumps(tool, ensure_ascii=False)) == [], tool["name"]


def test_all_company_limits_are_declared_in_config():
    assert config.MAX_SEARCH_LIMIT == 20
    assert config.MAX_FINANCIAL_PERIODS == 40
    assert config.CONSENSUS_DISAGREE == pytest.approx(0.05)


def test_no_forbidden_host_is_whitelisted():
    for host in config.HOST_POLICIES:
        assert not config.is_forbidden_host(host), host
