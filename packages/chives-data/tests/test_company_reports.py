from __future__ import annotations

from fakes import FakeCompanySources, company_fixture, make_service


def test_reports_are_metadata_only_and_marked_as_untrusted_text():
    company = FakeCompanySources()
    company.report_rows = company_fixture("reports_600519.json")
    service = make_service(company_sources=company)
    payload = service.call("company_reports", {"code": "600519", "limit": 2})
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["untrusted_text"] is True
    assert data["count"] == 2
    assert len(data["reports"]) == 2
    first = data["reports"][0]
    assert first["title"]
    assert first["org"]
    assert first["forecasts"]
    assert first["untrusted_text"] is True
    assert "link" not in first


def test_empty_or_failed_reports_are_unavailable():
    company = FakeCompanySources()
    company.report_rows = []
    service = make_service(company_sources=company)
    assert service.call("company_reports", {"code": "600519"})["status"] == "unavailable"
    company.report_error = RuntimeError("boom")
    assert service.call("company_reports", {"code": "600519"})["status"] == "unavailable"


def test_report_argument_errors():
    company = FakeCompanySources()
    service = make_service(company_sources=company)
    for args in ({}, {"code": "600519", "limit": 0}):
        payload = service.call("company_reports", args)
        assert payload["status"] == "unavailable"
        assert payload["message"]
