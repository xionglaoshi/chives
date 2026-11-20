from __future__ import annotations

import pytest

from fakes import FakeCompanySources, company_fixture, make_service


def _service() -> tuple:
    company = FakeCompanySources()
    company.segment_rows = company_fixture("segments_002553.json")
    company.org_rows = company_fixture("org_002553.json")
    company.concept_rows = company_fixture("concepts_002553.json")
    company.index_cons["000300"] = company_fixture("index_cons_300.json")
    return make_service(company_sources=company), company


def test_profile_industry_concepts_and_segments():
    service, _ = _service()
    payload = service.call("company_profile", {"code": "002553", "by": "product"})
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["name"] == "南方精工"
    assert data["industry"]["name"] == "汽车零部件"
    assert data["industry"]["path"] == "交运设备-汽车-汽车零部件"
    assert data["concepts"][0]["name"]
    assert data["untrusted_text"] is True
    segments = data["segments"]
    assert segments["period"] == "2026-06-30"
    assert segments["by"] == "product"
    assert segments["count"] == 7
    assert segments["rows"][0]["revenue_yuan"] >= segments["rows"][1]["revenue_yuan"]
    assert segments["rows"][0]["revenue_share_pct"] is not None


def test_region_segments_are_available_too():
    service, company = _service()
    payload = service.call("company_profile", {"code": "002553", "by": "region"})
    assert payload["status"] == "partial" or payload["status"] == "ok"
    assert payload["data"]["segments"]["by"] == "region"


def test_index_constituents_and_membership():
    service, _ = _service()
    payload = service.call(
        "company_profile", {"index": "000300.SH", "code": "000001.SZ", "limit": 3}
    )
    assert payload["status"] == "ok"
    index = payload["data"]["index"]
    assert index["index"] == "000300.SH"
    assert index["index_name"] == "沪深300"
    assert index["count"] == 50
    assert index["returned"] == 3
    assert index["in_index"] is True
    assert index["as_of"]


def test_missing_segments_still_returns_industry_and_concepts():
    service, company = _service()
    company.segment_error = RuntimeError("boom")
    payload = service.call("company_profile", {"code": "002553"})
    assert payload["status"] == "partial"
    assert {item["field"] for item in payload["missing"]} == {"segments"}
    assert payload["data"]["industry"]["name"] == "汽车零部件"


def test_unsupported_index_and_bad_arguments():
    service, _ = _service()
    payload = service.call("company_profile", {"index": "399001.SZ"})
    assert payload["status"] == "unavailable"
    assert payload["message"]
    for args in ({}, {"code": "002553", "by": "xx"}, {"index": "不存在的指数"}):
        result = service.call("company_profile", args)
        assert result["status"] == "unavailable", args
        assert result["message"]
