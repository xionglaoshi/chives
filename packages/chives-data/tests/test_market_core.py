from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from chives_data import config
from chives_data.market_sources import LeguActivity
from chives_data.transport import UpstreamError
from fakes import CN, FakeMarketSources, FakeSources, make_service


def _offline() -> tuple:
    sources = FakeSources()
    market = FakeMarketSources()
    service = make_service(sources, market_sources=market, now=datetime(2026, 11, 17, 16, 0, tzinfo=CN))
    return service, market


def _forbidden(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False).lower()
    for word in config.FORBIDDEN_OUTPUT:
        assert word.lower() not in text, word


def test_overview_direct_uses_market_activity():
    service, market = _offline()
    market.legu = LeguActivity(
        up=3238, down=1748, flat=231, suspended=7, limit_up=41, limit_down=25,
        active_pct=61.98, as_of=datetime(2026, 11, 17, 11, 30, tzinfo=CN),
    )
    payload = service.call("market_overview", {})
    assert payload["status"] == "partial"
    assert payload["data"]["breadth"]["up_count"] == 3238
    assert payload["basis"][0]["field"] == "up_count"
    assert {item["field"] for item in payload["missing"]} >= {"broken_count", "max_streak"}
    _forbidden(payload)


def test_overview_unavailable_when_both_sources_fail():
    service, market = _offline()
    market.legu_error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("market_overview", {})
    assert payload["status"] == "unavailable"
    assert payload["message"]


def test_movers_direct_assigns_rank():
    service, market = _offline()
    market.movers["gainers"] = [
        {"code": "301288.SZ", "name": "清研环境", "price": 20.14, "change_pct": 20.02, "amount_yuan": 2.0, "turnover_pct": 2.0},
        {"code": "301209.SZ", "name": "联合化学", "price": 52.96, "change_pct": 20.0, "amount_yuan": 3.0, "turnover_pct": 3.0},
    ]
    payload = service.call("market_movers", {"kind": "gainers", "limit": 2, "include_bj": False})
    assert payload["status"] == "ok"
    assert [row["code"] for row in payload["data"]["rows"]] == ["301288.SZ", "301209.SZ"]
    assert [row["rank"] for row in payload["data"]["rows"]] == [1, 2]
    _forbidden(payload)


def test_movers_unavailable_when_both_sources_fail():
    service, market = _offline()
    market.movers_error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("market_movers", {"kind": "losers"})
    assert payload["status"] == "unavailable"
    assert "榜单" in payload["message"]


def test_movers_parameter_error():
    service, _ = _offline()
    payload = service.call("market_movers", {"kind": "bogus"})
    assert payload["status"] == "unavailable"
    assert "kind" in payload["message"]


POOL_ROWS = [
    {"code": "002187.SZ", "name": "广百股份", "price": 8.44, "change_pct": 10.039, "amount_yuan": 1516951872.0,
     "turnover_pct": 25.98, "streak": 4, "first_seal_time": "09:30:03", "broken_times": 11,
     "industry": "一般零售", "seal_amount_yuan": 35957776.0},
    {"code": "000533.SZ", "name": "顺钠股份", "price": 10.8, "change_pct": 9.98, "amount_yuan": 1465745792.0,
     "turnover_pct": 20.08, "streak": 2, "first_seal_time": "09:30:09", "broken_times": 6,
     "industry": "电网设备", "seal_amount_yuan": 103288770.0},
]


def test_pool_direct_zt_and_missing_fields():
    service, market = _offline()
    market.ths_pools["zt"] = (41, [
        {"code": "600936.SH", "name": "北投科技", "price": 4.42, "change_pct": 9.95, "amount_yuan": None,
         "turnover_pct": 12.68, "streak": 2, "first_seal_time": "09:33:57", "broken_times": 10,
         "industry": None, "theme": "AI应用", "seal_amount_yuan": 58843460.0},
    ])
    payload = service.call("market_limit_pool", {"kind": "zt", "limit": 5})
    assert payload["status"] == "partial"
    assert payload["data"]["count"] == 41
    fields = {item["field"] for item in payload["missing"]}
    assert {"industry", "amount_yuan"} <= fields
    _forbidden(payload)


def test_pool_direct_dt_is_unavailable_without_a_direct_source():
    service, market = _offline()
    payload = service.call("market_limit_pool", {"kind": "dt"})
    assert payload["status"] == "unavailable"
    assert "跌停" in payload["message"]


def test_pool_direct_stats_computes_seal_and_promotion():
    service, market = _offline()
    rows = [
        {"code": "A.SH", "name": "A", "streak": 1},
        {"code": "B.SH", "name": "B", "streak": 2},
    ]
    market.ths_pools["zt"] = (2, rows)
    market.ths_pools["zb"] = (1, [{"code": "C.SH", "name": "C"}])
    payload = service.call("market_limit_pool", {"kind": "stats", "date": "2026-11-17"})
    assert payload["status"] == "partial"
    day = payload["data"]["days"][0]
    assert day["seal_ratio_pct"] == pytest.approx(66.67)
    assert day["promote_1to2_pct"] == 0.0  # both days see the same fake rows
    assert payload["missing"]
    _forbidden(payload)


def test_pool_direct_ladder_has_no_quote_fields():
    service, market = _offline()
    market.ths_ladder = lambda *, day: {
        "max_streak": 3,
        "tiers": [{"streak": 3, "count": 1, "rows": [{"code": "600001.SH", "name": "A"}]}],
    }
    payload = service.call("market_limit_pool", {"kind": "ladder", "date": "2026-11-17"})
    assert payload["status"] == "partial"
    assert payload["data"]["max_streak"] == 3
    assert payload["data"]["tiers"][0]["rows"][0]["code"] == "600001.SH"
    assert any(item["field"] == "rows" for item in payload["missing"])
    _forbidden(payload)


def test_overview_has_no_headlines_without_engine():
    service, market = _offline()
    market.legu = LeguActivity(
        up=3238, down=1748, flat=231, suspended=7, limit_up=41, limit_down=25,
        active_pct=61.98, as_of=datetime(2026, 11, 17, 11, 30, tzinfo=CN),
    )
    payload = service.call("market_overview", {})
    assert payload["data"]["headlines"] == []
    assert any(item["field"] == "headlines" for item in payload["missing"])
    _forbidden(payload)


def test_pool_parameter_errors():
    service, _ = _offline()
    assert service.call("market_limit_pool", {"kind": "nope"})["status"] == "unavailable"
    assert service.call("market_limit_pool", {"kind": "zt", "date": "2026-13-01"})["status"] == "unavailable"


def test_pool_unavailable_when_source_fails():
    service, market = _offline()
    market.ths_error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("market_limit_pool", {"kind": "zt"})
    assert payload["status"] == "unavailable"
    assert "涨停池" in payload["message"]
