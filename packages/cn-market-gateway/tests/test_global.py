from __future__ import annotations

from datetime import date

import pytest

from cn_market_gateway.sources import parse_global_sina, parse_global_tencent
from cn_market_gateway.transport import UpstreamError
from fakes import FIXTURES, FakeClock, FakeSources, make_service


def _fixture(name: str) -> str:
    return (FIXTURES / "global" / name).read_text(encoding="utf-8")


def _service() -> tuple:
    sources = FakeSources()
    sources.global_tencent_rows = parse_global_tencent(_fixture("tencent_global.txt"), now=make_service(sources).now())
    sources.global_sina_rows = parse_global_sina(_fixture("sina_global.txt"), now=make_service(sources).now())
    sources.rates = {
        "us2y": {date(2026, 11, 14): 3.5, date(2026, 11, 17): 3.55},
        "us10y": {date(2026, 11, 14): 4.2, date(2026, 11, 17): 4.25},
        "cn10y": {date(2026, 11, 14): 1.8, date(2026, 11, 17): 1.82},
    }
    return make_service(sources), sources


def test_global_groups_combine_sources_and_units():
    service, _ = _service()
    out = service.call("market_global", {"groups": ["us_index", "hk_index"]})
    assert out["status"] == "ok"
    groups = out["data"]["groups"]
    dji = next(item for item in groups["us_index"] if item["key"] == "dji")
    assert dji["price"] == pytest.approx(52347.55)
    assert dji["change_pct"] == pytest.approx(0.1)
    assert dji["quote_tz"] == "America/New_York"
    assert any(item["key"] == "hxc" for item in groups["us_index"])
    assert any(item["key"] == "hsi" for item in groups["hk_index"])


def test_global_futures_use_previous_settlement_basis():
    service, _ = _service()
    out = service.call("market_global", {"groups": ["a50"]})
    assert out["status"] == "ok"
    item = out["data"]["groups"]["a50"][0]
    assert item["prev_close_kind"] == "settle"
    assert any("昨结算" in entry["note"] for entry in out["basis"])


def test_global_rates_are_percent_with_basis_points():
    service, _ = _service()
    out = service.call("market_global", {"groups": ["rates"]})
    assert out["status"] == "ok"
    us10 = next(item for item in out["data"]["groups"]["rates"] if item["key"] == "us10y")
    assert us10["price"] == pytest.approx(4.25)
    assert us10["change_bp"] == pytest.approx(5.0)
    assert any("基点" in entry["note"] for entry in out["basis"])


def test_rates_only_uses_thirty_minute_cache():
    sources = FakeSources()
    sources.rates = {
        "us10y": {date(2026, 11, 17): 4.25},
        "cn10y": {date(2026, 11, 17): 1.82},
    }
    clock = FakeClock()
    service = make_service(sources, clock=clock)
    service.call("market_global", {"groups": ["rates"]})
    clock.advance(31)
    service.call("market_global", {"groups": ["rates"]})
    assert sources.calls.count("bond_rates") == 1
    clock.advance(1801)
    service.call("market_global", {"groups": ["rates"]})
    assert sources.calls.count("bond_rates") == 2


def test_global_symbols_use_tencent_rows():
    service, _ = _service()
    out = service.call("market_global", {"symbols": ["usNVDA", "hk00700"]})
    assert out["status"] == "ok"
    assert [item["key"] for item in out["data"]["items"]] == ["usNVDA", "hk00700"]
    assert out["data"]["items"][0]["quote_tz"] == "America/New_York"
    assert out["data"]["items"][1]["quote_tz"] == "Asia/Hong_Kong"


def test_global_leaders_include_a_share_sectors():
    service, _ = _service()
    out = service.call("market_global", {"groups": ["leaders"]})
    assert out["status"] in {"ok", "partial"}
    nvda = next(item for item in out["data"]["groups"]["leaders"] if item["key"] == "usNVDA")
    assert "算力" in nvda["a_share_sectors"]


def test_global_tencent_failure_falls_back_to_sina():
    service, sources = _service()
    sources.global_tencent_error = UpstreamError("upstream_network", circuit=True)
    out = service.call("market_global", {"groups": ["a50", "fx"]})
    assert out["status"] == "ok"
    assert any(item["key"] == "a50" for item in out["data"]["groups"]["a50"])


def test_global_all_fail_is_unavailable():
    service, sources = _service()
    sources.global_tencent_error = UpstreamError("upstream_network", circuit=True)
    sources.global_sina_error = UpstreamError("upstream_network", circuit=True)
    out = service.call("market_global", {"symbols": ["usNVDA"]})
    assert out["status"] == "unavailable"
    assert "稍后再试" in out["message"]


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"groups": [], "symbols": ["usNVDA"]},
        {"groups": ["bad"]},
        {"symbols": []},
        {"symbols": ["bad"]},
        {"symbols": [f"usA{i}" for i in range(11)]},
    ],
)
def test_global_argument_errors(args):
    service, sources = _service()
    out = service.call("market_global", args)
    assert out["status"] == "unavailable"
    assert sources.calls == []
