from __future__ import annotations

from datetime import datetime

import pytest

from cn_market_gateway.transport import UpstreamError
from fakes import CN, FakeSources, index_fixture_bars, make_service, minute_rows


def _daily(day: str, volume: int, amount: float, close: float = 10.0) -> dict:
    return {
        "date": day,
        "open": close - 0.2,
        "high": close + 0.3,
        "low": close - 0.4,
        "close": close,
        "volume_shares": volume,
        "amount_yuan": amount,
        "turnover_pct": 1.5,
    }


def _service() -> tuple:
    sources = FakeSources()
    sources.daily_sina = [
        _daily("2026-11-02", 1000, 10000.0, 10.0),
        _daily("2026-11-03", 2000, 20000.0, 10.5),
        _daily("2026-11-04", 3000, 30000.0, 10.2),
    ]
    return make_service(sources), sources


def test_daily_bars_values_and_limit():
    service, _ = _service()
    out = service.call(
        "market_bars",
        {"code": "600519", "interval": "1d", "start": "2026-11-01", "end": "2026-11-10", "limit": 2},
    )
    assert out["status"] == "ok"
    assert out["data"]["count"] == 2
    assert [bar["time"] for bar in out["data"]["bars"]] == ["2026-11-03", "2026-11-04"]
    assert out["data"]["bars"][0]["volume_shares"] == 2000


def test_daily_tencent_fallback_marks_amount_missing():
    service, sources = _service()
    sources.sina_daily_error = UpstreamError("upstream_network", circuit=True)
    sources.daily_tencent = [
        {"date": "2026-11-03", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume_shares": 123400}
    ]
    out = service.call(
        "market_bars",
        {"code": "600519", "interval": "1d", "start": "2026-11-01", "end": "2026-11-10"},
    )
    assert out["status"] == "partial"
    assert out["data"]["bars"][0]["amount_yuan"] is None
    assert any(item["field"] == "amount_yuan" for item in out["missing"])
    assert any("成交额" in item["note"] for item in out["basis"])


def test_weekly_and_monthly_aggregation():
    service, _ = _service()
    sources = service.sources
    sources.daily_sina = [
        _daily("2026-11-02", 100, 1000.0, 10.0),
        _daily("2026-11-03", 200, 2000.0, 10.5),
        _daily("2026-11-06", 300, 3000.0, 10.2),
        _daily("2026-11-09", 400, 4000.0, 11.0),
    ]
    weekly = service.call(
        "market_bars",
        {"code": "600519", "interval": "1w", "start": "2026-11-01", "end": "2026-11-30"},
    )
    assert weekly["status"] == "ok"
    assert [bar["time"] for bar in weekly["data"]["bars"]] == ["2026-11-06", "2026-11-09"]
    assert weekly["data"]["bars"][0]["volume_shares"] == 600
    assert weekly["data"]["bars"][0]["amount_yuan"] == pytest.approx(6000.0)

    monthly = service.call(
        "market_bars",
        {"code": "600519", "interval": "1M", "start": "2026-11-01", "end": "2026-11-30"},
    )
    assert monthly["status"] == "ok"
    assert monthly["data"]["bars"][0]["time"] == "2026-11-09"


def test_index_daily_uses_index_source_and_keeps_amount():
    service, sources = _service()
    sources.index_sina = index_fixture_bars()
    out = service.call(
        "market_bars",
        {"code": "000300.SH", "interval": "1d", "start": "2026-09-01", "end": "2026-12-31", "limit": 5},
    )
    assert out["status"] == "partial"
    bars = out["data"]["bars"]
    assert len(bars) == 5
    assert bars[-1]["amount_yuan"] is not None
    assert bars[-1]["volume_shares"] == int(load_volume() * 100)


def load_volume() -> float:
    from fakes import load_json

    return float(load_json("index_bars.json")["records"][-1]["volume"])


def test_minute_bars_are_filtered_and_limited():
    service, sources = _service()
    sources.minutes_sina = minute_rows(
        [
            ("2026-11-02 09:31:00", 10.0, 10.1, 9.9, 10.0, 100, 1000.0),
            ("2026-11-02 09:32:00", 10.0, 10.2, 9.9, 10.1, 200, 2010.0),
            ("2026-11-03 09:31:00", 11.0, 11.1, 10.9, 11.0, 300, 3300.0),
        ]
    )
    out = service.call(
        "market_bars",
        {"code": "600519", "interval": "1m", "start": "2026-11-02", "end": "2026-11-02", "limit": 10},
    )
    assert out["status"] == "ok"
    assert out["data"]["count"] == 2
    assert out["data"]["bars"][0]["time"].endswith("+08:00")
    assert out["data"]["bars"][1]["volume_shares"] == 200


def test_minute_tencent_fallback_aggregates_and_marks_basis():
    service, sources = _service()
    sources.sina_minutes_error = UpstreamError("upstream_network", circuit=True)
    sources.minutes_tencent = (
        datetime(2026, 11, 3, tzinfo=CN).date(),
        minute_rows(
            [
                ("2026-11-03 09:31:00", 10.0, 10.1, 9.9, 10.0, 100, 1000.0),
                ("2026-11-03 09:32:00", 10.0, 10.2, 9.9, 10.1, 200, 2010.0),
            ]
        ),
    )
    out = service.call(
        "market_bars",
        {"code": "600519", "interval": "5m", "start": "2026-11-03", "end": "2026-11-03"},
    )
    assert out["status"] == "ok"
    assert out["data"]["count"] == 1
    assert out["data"]["bars"][0]["volume_shares"] == 300
    assert any("最近一个交易日" in item["note"] for item in out["basis"])


def test_bars_all_sources_fail_is_unavailable():
    service, sources = _service()
    sources.sina_daily_error = UpstreamError("upstream_network", circuit=True)
    sources.tencent_daily_error = UpstreamError("upstream_network", circuit=True)
    out = service.call("market_bars", {"code": "600519", "start": "2026-11-01", "end": "2026-11-10"})
    assert out["status"] == "unavailable"
    assert "K 线" in out["message"]


@pytest.mark.parametrize(
    "args",
    [
        {"code": "600519", "interval": "2h"},
        {"code": "600519", "interval": []},
        {"code": "600519", "adjust": "bad"},
        {"code": "600519", "adjust": []},
        {"code": "600519", "limit": 0},
        {"code": "600519", "limit": 1001},
        {"code": "600519", "start": "2026-11-10", "end": "2026-11-01"},
        {"code": "bad"},
    ],
)
def test_bars_argument_errors(args):
    service, sources = _service()
    out = service.call("market_bars", args)
    assert out["status"] == "unavailable"
    assert sources.calls == []
