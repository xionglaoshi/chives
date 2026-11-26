from __future__ import annotations

import pytest

from chives_data.transport import UpstreamError
from fakes import FakeSources, make_service, minute_rows

HAND_ROWS = [
    ("2026-01-05 09:31:00", 10.0, 10.2, 9.9, 10.1, 100, 1005.0),
    ("2026-01-05 09:45:00", 10.1, 10.5, 10.0, 10.4, 200, 2070.0),
    ("2026-01-05 10:00:00", 10.4, 10.4, 10.1, 10.2, 300, 3075.0),
    ("2026-01-05 10:01:00", 10.2, 10.3, 10.0, 10.1, 400, 4060.0),
    ("2026-01-05 14:59:00", 10.1, 10.2, 9.9, 10.0, 500, 5025.0),
    ("2026-01-05 15:00:00", 10.0, 10.1, 9.8, 9.9, 600, 5955.0),
]


def _service() -> tuple:
    sources = FakeSources()
    sources.minutes_sina = minute_rows(HAND_ROWS)
    return make_service(sources), sources


def test_intraday_definitions_match_old_tool():
    service, _ = _service()
    out = service.call("market_intraday", {"code": "600519", "date": "2026-01-05"})
    assert out["status"] == "ok"
    data = out["data"]
    assert data["bars"] == 6
    assert data["first_bar_time"] == "09:31"
    assert data["last_bar_time"] == "15:00"
    assert data["complete"] is True
    assert data["open"] == pytest.approx(10.0)
    assert data["high"] == pytest.approx(10.5)
    assert data["low"] == pytest.approx(9.8)
    assert data["close"] == pytest.approx(9.9)
    assert data["high_time"] == "09:45"
    assert data["low_time"] == "15:00"
    assert data["volume_total_shares"] == 2100
    assert data["amount_total_yuan"] == pytest.approx(21190.0)
    assert data["vwap"] == pytest.approx(10.0905)
    assert data["close_vs_vwap_pct"] == pytest.approx(1.89)
    assert data["first_30min_volume_share_pct"] == pytest.approx(28.6)
    assert data["volume_share_from_high_bar_pct"] == pytest.approx(95.2)
    assert out["as_of"].startswith("2026-01-05T15:00:00")


def test_intraday_empty_day_is_unavailable():
    service, _ = _service()
    out = service.call("market_intraday", {"code": "600519", "date": "2026-01-06"})
    assert out["status"] == "unavailable"
    assert "交易日" in out["message"]


def test_intraday_source_failure_is_unavailable():
    service, sources = _service()
    sources.sina_minutes_error = UpstreamError("upstream_network", circuit=True)
    out = service.call("market_intraday", {"code": "600519", "date": "2026-01-05"})
    assert out["status"] == "unavailable"
    assert "稍后再试" in out["message"]


@pytest.mark.parametrize("args", [{"code": "600519"}, {"code": "600519", "date": "2026/01/05"}, {"code": "bad", "date": "2026-01-05"}])
def test_intraday_argument_errors(args):
    service, sources = _service()
    out = service.call("market_intraday", args)
    assert out["status"] == "unavailable"
    assert sources.calls == []
