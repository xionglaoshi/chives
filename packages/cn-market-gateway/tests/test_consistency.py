from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cn_market_gateway.sources import parse_tencent_quotes
from fakes import FIXTURES, FakeSources, make_service, minute_rows, tencent_fixture_rows

OLD_SRC = Path(__file__).resolve().parents[2] / "cn-extra-mcp" / "src"
if str(OLD_SRC) not in sys.path:
    sys.path.insert(0, str(OLD_SRC))

import cn_extra_mcp.daily as old_daily  # noqa: E402
import cn_extra_mcp.global_market as old_global  # noqa: E402
import cn_extra_mcp.service as old_service  # noqa: E402

HAND_ROWS = [
    ("2026-01-05 09:31:00", 10.0, 10.2, 9.9, 10.1, 100, 1005.0),
    ("2026-01-05 09:45:00", 10.1, 10.5, 10.0, 10.4, 200, 2070.0),
    ("2026-01-05 10:00:00", 10.4, 10.4, 10.1, 10.2, 300, 3075.0),
    ("2026-01-05 10:01:00", 10.2, 10.3, 10.0, 10.1, 400, 4060.0),
    ("2026-01-05 14:59:00", 10.1, 10.2, 9.9, 10.0, 500, 5025.0),
    ("2026-01-05 15:00:00", 10.0, 10.1, 9.8, 9.9, 600, 5955.0),
]


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "day": stamp,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
            for stamp, open_, high, low, close, volume, amount in HAND_ROWS
        ]
    )


@pytest.fixture(scope="module")
def old_minute_frame():
    return _frame()


def test_quote_matches_old_tool_after_unit_conversion(monkeypatch):
    text = (FIXTURES / "tencent_quotes.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(old_service.sources, "fetch_tencent_text", lambda symbols: text)
    old_out = old_service.cn_get_quote_snapshot(["600000"])
    assert old_out["status"] == "ready"
    old_quote = old_out["data"][0]

    sources = FakeSources()
    sources.quote_tencent = parse_tencent_quotes(text)
    new_out = make_service(sources).call("market_quote", {"codes": ["600000"]})
    new_quote = new_out["data"]["quotes"][0]

    for field in ("price", "prev_close", "open", "high", "low", "change_pct"):
        assert new_quote[field] == pytest.approx(old_quote[field])
    assert new_quote["volume_shares"] == int(old_quote["volume_lots"] * 100)
    assert new_quote["amount_yuan"] == pytest.approx(old_quote["amount_wan"] * 10000)
    assert new_quote["limit_up"] == pytest.approx(old_quote["limit_up"])
    assert new_quote["limit_down"] == pytest.approx(old_quote["limit_down"])


def test_minute_bars_match_old_tool(monkeypatch, old_minute_frame):
    monkeypatch.setattr(old_service.sources, "fetch_minute_frame", lambda symbol, period: old_minute_frame)
    old_out = old_service.cn_get_minute_bars("600519", "1", "2026-01-05", "2026-01-05")
    assert old_out["status"] == "ready"

    sources = FakeSources()
    sources.minutes_sina = minute_rows(HAND_ROWS)
    new_out = make_service(sources).call(
        "market_bars",
        {"code": "600519", "interval": "1m", "start": "2026-01-05", "end": "2026-01-05"},
    )
    assert new_out["status"] == "ok"
    old_bars = old_out["data"]["bars"]
    new_bars = new_out["data"]["bars"]
    assert len(new_bars) == len(old_bars)
    for old_bar, new_bar in zip(old_bars, new_bars):
        assert new_bar["time"] == old_bar["time"]
        assert new_bar["close"] == pytest.approx(old_bar["close"])
        assert new_bar["volume_shares"] == old_bar["volume"]
        assert new_bar["amount_yuan"] == pytest.approx(old_bar["amount"])


def test_daily_bars_match_old_tool(monkeypatch):
    frame = pd.DataFrame(
        [
            {
                "date": "2026-11-02",
                "open": 1410.0,
                "high": 1447.0,
                "low": 1395.02,
                "close": 1439.1,
                "volume": 8269122.0,
                "amount": 11849258015.0,
                "turnover": 0.006615,
                "outstanding_share": 1250081601.0,
            }
        ]
    )
    monkeypatch.setattr(old_daily.global_market, "_cached_fetch", lambda *args, **kwargs: frame)
    old_out = old_daily.cn_get_daily_bars("600519", "2026-11-01", "2026-11-10", "none")
    old_bar = old_out["data"]["bars"][0]

    sources = FakeSources()
    sources.daily_sina = [
        {
            "date": "2026-11-02",
            "open": 1410.0,
            "high": 1447.0,
            "low": 1395.02,
            "close": 1439.1,
            "volume_shares": 8269122,
            "amount_yuan": 11849258015.0,
            "turnover_pct": 0.6615,
        }
    ]
    new_out = make_service(sources).call(
        "market_bars",
        {"code": "600519", "interval": "1d", "start": "2026-11-01", "end": "2026-11-10"},
    )
    new_bar = new_out["data"]["bars"][0]
    for field in ("open", "high", "low", "close", "volume_shares", "amount_yuan", "turnover_pct"):
        assert new_bar[field] == pytest.approx(old_bar[field])
    assert new_bar["time"] == old_bar["date"]


def test_intraday_matches_old_tool(monkeypatch, old_minute_frame):
    monkeypatch.setattr(old_service.sources, "fetch_minute_frame", lambda symbol, period: old_minute_frame)
    old_out = old_service.cn_intraday_summary("600519", "2026-01-05")
    old_data = old_out["data"]

    sources = FakeSources()
    sources.minutes_sina = minute_rows(HAND_ROWS)
    new_out = make_service(sources).call("market_intraday", {"code": "600519", "date": "2026-01-05"})
    new_data = new_out["data"]
    pairs = {
        "bars": "bars",
        "first_bar_time": "first_bar_time",
        "last_bar_time": "last_bar_time",
        "complete": "complete",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "high_time": "high_time",
        "low_time": "low_time",
        "volume_total_shares": "volume_total_shares",
        "vwap": "vwap",
        "close_vs_vwap_pct": "close_vs_vwap_pct",
        "first_30min_volume_share_pct": "first_30min_volume_share_pct",
        "volume_share_from_high_bar_pct": "volume_share_from_high_bar_pct",
    }
    for old_field, new_field in pairs.items():
        assert new_data[new_field] == pytest.approx(old_data[old_field])
    assert new_data["amount_total_yuan"] == pytest.approx(old_data["amount_total_cny"])


def test_global_snapshot_matches_old_tool(monkeypatch):
    tencent_text = (FIXTURES / "global" / "tencent_global.txt").read_text(encoding="utf-8")
    sina_text = (FIXTURES / "global" / "sina_global.txt").read_text(encoding="utf-8")

    def cached(upstream, key, ttl, fn):
        return tencent_text if upstream == "tencent" else sina_text

    monkeypatch.setattr(old_global, "_cached_fetch", cached)
    old_out = old_global.cn_get_global_snapshot(["us_index"])
    old_items = old_out["data"]["groups"]["us_index"]["items"]

    from cn_market_gateway.sources import parse_global_sina, parse_global_tencent
    from fakes import make_service

    sources = FakeSources()
    sources.global_tencent_rows = parse_global_tencent(tencent_text, now=make_service(sources).now())
    sources.global_sina_rows = parse_global_sina(sina_text, now=make_service(sources).now())
    new_out = make_service(sources).call("market_global", {"groups": ["us_index"]})
    new_items = new_out["data"]["groups"]["us_index"]

    old_by_key = {item["key"]: item for item in old_items}
    new_by_key = {item["key"]: item for item in new_items}
    assert set(old_by_key) == set(new_by_key)
    for key, old_item in old_by_key.items():
        new_item = new_by_key[key]
        if old_item.get("price") is None:
            assert new_item.get("price") is None
            continue
        assert new_item["price"] == pytest.approx(old_item["price"])
        assert new_item["change_pct"] == pytest.approx(old_item["change_pct"])
        assert new_item["quote_time"] == old_item["quote_time"]
