from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from chives_data import market_sources as ms

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "market"


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_legu_activity_parses_counts_and_time():
    activity = ms.parse_legu_activity((FIXTURES / "legu_activity.html").read_text(encoding="utf-8"))
    assert (activity.up, activity.down, activity.flat) == (3238, 1748, 231)
    assert activity.limit_up == 41 and activity.limit_down == 25
    assert activity.suspended == 7
    assert activity.as_of is not None and activity.as_of.hour == 11


def test_sina_movers_parses_units_and_filters_bj():
    payload = _json("sina_movers_gainers.json")
    assert any(str(item.get("symbol", "")).startswith("bj") for item in payload)
    rows = ms.parse_sina_movers(payload, include_bj=False)
    assert rows and all(not row["code"].endswith(".BJ") for row in rows)
    row = rows[0]
    assert row["code"] == "301288.SZ"
    assert row["amount_yuan"] == 195528320.0
    assert row["turnover_pct"] == pytest.approx(13.02202)


def test_sina_board_and_node_parsers():
    industries = ms.parse_sina_board_js((FIXTURES / "sina_industry.js").read_text(encoding="gbk"))
    assert len(industries) == 49
    assert industries[0]["code"].startswith("new_")
    concepts = ms.parse_sina_board_js((FIXTURES / "sina_concept.js").read_text(encoding="gbk"))
    assert len(concepts) == 172
    members = ms.parse_sina_node(_json("sina_node_new_kfq.json"))
    assert members[0]["code"] == "600895.SH"
    assert members[0]["amount_yuan"] == 1100569048.0


def test_sina_flow_parsers_convert_decimal_ratios():
    boards = ms.parse_sina_flow_boards(_json("sina_flow_sector.json"))
    assert boards[0]["code"] == "new_dzqj"
    assert boards[0]["main_net_pct"] == pytest.approx(10.8727)
    assert boards[0]["change_pct"] is not None
    stocks = ms.parse_sina_stock_flows(_json("sina_flow_stock.json"))
    assert stocks[0]["code"] == "600206.SH"
    assert stocks[0]["main_net_yuan"] == 2082661452.51


def test_sina_stock_history_limits_days_and_computes_amount():
    rows = ms.parse_sina_stock_history(_json("sina_flow_stock_history.json"), days=2)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-11-16"
    assert rows[0]["main_net_yuan"] == 677679142.74
    assert rows[0]["amount_yuan"] == pytest.approx(5603596655.14, rel=1e-9)


def test_ths_pool_units_and_streak():
    total, rows = ms.parse_ths_pool(_json("ths_pool_zt.json"), kind="zt")
    assert total == 41 and len(rows) == 5
    row = rows[0]
    assert row["code"] == "600936.SH"
    assert row["streak"] == 2
    assert row["first_seal_time"] == "09:33:57"
    assert row["seal_amount_yuan"] == 58843460.0
    assert row["seal_volume_shares"] == 13313000


def test_ths_broken_pool_and_ladder():
    total, rows = ms.parse_ths_pool(_json("ths_pool_zb.json"), kind="zb")
    assert total == 9 and len(rows) == 9
    assert rows[0]["streak"] is None
    ladder = ms.parse_ths_ladder(_json("ths_pool_ladder.json"))
    assert ladder["max_streak"] == 4
    assert ladder["tiers"][0]["count"] == 1


def test_datacenter_normalizers_use_documented_units():
    dragon = ms.normalize_dragon_row(ms.datacenter_rows(_json("dc_dragon.json"))[0])
    assert dragon["net_buy_yuan"] == 460963059.86
    block = ms.normalize_block_row(ms.datacenter_rows(_json("dc_block.json"))[1])
    assert block["premium_pct"] == pytest.approx(-8.756081)
    assert block["deal_volume_shares"] == 1600
    margin = ms.normalize_margin_row(ms.datacenter_rows(_json("dc_margin.json"))[0])
    assert margin["financing_balance_yuan"] == 174075926.0
    assert margin["short_volume_shares"] == 11100


def test_hkex_daily_two_days_and_units():
    for name, expected in (("hkex_daily_20261113e.js", 111733790000.0), ("hkex_daily_20261116e.js", 108239990000.0)):
        data = ms.parse_hkex_daily((FIXTURES / name).read_text(encoding="utf-8"))
        assert data["date"] == ("2026-11-13" if "1113" in name else "2026-11-16")
        assert data["channels"]["sh"]["total_turnover_yuan"] == expected
        assert data["channels"]["sh"]["trade_count"] is not None
        assert data["top_active"]["sh"][0]["turnover_yuan"] > 1_000_000_000


def test_hkex_holdings_sh_sz_and_change():
    sh = ms.parse_hkex_holdings(
        gzip.open(FIXTURES / "hkex_holdings_sh.html.gz", "rt", encoding="utf-8", errors="replace").read()
    )
    sz = ms.parse_hkex_holdings(
        gzip.open(FIXTURES / "hkex_holdings_sz.html.gz", "rt", encoding="utf-8", errors="replace").read()
    )
    assert sh["date"] == date(2026, 9, 30) and len(sh["rows"]) == 2089
    assert sz["date"] == date(2026, 9, 30) and sz["rows"]
    assert all(row["shareholding_shares"] > 0 for row in sh["rows"][:20])
    current = [{"code": "600519.SH", "shareholding_shares": 55263682, "shareholding_pct": 4.42}]
    previous = [{"code": "600519.SH", "shareholding_shares": 50263682, "shareholding_pct": 4.0}]
    changed = ms.holdings_change(current, previous)
    assert changed[0]["change_shares"] == 5_000_000
    assert changed[0]["change_pct_points"] == 0.42


def test_quarter_helpers():
    assert ms.quarter_end(date(2026, 9, 30)) == date(2026, 9, 30)
    assert ms.quarter_end(date(2026, 11, 17)) == date(2026, 12, 31)
    assert ms.previous_quarter_end(date(2026, 9, 30)) == date(2026, 6, 30)
    assert ms.previous_quarter_end(date(2026, 1, 15)) == date(2025, 12, 31)
    assert ms.next_quarter_end(date(2026, 6, 30)) == date(2026, 9, 30)


def test_no_forbidden_host_in_whitelist():
    assert not any("push" + "2" in host for host in ms.config.HOST_POLICIES)


def test_required_hosts_are_whitelisted():
    hosts = set(ms.config.HOST_POLICIES)
    assert {
        "legulegu.com",
        "vip.stock.finance.sina.com.cn",
        "money.finance.sina.com.cn",
        "datacenter-web.eastmoney.com",
        "data.10jqka.com.cn",
        "www.hkex.com.hk",
        "www3.hkexnews.hk",
    } <= hosts


def test_engine_host_and_client_are_gone():
    assert "127.0.0.1:8866" not in ms.config.HOST_POLICIES
    assert not hasattr(ms, "EngineClient")
    assert not hasattr(ms.MarketSources, "engine_get")
    assert not hasattr(ms.MarketSources, "sync_engine_health")
    assert not hasattr(ms.MarketSources, "eastmoney_open")


def test_service_health_has_no_engine_fields():
    from fakes import FakeSources, make_service

    service = make_service(FakeSources())
    health = service.health()
    assert "engine" not in health
    assert "eastmoney_open" not in health
