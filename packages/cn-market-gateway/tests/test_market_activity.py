from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from cn_market_gateway import config
from fakes import CN, FakeMarketSources, FakeSources, make_service

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "market"


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _rows(name: str) -> list[dict]:
    return _json(name)["result"]["data"]


def _offline() -> tuple:
    service = make_service(FakeSources(), market_sources=FakeMarketSources(),
                           now=datetime(2026, 11, 17, 16, 0, tzinfo=CN))
    return service, service.market_sources


def _forbidden(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False).lower()
    for word in config.FORBIDDEN_OUTPUT:
        assert word.lower() not in text, word


def test_dragon_tiger_full_market():
    service, market = _offline()
    market.datacenter_rows["RPT_DAILYBILLBOARD_DETAILS"] = _rows("dc_dragon.json")
    payload = service.call("market_trading_activity", {"kind": "dragon_tiger", "date": "2026-10-30"})
    assert payload["status"] == "ok"
    assert payload["data"]["count"] == 93
    first = payload["data"]["appearances"][0]
    assert first["code"] == "000568" and first["net_buy_yuan"] == 460963059.86
    _forbidden(payload)


def test_dragon_tiger_with_code_returns_seats():
    service, market = _offline()
    market.datacenter_rows["RPT_DAILYBILLBOARD_DETAILS"] = _rows("dc_dragon.json")[:1]
    market.datacenter_rows["RPT_BILLBOARD_DAILYDETAILSBUY"] = _rows("dc_seat_buy.json")
    market.datacenter_rows["RPT_BILLBOARD_DAILYDETAILSSELL"] = _rows("dc_seat_sell.json")
    payload = service.call("market_trading_activity",
                           {"kind": "dragon_tiger", "date": "2026-10-30", "code": "000568"})
    assert payload["status"] == "ok"
    seats = payload["data"]["seats"]
    assert seats and seats[0]["seat"] == "深股通专用"
    assert {seat["side"] for seat in seats} <= {"BUY", "SELL"}
    _forbidden(payload)


def test_block_trades_units_and_premium_percent():
    service, market = _offline()
    market.datacenter_rows["RPT_DATA_BLOCKTRADE"] = _rows("dc_block.json")
    payload = service.call("market_trading_activity",
                           {"kind": "block_trades", "code": "600519", "days": 30, "date": "2026-11-17"})
    assert payload["status"] == "ok"
    first = payload["data"]["records"][0]
    assert first["deal_volume_shares"] == 16900
    assert first["deal_amount_yuan"] == 23830700.0
    second = payload["data"]["records"][1]
    assert second["premium_pct"] == -8.756081  # -0.0875608 decimal -> percent
    _forbidden(payload)


def test_margin_rows_and_units():
    service, market = _offline()
    market.datacenter_rows["RPTA_WEB_RZRQ_GGMX"] = _rows("dc_margin.json")
    payload = service.call("market_trading_activity", {"kind": "margin", "code": "002553", "days": 5})
    assert payload["status"] == "ok"
    first = payload["data"]["records"][0]
    assert first["trade_date"] == "2026-11-16"
    assert first["financing_balance_yuan"] == 174075926.0
    assert first["short_volume_shares"] == 11100
    assert len(payload["data"]["records"]) == 5
    _forbidden(payload)


def test_activity_requires_code_for_block_and_margin():
    service, _ = _offline()
    assert "code" in service.call("market_trading_activity", {"kind": "block_trades"})["message"]
    assert "code" in service.call("market_trading_activity", {"kind": "margin"})["message"]


def test_activity_upstream_failure_is_unavailable():
    service, market = _offline()
    market.datacenter_error = RuntimeError("boom")
    for kind, args in (("dragon_tiger", {"date": "2026-10-30"}), ("margin", {"code": "002553"})):
        payload = service.call("market_trading_activity", {"kind": kind, **args})
        assert payload["status"] == "unavailable"
        assert payload["message"]


def test_northbound_daily_units_and_no_net_flow():
    service, market = _offline()
    market.hkex["2026-11-16"] = {
        "date": "2026-11-16",
        "channels": {
            "sh": {"total_turnover_yuan": 108239990000.0, "etf_turnover_yuan": 2627620000.0, "trade_count": 6258767},
            "sz": {"total_turnover_yuan": 111999640000.0, "etf_turnover_yuan": 1885360000.0, "trade_count": 6948149},
        },
        "top_active": {"sh": [{"rank": 1, "code": "688256.SH", "name": "寒武纪",
                               "turnover_yuan": 2294855983.0}], "sz": []},
    }
    payload = service.call("market_northbound", {"kind": "daily", "date": "2026-11-16"})
    assert payload["status"] == "ok"
    assert payload["data"]["total_turnover_yuan"] == 220239630000.0
    assert payload["basis"][0]["field"] == "total_turnover_yuan"
    text = json.dumps(payload, ensure_ascii=False)
    assert "net_yuan" not in text and "net_inflow" not in text
    _forbidden(payload)


def test_northbound_top_active_and_code_filter():
    service, market = _offline()
    market.hkex["2026-11-16"] = {
        "date": "2026-11-16",
        "channels": {"sh": {"total_turnover_yuan": 1.0, "etf_turnover_yuan": None, "trade_count": 1}},
        "top_active": {
            "sh": [{"rank": 1, "code": "688256.SH", "name": "寒武纪", "turnover_yuan": 1.0},
                   {"rank": 2, "code": "600519.SH", "name": "贵州茅台", "turnover_yuan": 2.0}],
            "sz": [],
        },
    }
    payload = service.call("market_northbound", {"kind": "top_active", "date": "2026-11-16", "code": "600519"})
    assert payload["status"] == "ok"
    assert [row["code"] for row in payload["data"]["rows"]] == ["600519.SH"]
    _forbidden(payload)


def test_northbound_holdings_change():
    service, market = _offline()
    market.holdings["sh|latest"] = {
        "date": date(2026, 9, 30),
        "rows": [{"code": "600519.SH", "name": "KWEICHOW MOUTAI", "shareholding_shares": 55263682,
                  "shareholding_pct": 4.42}],
    }
    market.holdings["sh|2026-06-30"] = {
        "date": date(2026, 6, 30),
        "rows": [{"code": "600519.SH", "name": "KWEICHOW MOUTAI", "shareholding_shares": 50263682,
                  "shareholding_pct": 4.0}],
    }
    payload = service.call("market_northbound", {"kind": "holdings", "code": "600519"})
    assert payload["status"] == "ok"
    assert payload["data"]["date"] == "2026-09-30"
    assert payload["data"]["previous_date"] == "2026-06-30"
    row = payload["data"]["rows"][0]
    assert row["change_shares"] == 5_000_000
    assert row["change_pct_points"] == 0.42
    _forbidden(payload)


def test_northbound_holdings_rejects_non_quarter_date_and_bj():
    service, _ = _offline()
    bad = service.call("market_northbound", {"kind": "holdings", "date": "2026-09-29"})
    assert bad["status"] == "unavailable"
    assert "季度末" in bad["message"]
    bj = service.call("market_northbound", {"kind": "holdings", "code": "920083"})
    assert bj["status"] == "unavailable"
    assert "北交所" in bj["message"]


def test_northbound_missing_previous_quarter_is_partial():
    service, market = _offline()
    market.holdings["sh|latest"] = {
        "date": date(2026, 9, 30),
        "rows": [{"code": "600519.SH", "name": "KWEICHOW MOUTAI", "shareholding_shares": 55263682,
                  "shareholding_pct": 4.42}],
    }
    payload = service.call("market_northbound", {"kind": "holdings", "code": "600519"})
    assert payload["status"] == "partial"
    assert payload["data"]["rows"][0]["change_shares"] is None
    assert payload["missing"][0]["field"] == "change_shares"


def test_northbound_daily_unavailable_for_unknown_date():
    service, _ = _offline()
    payload = service.call("market_northbound", {"kind": "daily", "date": "2026-11-15"})
    assert payload["status"] == "unavailable"
    assert "交易日" in payload["message"]


def test_hkex_holdings_names_are_complete():
    import gzip

    from cn_market_gateway.market_sources import parse_hkex_holdings

    html = gzip.decompress((FIXTURES / "hkex_holdings_sh.html.gz").read_bytes()).decode("utf-8")
    rows = {row["code"]: row for row in parse_hkex_holdings(html)["rows"]}
    name = rows["600519.SH"]["name"]
    assert name.startswith("KWEICHOW MOUTAI")
    assert "(" not in name and "#" not in name


def test_northbound_holdings_without_code_merges_both_channels_with_limit_and_sort():
    service, market = _offline()

    def quarter(rows_sh, rows_sz, prev_sh, prev_sz):
        market.holdings["sh|latest"] = {"date": date(2026, 9, 30), "rows": rows_sh}
        market.holdings["sz|latest"] = {"date": date(2026, 9, 30), "rows": rows_sz}
        market.holdings["sh|2026-06-30"] = {"date": date(2026, 6, 30), "rows": prev_sh}
        market.holdings["sz|2026-06-30"] = {"date": date(2026, 6, 30), "rows": prev_sz}

    def row(code, shares, pct):
        return {"code": code, "name": code, "shareholding_shares": shares, "shareholding_pct": pct}

    quarter(
        [row("600519.SH", 100, 4.0), row("600000.SH", 50, 1.0)],
        [row("000001.SZ", 300, 2.0)],
        [row("600519.SH", 90, 3.9), row("600000.SH", 10, 0.5)],
        [row("000001.SZ", 280, 1.9)],
    )
    payload = service.call("market_northbound", {"kind": "holdings", "limit": 2})
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["total_count"] == 3 and data["count"] == 2
    assert [r["code"] for r in data["rows"]] == ["600000.SH", "000001.SZ"]  # change_shares 40, 20, 10
    by_pct = service.call("market_northbound", {"kind": "holdings", "limit": 1, "sort": "shareholding_pct"})
    assert by_pct["data"]["rows"][0]["code"] == "600519.SH"
    bad = service.call("market_northbound", {"kind": "holdings", "limit": 500})
    assert bad["status"] == "unavailable"
    _forbidden(payload)


def test_previous_quarter_form_keeps_the_channel_in_the_query():
    import gzip

    from cn_market_gateway.market_sources import MarketSources

    html = gzip.decompress((FIXTURES / "hkex_holdings_sz.html.gz").read_bytes()).decode("utf-8")

    class Governor:
        def __init__(self):
            self.forms = []

        def request(self, host, path, *, params=None, headers=None, encoding="utf-8"):
            assert params == {"t": "sz"}
            return html

        def request_form(self, host, path, *, form, params=None, headers=None, encoding="utf-8"):
            self.forms.append(params)
            return html  # same date: the loop stops after one submit

    governor = Governor()
    sources = MarketSources(governor)  # type: ignore[arg-type]
    current = sources.hkex_holdings("sz")
    sources.hkex_holdings("sz", day=date(current["date"].year, 6, 30))
    assert governor.forms == [{"t": "sz"}]


def test_hkex_daily_restores_leading_zeros_on_shenzhen_codes():
    import re

    from cn_market_gateway.market_sources import parse_hkex_daily

    parsed = parse_hkex_daily((FIXTURES / "hkex_daily_20261116e.js").read_text(encoding="utf-8"))
    sz_codes = [row["code"] for row in parsed["top_active"]["sz"]]
    assert sz_codes and all(re.fullmatch(r"\d{6}\.SZ", code) for code in sz_codes), sz_codes
    assert "002463.SZ" in sz_codes and "000333.SZ" in sz_codes


def test_northbound_daily_days_returns_a_trading_day_range_in_one_call():
    service, market = _offline()

    def day(d, sh):
        return {"date": d, "channels": {"sh": {"total_turnover_yuan": sh, "etf_turnover_yuan": None, "trade_count": 1},
                                         "sz": {"total_turnover_yuan": 1.0, "etf_turnover_yuan": None, "trade_count": 1}},
                "top_active": {"sh": [], "sz": []}}

    for d, v in [("2026-11-12", 3.0), ("2026-11-13", 4.0), ("2026-11-16", 5.0), ("2026-11-17", 6.0)]:
        market.hkex[d] = day(d, v)
    payload = service.call("market_northbound", {"kind": "daily", "date": "2026-11-17", "days": 3})
    assert payload["status"] == "ok"
    assert [row["date"] for row in payload["data"]["days"]] == ["2026-11-13", "2026-11-16", "2026-11-17"]
    assert payload["data"]["days"][-1]["total_turnover_yuan"] == 7.0
    assert "没有每日净买入" in payload["basis"][0]["note"]
    bad = service.call("market_northbound", {"kind": "daily", "days": 50})
    assert bad["status"] == "unavailable" and "days" in bad["message"]
    _forbidden(payload)
