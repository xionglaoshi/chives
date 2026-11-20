from __future__ import annotations

import json

import pytest

from cn_market_gateway.company_parse import normalize_suggest
from fakes import FakeCompanySources, company_fixture, make_service


def _service() -> tuple:
    company = FakeCompanySources()
    company.search_rows = normalize_suggest(company_fixture("suggest_nfjg.json"))
    company.names = company_fixture("names_sample.json")
    return make_service(company_sources=company), company


def test_search_by_chinese_name_pinyin_and_duplicate_names():
    service, company = _service()
    plain = service.call("company_search", {"query": "南方精工"})
    assert plain["status"] == "ok"
    assert plain["data"]["candidates"][0]["code"] == "002553.SZ"
    assert plain["data"]["candidates"][0]["market"] == "深"
    assert plain["data"]["count"] == 1

    company.search_rows = normalize_suggest(company_fixture("suggest_hs300.json"))
    many = service.call("company_search", {"query": "沪深300", "limit": 6})
    assert many["status"] == "ok"
    codes = {item["code"] for item in many["data"]["candidates"]}
    assert {"000300.SH", "399300.SZ", "510300.SH"} <= codes
    assert {item["type"] for item in many["data"]["candidates"]} >= {"指数", "ETF"}
    assert many["data"]["count"] == len(many["data"]["candidates"])


def test_suffixed_and_prefixed_codes_are_resolved_to_the_exact_instrument():
    company = FakeCompanySources()
    company.search_rows = normalize_suggest(company_fixture("suggest_hs300.json"))
    service = make_service(company_sources=company)
    payload = service.call("company_search", {"query": "000300.SH"})
    assert payload["status"] == "ok"
    assert [item["code"] for item in payload["data"]["candidates"]] == ["000300.SH"]

    company.search_rows = [
        {
            "code": "600519.SH",
            "name": "贵州茅台",
            "market": "沪",
            "type": "股票",
            "pinyin": "GZMT",
        }
    ]
    payload = service.call("company_search", {"query": "sh600519"})
    assert payload["status"] == "ok"
    assert payload["data"]["candidates"][0]["code"] == "600519.SH"


def test_pinyin_initials_match_the_same_stock():
    company = FakeCompanySources()
    company.search_rows = normalize_suggest(company_fixture("suggest_nfjg_pinyin.json"))
    service = make_service(company_sources=company)
    payload = service.call("company_search", {"query": "nfjg"})
    assert payload["status"] == "ok"
    assert payload["data"]["candidates"][0]["code"] == "002553.SZ"


def test_local_name_table_is_used_when_search_is_unavailable():
    company = FakeCompanySources()
    company.search_error = RuntimeError("boom")
    company.names = company_fixture("names_sample.json")
    service = make_service(company_sources=company)
    payload = service.call("company_search", {"query": "南方精工"})
    assert payload["status"] == "ok"
    assert payload["data"]["candidates"][0]["code"] == "002553.SZ"
    assert payload["basis"][0]["note"].startswith("本次只匹配 A 股简称")


def test_missing_query_and_empty_result_are_unavailable():
    service, company = _service()
    for args in ({}, {"query": ""}, {"query": "南方精工", "limit": 0}):
        payload = service.call("company_search", args)
        assert payload["status"] == "unavailable"
        assert payload["message"]
    company.search_rows = []
    company.names = []
    payload = service.call("company_search", {"query": "不存在的公司"})
    assert payload["status"] == "unavailable"


def test_suggest_filters_out_non_a_share_instruments():
    rows = normalize_suggest(company_fixture("suggest_nfjg_pinyin.json"))
    assert [row["code"] for row in rows] == ["002553.SZ"]
    assert all(row["type"] in {"股票", "ETF", "指数"} for row in rows)


def test_bj_stock_is_mapped_to_bj():
    payload = {
        "QuotationCodeTable": {
            "Data": [
                {
                    "Code": "920418",
                    "Name": "苏轴股份",
                    "PinYin": "SZGF",
                    "Classify": "NEEQ",
                    "MarketType": "_TB",
                    "SecurityTypeName": "京A",
                    "SecurityType": "27",
                }
            ]
        }
    }
    rows = normalize_suggest(payload)
    assert rows[0]["code"] == "920418.BJ"
    assert rows[0]["market"] == "北"
