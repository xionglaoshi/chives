from __future__ import annotations

import json

import pytest

from fakes import FakeCompanySources, company_fixture, make_service


def _service() -> tuple:
    company = FakeCompanySources()
    company.top10["20260930"] = company_fixture("top10_002553.json")
    company.fund_rows = company_fixture("funds_600519.json")
    company.holder_rows = company_fixture("holder_count_002553.json")
    company.lockup_rows = company_fixture("lockup_002553.json")
    return make_service(company_sources=company), company


def test_top10_holders_use_float_ratio_and_keep_text_changes():
    service, _ = _service()
    payload = service.call("company_holders", {"code": "002553", "kind": "top10"})
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["period"] == "2026-09-30"
    assert data["count"] == 10
    first = data["rows"][0]
    assert first["rank"] == 1
    assert first["shares"] == pytest.approx(30_100_000.0)
    assert first["change_raw"] == "不变"
    assert first["change_shares"] is None
    assert payload["basis"][0]["field"] == "float_ratio_pct"


def test_funds_are_sorted_by_market_value_and_limited():
    service, _ = _service()
    payload = service.call("company_holders", {"code": "600519", "kind": "funds", "limit": 2})
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["period"] == "2026-09-30"
    assert data["returned"] == 2
    assert data["fund_count"] == 30
    assert data["rows"][0]["market_value_yuan"] >= data["rows"][1]["market_value_yuan"]


def test_holder_count_matches_the_verified_values():
    service, _ = _service()
    payload = service.call("company_holders", {"code": "002553", "kind": "count", "limit": 3})
    assert payload["status"] == "ok"
    latest = payload["data"]["rows"][0]
    assert latest["end_date"] == "2026-09-30"
    assert latest["holder_count"] == 77_783
    assert latest["holder_count_change"] == 8_522
    assert latest["holder_count_change_pct"] == pytest.approx(12.304182729, rel=1e-8)
    assert latest["prev_period_end"] == "2026-06-30"
    assert payload["data"]["rows"][1]["avg_hold_shares"] is None


def test_lockup_matches_the_verified_values_after_unit_conversion():
    service, _ = _service()
    payload = service.call("company_holders", {"code": "002553", "kind": "lockup", "limit": 2})
    assert payload["status"] == "ok"
    latest = payload["data"]["rows"][0]
    assert latest["free_date"] == "2026-05-26"
    assert latest["free_shares"] == pytest.approx(5_409_639.0)
    assert latest["lockup_market_cap_yuan"] == pytest.approx(108_517_400.0, rel=1e-5)
    assert latest["free_ratio_pct"] == pytest.approx(2.1114, abs=0.0001)
    assert latest["total_ratio_pct"] == pytest.approx(1.5307, abs=0.0001)


def test_bj_stock_holders_are_accepted():
    service, _ = _service()
    payload = service.call("company_holders", {"code": "920418", "kind": "lockup", "limit": 2})
    assert payload["status"] == "ok"
    assert payload["data"]["code"] == "920418.BJ"


def test_missing_period_and_failures_are_unavailable():
    service, company = _service()
    assert (
        service.call("company_holders", {"code": "600519", "kind": "funds", "period": "2020-12-31"})[
            "status"
        ]
        == "unavailable"
    )
    company.holder_error = RuntimeError("boom")
    assert service.call("company_holders", {"code": "002553", "kind": "count"})["status"] == "unavailable"


def test_holder_argument_errors():
    service, _ = _service()
    for args in (
        {"code": "002553", "kind": "xx"},
        {},
        {"code": "002553", "kind": "count", "limit": 500},
        {"code": "002553", "kind": "lockup", "period": "2026-02-30"},
    ):
        payload = service.call("company_holders", args)
        assert payload["status"] == "unavailable", args
        assert payload["message"]


def _market_service() -> tuple:
    company = FakeCompanySources()
    company.lockup_market_rows = company_fixture("lockup_market_30d.json")["data"]
    return make_service(company_sources=company), company


def test_lockup_market_returns_events_daily_summary_and_units():
    service, _ = _market_service()
    payload = service.call("company_holders", {"kind": "lockup", "limit": 200})
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["view"] == "lockup_market"
    assert data["total_count"] == 147
    assert len(data["rows"]) == 147
    assert sum(day["count"] for day in data["daily"]) == 147
    assert data["daily"][0]["date"] == "2026-11-17"
    caps = [row["market_cap_yuan"] for row in data["rows"] if row["market_cap_yuan"] is not None]
    assert caps == sorted(caps, reverse=True)
    row = next(item for item in data["rows"] if item["code"] == "600732.SH")
    assert row["shares"] == pytest.approx(1_615_725.0)
    assert row["market_cap_yuan"] == pytest.approx(18_629_309.25)
    assert row["float_ratio_pct"] == pytest.approx(0.0766884395)
    assert row["total_ratio_pct"] == pytest.approx(0.0763948251)
    assert row["holder_type"] == "股权激励限售股份"
    assert [item["field"] for item in payload["basis"]] == [
        "shares", "market_cap_yuan", "float_ratio_pct", "total_ratio_pct", "daily"
    ]


def test_lockup_market_sorts_and_limits():
    service, _ = _market_service()
    by_date = service.call(
        "company_holders", {"kind": "lockup", "sort": "date", "limit": 5, "start": "2026-11-17", "end": "2026-11-30"}
    )
    assert by_date["status"] == "ok"
    dates = [row["date"] for row in by_date["data"]["rows"]]
    assert dates == sorted(dates)
    assert by_date["data"]["total_count"] == len(by_date["data"]["rows"]) or by_date["data"]["total_count"] > 5

    by_ratio = service.call("company_holders", {"kind": "lockup", "sort": "float_ratio_pct", "limit": 5})
    ratios = [row["float_ratio_pct"] for row in by_ratio["data"]["rows"]]
    assert ratios == sorted(ratios, reverse=True)


def test_lockup_market_range_and_argument_boundaries():
    service, _ = _market_service()
    for args in (
        {"kind": "lockup", "start": "2026-11-17", "end": "2027-02-16"},
        {"kind": "lockup", "start": "2026-12-01", "end": "2026-11-17"},
        {"kind": "lockup", "start": "2026-02-30"},
        {"kind": "lockup", "limit": 201},
        {"kind": "lockup", "sort": "change_pct"},
        {"kind": "lockup", "period": "2026-09-30"},
    ):
        payload = service.call("company_holders", args)
        assert payload["status"] == "unavailable", args
        assert payload["message"]


def test_lockup_market_empty_and_upstream_failure():
    service, company = _market_service()
    company.lockup_market_rows = []
    payload = service.call("company_holders", {"kind": "lockup"})
    assert payload["status"] == "ok"
    assert payload["data"]["rows"] == []
    assert payload["data"]["daily"] == []

    company.lockup_market_error = RuntimeError("boom")
    payload = service.call(
        "company_holders", {"kind": "lockup", "start": "2026-12-01", "end": "2026-12-30"}
    )
    assert payload["status"] == "unavailable"
    assert "限售解禁" in payload["message"]


class _LockupGovernor:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.requests: list[dict[str, Any]] = []

    def request(self, host, path, *, params=None, headers=None, encoding="utf-8"):
        assert host == "datacenter-web.eastmoney.com"
        self.requests.append(dict(params or {}))
        page = int((params or {})["pageNumber"])
        return json.dumps(self.pages[page - 1])


def test_lockup_market_source_pages_and_filters():
    from chives_data.company_sources import CompanySources

    page = {"result": {"pages": 2, "data": [{"SECURITY_CODE": "600732", "FREE_DATE": "2026-11-17 00:00:00"}]}}
    governor = _LockupGovernor([page, page])
    rows = CompanySources(governor).lockup_market("2026-11-17", "2026-12-17")  # type: ignore[arg-type]
    assert len(rows) == 2
    assert [request["pageNumber"] for request in governor.requests] == ["1", "2"]
    assert governor.requests[0]["reportName"] == "RPT_LIFT_STAGE"
    assert governor.requests[0]["pageSize"] == "500"
    assert governor.requests[0]["filter"] == "(FREE_DATE>='2026-11-17')(FREE_DATE<='2026-12-17')"


def test_lockup_market_table_is_cached_across_sort_and_limit():
    service, company = _market_service()
    first = service.call("company_holders", {"kind": "lockup", "limit": 1})
    second = service.call("company_holders", {"kind": "lockup", "sort": "date", "limit": 5})
    assert first["status"] == "ok" and second["status"] == "ok"
    assert company.calls.count("lockup_market") == 1
    assert first["data"]["total_count"] == second["data"]["total_count"]
