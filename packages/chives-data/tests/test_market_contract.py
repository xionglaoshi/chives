from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from chives_data import config
from chives_data.market_sources import LeguActivity
from fakes import CN, FakeMarketSources, FakeSources, make_service

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "market"


def _rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["result"]["data"]


def _service() -> tuple:
    market = FakeMarketSources()
    market.legu = LeguActivity(
        up=3238, down=1748, flat=231, suspended=7, limit_up=41, limit_down=25,
        active_pct=61.98, as_of=datetime(2026, 11, 17, 11, 30, tzinfo=CN),
    )
    market.movers["gainers"] = [
        {"code": "600519.SH", "name": "贵州茅台", "price": 1.0, "change_pct": 1.0,
         "amount_yuan": 1.0, "turnover_pct": 1.0}
    ]
    market.ths_pools["zt"] = (1, [
        {"code": "600519.SH", "name": "贵州茅台", "price": 1.0, "change_pct": 1.0,
         "amount_yuan": None, "turnover_pct": 1.0, "streak": 1, "first_seal_time": "09:30:00",
         "broken_times": 0, "industry": None, "theme": "白酒", "seal_amount_yuan": 1.0}
    ])
    market.ths_industry_rows = json.loads((FIXTURES / "ths_industry_summary.json").read_text(encoding="utf-8"))
    market.stock_flows["in"] = [
        {"code": "600519.SH", "name": "贵州茅台", "main_net_yuan": 1.0, "main_net_pct": 1.0,
         "change_pct": 1.0, "amount_yuan": 1.0}
    ]
    market.datacenter_rows["RPT_DAILYBILLBOARD_DETAILS"] = _rows("dc_dragon.json")[:2]
    market.datacenter_rows["RPT_DATA_BLOCKTRADE"] = _rows("dc_block.json")
    market.datacenter_rows["RPTA_WEB_RZRQ_GGMX"] = _rows("dc_margin.json")
    market.hkex["2026-11-16"] = {
        "date": "2026-11-16",
        "channels": {"sh": {"total_turnover_yuan": 1.0, "etf_turnover_yuan": None, "trade_count": 1}},
        "top_active": {"sh": [{"rank": 1, "code": "600519.SH", "name": "贵州茅台", "turnover_yuan": 1.0}], "sz": []},
    }
    service = make_service(FakeSources(), market_sources=market, now=datetime(2026, 11, 17, 16, 0, tzinfo=CN))
    return service, market


CASES = [
    ("market_overview", {}),
    ("market_movers", {"kind": "gainers"}),
    ("market_limit_pool", {"kind": "zt"}),
    ("market_sectors", {"kind": "industry"}),
    ("market_fund_flow", {"scope": "rank", "kind": "in"}),
    ("market_trading_activity", {"kind": "dragon_tiger", "date": "2026-10-30"}),
    ("market_northbound", {"kind": "daily", "date": "2026-11-16"}),
]


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def test_every_market_tool_passes_the_forbidden_word_contract():
    service, _ = _service()
    for tool, args in CASES:
        payload = service.call(tool, args)
        assert payload["status"] in {"ok", "partial"}, tool
        text = json.dumps(payload, ensure_ascii=False).lower()
        for word in config.FORBIDDEN_OUTPUT:
            assert word.lower() not in text, (tool, word)
        assert "source" not in _keys(payload), tool


def test_every_market_tool_rejects_wrong_argument_types_without_protocol_error():
    service, _ = _service()
    bad_args = [
        ("market_overview", []),
        ("market_movers", {"limit": 0}),
        ("market_limit_pool", {"kind": "xx"}),
        ("market_sectors", {"limit": 0}),
        ("market_fund_flow", {"scope": "xx"}),
        ("market_trading_activity", {"kind": "xx"}),
        ("market_northbound", {"kind": "xx"}),
    ]
    for tool, args in bad_args:
        payload = service.call(tool, args)
        assert payload["status"] == "unavailable", tool
        assert isinstance(payload.get("message"), str) and payload["message"], tool


def test_authored_text_check_blocks_chinese_source_names_but_not_third_party_data():
    import pytest

    from chives_data.envelope import EnvelopeLeak, basis, envelope

    with pytest.raises(EnvelopeLeak):
        envelope("ok", as_of="2026-11-17", basis_items=[basis("x", "按新浪口径统计")])
    with pytest.raises(EnvelopeLeak):
        envelope("ok", as_of="2026-11-17", basis_items=[basis("x", "使用备用口径")])
    ok = envelope("ok", as_of="2026-11-17", data={"rows": [{"name": "腾讯概念"}, {"name": "MONTHS HEALTH"}]})
    assert ok["status"] == "ok"


def test_tool_descriptions_name_no_source():
    import json as _json

    from chives_data.envelope import authored_leaks
    from chives_data.schemas import static_tools

    for tool in static_tools():
        assert authored_leaks(_json.dumps(tool, ensure_ascii=False)) == [], tool["name"]
