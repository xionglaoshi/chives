from __future__ import annotations

import json
from datetime import datetime

from chives_data import config
from chives_data.envelope import authored_leaks
from chives_data.transport import UpstreamError
from fakes import CN, FakeMarketSources, FakeSources, make_service


def _offline() -> tuple:
    service = make_service(FakeSources(), market_sources=FakeMarketSources(),
                           now=datetime(2026, 11, 17, 16, 0, tzinfo=CN))
    return service, service.market_sources


def _forbidden(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False).lower()
    for word in config.FORBIDDEN_OUTPUT:
        assert word.lower() not in text, word
    authored = {key: payload[key] for key in ("basis", "missing", "message") if key in payload}
    assert authored_leaks(json.dumps(authored, ensure_ascii=False)) == []


BOARD_ROWS = [
    {"code": "new_kfq", "name": "开发区", "change_pct": 2.94, "amount_yuan": 2239282430.0,
     "member_count": 10, "leader": {"code": "600895.SH", "name": "张江高科", "change_pct": 6.33}},
    {"code": "new_dzqj", "name": "电子器件", "change_pct": 2.33, "amount_yuan": 61228349228.0,
     "member_count": 152, "leader": {"code": "600206.SH", "name": "有研新材", "change_pct": 10.01}},
]


THS_ROWS = [
    {"板块": "甲行业", "涨跌幅": 2.0, "总成交额": 10.0, "净流入": 1.0, "上涨家数": 3,
     "下跌家数": 1, "领涨股": "甲公司", "领涨股-涨跌幅": 5.0},
    {"板块": "乙行业", "涨跌幅": 1.0, "总成交额": 30.0, "净流入": -2.0, "上涨家数": 2,
     "下跌家数": 4, "领涨股": "乙公司", "领涨股-涨跌幅": 3.0},
]


def test_sectors_industry_summary_used_after_engine_removal():
    service, market = _offline()
    market.engine_payloads["/sectors"] = {"ok": True, "as_of": "2026-11-17T15:00:00+08:00",
                                          "taxonomy": "sina_industry", "rows": BOARD_ROWS}
    market.ths_industry_rows = THS_ROWS
    payload = service.call("market_sectors", {"kind": "industry", "limit": 2})
    assert payload["status"] == "partial"
    assert payload["basis"][0]["field"] == "classification"
    row = payload["data"]["rows"][0]
    assert row["name"] == "甲行业"
    assert row["up_count"] == 3
    assert row["down_count"] == 1
    assert row["limit_up_count"] is None
    assert row["amount_share_pct"] == 25.0
    assert any(item["field"] == "code" for item in payload["missing"])
    _forbidden(payload)


def test_sectors_industry_summary_sorts_by_amount():
    service, market = _offline()
    market.ths_industry_rows = THS_ROWS
    payload = service.call("market_sectors", {"kind": "industry", "sort": "amount", "limit": 1})
    assert payload["status"] == "partial"
    assert payload["data"]["rows"][0]["name"] == "乙行业"
    assert payload["data"]["rows"][0]["amount_share_pct"] == 75.0
    _forbidden(payload)


def test_sectors_industry_leaders_accepts_public_and_legacy_codes(monkeypatch):
    service, market = _offline()
    rows = [{"code": "600895.SH", "name": "张江高科", "change_pct": 7.33, "amount_yuan": 1100569048.0}]
    calls = []

    def industry_leaders(name, *, limit):
        calls.append((name, limit))
        return rows

    monkeypatch.setattr(market, "ths_industry_leaders", industry_leaders, raising=False)
    for code in ("industry:半导体", "ths:半导体"):
        payload = service.call("market_sectors", {"kind": "industry", "code": code, "limit": 20})
        assert payload["status"] == "ok"
        assert payload["data"] == {"name": "半导体", "rows": rows}
        _forbidden(payload)

    assert calls == [("半导体", 5)]


def test_sectors_sina_detail_uses_node_members():
    service, market = _offline()
    market.boards["industry"] = BOARD_ROWS
    market.nodes["new_kfq"] = [{"code": "600895.SH", "name": "张江高科", "price": 27.81,
                                "change_pct": 7.33, "amount_yuan": 1100569048.0, "turnover_pct": 2.63}]
    payload = service.call("market_sectors", {"kind": "industry", "code": "new_kfq", "limit": 20})
    assert payload["status"] == "ok"
    assert payload["data"]["name"] == "开发区"
    assert payload["data"]["members"][0]["code"] == "600895.SH"
    assert payload["basis"]
    _forbidden(payload)


def test_flow_rank_direct_fallback():
    service, market = _offline()
    market.stock_flows["in"] = [{"code": "600206.SH", "name": "有研新材", "main_net_yuan": 1.0,
                                 "main_net_pct": 2.0, "change_pct": 3.0, "amount_yuan": 4.0}]
    payload = service.call("market_fund_flow", {"scope": "rank", "kind": "in", "limit": 10})
    assert payload["status"] == "ok"
    assert payload["data"]["rows"][0]["rank"] == 1
    assert payload["basis"]
    _forbidden(payload)


def test_flow_sector_direct_fallback():
    service, market = _offline()
    market.sector_flows["out"] = [{"code": "new_dzqj", "name": "电子器件", "main_net_yuan": -1.0,
                                   "main_net_pct": -2.0, "change_pct": -1.0, "amount_yuan": None}]
    payload = service.call("market_fund_flow", {"scope": "sector", "kind": "out", "limit": 5})
    assert payload["status"] == "ok"
    assert payload["data"]["rows"][0]["main_net_yuan"] == -1.0
    _forbidden(payload)


def test_flow_stock_history_uses_sina_basis():
    service, market = _offline()
    market.stock_history = [
        {"date": "2026-11-16", "close": 1452.9, "main_net_yuan": 677679142.74,
         "main_net_pct": 12.09, "change_pct": 1.23, "amount_yuan": 5603596655.14},
    ]
    payload = service.call("market_fund_flow", {"scope": "stock", "code": "600519", "days": 5})
    assert payload["status"] == "ok"
    assert payload["data"]["code"] == "600519.SH"
    assert "另一套主力定义" in payload["basis"][0]["note"]
    _forbidden(payload)


def test_flow_stock_requires_code_and_surfaces_failure():
    service, market = _offline()
    payload = service.call("market_fund_flow", {"scope": "stock"})
    assert payload["status"] == "unavailable"
    market.stock_history_error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("market_fund_flow", {"scope": "stock", "code": "600519"})
    assert payload["status"] == "unavailable"
    assert "资金流" in payload["message"]


def test_flow_sector_direct_returns_sina_taxonomy():
    service, market = _offline()
    market.sector_flows["in"] = [{"code": "new_kfq", "name": "开发区", "main_net_yuan": 1.0,
                                  "main_net_pct": 1.0, "change_pct": 1.0, "amount_yuan": None}]
    payload = service.call("market_fund_flow", {"scope": "sector", "kind": "in", "limit": 5})
    assert payload["status"] == "ok"
    assert payload["data"]["rows"][0]["code"] == "new_kfq"


def test_sectors_unavailable_when_industry_summary_fails():
    service, market = _offline()
    market.boards["industry"] = BOARD_ROWS
    market.ths_industry_error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("market_sectors", {"kind": "industry"})
    assert payload["status"] == "unavailable"
    assert "行业" in payload["message"]


def test_sectors_concept_uses_existing_path():
    service, market = _offline()
    market.boards["concept"] = BOARD_ROWS
    payload = service.call("market_sectors", {"kind": "concept", "limit": 1})
    assert payload["status"] == "ok"
    assert payload["data"]["rows"][0]["code"] == "new_kfq"
    _forbidden(payload)


def test_flow_unavailable_when_source_fails():
    service, market = _offline()
    market.flows_error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("market_fund_flow", {"scope": "rank", "kind": "in"})
    assert payload["status"] == "unavailable"
    assert "资金流" in payload["message"]
