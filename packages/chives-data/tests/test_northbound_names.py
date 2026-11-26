from __future__ import annotations

from datetime import datetime

from fakes import CN, FakeCompanySources, FakeMarketSources, FakeSources, make_service, tencent_fixture_rows


def _service(names: list[dict] | None = None) -> tuple:
    market = FakeMarketSources()
    market.hkex["2026-11-16"] = {
        "date": "2026-11-16",
        "channels": {"sh": {"total_turnover_yuan": 1.0, "etf_turnover_yuan": None, "trade_count": 1}},
        "top_active": {
            "sh": [
                {"rank": 1, "code": "688256.SH", "name": "CAMBRICON TECHNOLOGIES", "turnover_yuan": 1.0},
                {"rank": 2, "code": "999999.SH", "name": "UNKNOWN NAME", "turnover_yuan": 1.0},
            ],
            "sz": [],
        },
    }
    market.holdings["sh|latest"] = {
        "date": __import__("datetime").date(2026, 9, 30),
        "rows": [
            {
                "code": "600519.SH",
                "name": "KWEICHOW MOUTAI CO.,LTD.",
                "shareholding_shares": 100,
                "shareholding_pct": 1.0,
            }
        ],
    }
    market.holdings["sh|2026-06-30"] = {
        "date": __import__("datetime").date(2026, 6, 30),
        "rows": [
            {
                "code": "600519.SH",
                "name": "KWEICHOW MOUTAI CO.,LTD.",
                "shareholding_shares": 90,
                "shareholding_pct": 0.9,
            }
        ],
    }
    company = FakeCompanySources()
    company.names = names if names is not None else [
        {"代码": "688256", "名称": "寒武纪"},
        {"代码": "600519", "名称": "贵州茅台"},
    ]
    service = make_service(
        FakeSources(), market_sources=market, company_sources=company, now=datetime(2026, 11, 17, 16, 0, tzinfo=CN)
    )
    return service, company


def test_northbound_top_active_uses_chinese_names_and_keeps_unknown_english():
    service, _ = _service()
    payload = service.call("market_northbound", {"kind": "top_active", "date": "2026-11-16"})
    assert payload["status"] == "ok"
    names = {row["code"]: row["name"] for row in payload["data"]["rows"]}
    assert names["688256.SH"] == "寒武纪"
    assert names["999999.SH"] == "UNKNOWN NAME"


def test_northbound_holdings_uses_the_same_name_table():
    service, _ = _service()
    payload = service.call("market_northbound", {"kind": "holdings", "code": "600519"})
    assert payload["status"] in {"ok", "partial"}
    assert payload["data"]["rows"][0]["name"] == "贵州茅台"


def test_failed_name_table_keeps_the_original_names():
    service, company = _service()
    company.names_error = RuntimeError("boom")
    service.cache.clear()
    payload = service.call("market_northbound", {"kind": "top_active", "date": "2026-11-16"})
    names = {row["code"]: row["name"] for row in payload["data"]["rows"]}
    assert names["688256.SH"] == "CAMBRICON TECHNOLOGIES"


def test_codes_missing_from_the_name_table_get_their_name_from_one_quote_batch():
    service, _ = _service(names=[{"代码": "688256", "名称": "寒武纪"}])
    rows = dict(tencent_fixture_rows())
    any_row = dict(next(iter(rows.values())))
    any_row["name"] = "测试名称"
    service.market_sources.hkex["2026-11-16"]["top_active"]["sh"][1].update(code="601899.SH", name="ZIJIN MINING")
    service.sources.quote_tencent = {"sh601899": any_row}
    payload = service.call("market_northbound", {"kind": "top_active", "date": "2026-11-16"})
    names = {row["code"]: row["name"] for row in payload["data"]["rows"]}
    assert names["688256.SH"] == "寒武纪"
    assert names["601899.SH"] == "测试名称"
    assert service.sources.calls.count("tencent_quotes") == 1
