from __future__ import annotations

import pytest

from cn_extra_mcp import service
from helpers import HAND_ROWS, minute_frame

DAY = "2026-01-05"


@pytest.fixture
def hand(monkeypatch) -> None:
    rows = [dict(row) for row in HAND_ROWS]
    monkeypatch.setattr(
        service.sources, "fetch_minute_frame", lambda symbol, period: minute_frame(rows)
    )


def test_hand_computed_summary(hand) -> None:
    payload = service.cn_intraday_summary("002553.SZ", DAY)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    data = payload["data"]

    assert data["code"] == "002553.SZ"
    assert data["date"] == DAY
    assert data["bars"] == 6
    assert data["first_bar_time"] == "09:31"
    assert data["last_bar_time"] == "15:00"
    assert data["complete"] is True
    assert data["open"] == 10.0
    assert data["high"] == 10.5
    assert data["low"] == 9.8
    assert data["close"] == 9.9
    assert data["high_time"] == "09:45"
    assert data["low_time"] == "15:00"
    assert data["volume_total_shares"] == 2100
    assert data["amount_total_cny"] == 21190.0
    assert data["vwap"] == 10.0905
    assert data["close_vs_vwap_pct"] == 1.89
    assert data["first_30min_volume_share_pct"] == 28.6
    assert data["volume_share_from_high_bar_pct"] == 95.2
    assert "sum(amount) / sum(volume)" in data["definitions"]["vwap"]
    assert data["units"] == {"volume": "shares", "amount": "CNY"}


def test_first_occurrence_of_high_and_low(monkeypatch) -> None:
    rows = [
        {"day": f"2026-01-05 09:{minute:02d}:00", "open": "10", "high": "10.5", "low": "9.5", "close": "10", "volume": "100", "amount": "1000"}
        for minute in (31, 32)
    ]
    rows.append(
        {"day": "2026-01-05 15:00:00", "open": "10", "high": "10.0", "low": "9.6", "close": "10", "volume": "100", "amount": "1000"}
    )
    monkeypatch.setattr(
        service.sources, "fetch_minute_frame", lambda symbol, period: minute_frame(rows)
    )
    data = service.cn_intraday_summary("002553", DAY)["data"]
    assert data["high_time"] == "09:31"
    assert data["low_time"] == "09:31"


def test_incomplete_day(monkeypatch) -> None:
    rows = [dict(row) for row in HAND_ROWS[:-1]]
    monkeypatch.setattr(
        service.sources, "fetch_minute_frame", lambda symbol, period: minute_frame(rows)
    )
    data = service.cn_intraday_summary("002553", DAY)["data"]
    assert data["last_bar_time"] == "14:59"
    assert data["complete"] is False


def test_empty_day_reports_available_range(hand) -> None:
    payload = service.cn_intraday_summary("002553", "2026-01-06")
    assert payload["ok"] is True
    assert payload["status"] == "empty"
    assert payload["data"]["bars"] == 0
    assert payload["data"]["available_range"] == ["2026-01-05", "2026-01-05"]


def test_zero_volume_yields_null_ratios(monkeypatch) -> None:
    rows = [
        {"day": "2026-01-05 09:31:00", "open": "10", "high": "10", "low": "10", "close": "10", "volume": "0", "amount": "0"},
        {"day": "2026-01-05 15:00:00", "open": "10", "high": "10", "low": "10", "close": "10", "volume": "0", "amount": "0"},
    ]
    monkeypatch.setattr(
        service.sources, "fetch_minute_frame", lambda symbol, period: minute_frame(rows)
    )
    data = service.cn_intraday_summary("002553", DAY)["data"]
    assert data["volume_total_shares"] == 0
    assert data["vwap"] is None
    assert data["close_vs_vwap_pct"] is None


def test_invalid_arguments(hand) -> None:
    assert service.cn_intraday_summary("abc", DAY)["error"]["code"] == "invalid_symbol"
    assert service.cn_intraday_summary("002553", "2026-1-5")["error"]["code"] == "invalid_argument"
    assert service.cn_intraday_summary("002553", "2026/01/05")["error"]["code"] == "invalid_argument"


def test_bj_code_and_legacy_warning(monkeypatch) -> None:
    seen: list[str] = []

    def fake_fetch(symbol: str, period: str):
        seen.append(symbol)
        return minute_frame([dict(row) for row in HAND_ROWS])

    monkeypatch.setattr(service.sources, "fetch_minute_frame", fake_fetch)
    current = service.cn_intraday_summary("920418.BJ", DAY)
    assert current["data"]["code"] == "920418.BJ"
    assert "warnings" not in current

    legacy = service.cn_intraday_summary("430418", DAY)
    assert legacy["data"]["code"] == "430418.BJ"
    assert legacy["warnings"] == ["legacy_bj_code"]
    assert "北交所代码已迁移" in legacy["warning_message"]
    assert seen == ["bj920418", "bj430418"]


def test_bj_empty_day_keeps_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        service.sources, "fetch_minute_frame", lambda symbol, period: minute_frame([])
    )
    payload = service.cn_intraday_summary("430418.BJ", DAY)
    assert payload["status"] == "empty"
    assert payload["warnings"] == ["legacy_bj_code"]
