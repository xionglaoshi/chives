from __future__ import annotations

import pandas as pd
import pytest

from cn_extra_mcp import service
from helpers import EMPTY_FRAME, TWO_DAY_ROWS, minute_frame


@pytest.fixture
def captured(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def fake_fetch(symbol: str, period: str) -> pd.DataFrame:
        calls.append((symbol, period))
        return minute_frame(TWO_DAY_ROWS)

    monkeypatch.setattr(service.sources, "fetch_minute_frame", fake_fetch)
    return calls


def test_full_window(captured) -> None:
    payload = service.cn_get_minute_bars("002553.SZ")
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["market"] == "cn"
    data = payload["data"]
    assert captured == [("sz002553", "1")]
    assert data["code"] == "002553.SZ"
    assert data["period"] == "1"
    assert data["count"] == 4
    assert data["dates"] == ["2026-10-29", "2026-10-30"]
    assert data["available_range"] == ["2026-10-29", "2026-10-30"]
    assert data["units"] == {"volume": "shares", "amount": "CNY"}
    assert data["bars"][0]["time"] == "2026-10-29T09:31:00+08:00"
    assert data["bars"][0]["volume"] == 1000


def test_date_outside_window_is_empty_never_other_day(captured) -> None:
    payload = service.cn_get_minute_bars(
        "002553", start_date="2026-01-05", end_date="2026-01-05"
    )
    assert payload["ok"] is True
    assert payload["status"] == "empty"
    assert payload["data"]["bars"] == []
    assert payload["data"]["count"] == 0
    assert payload["data"]["dates"] == []
    assert payload["data"]["available_range"] == ["2026-10-29", "2026-10-30"]


def test_partial_overlap_returns_only_overlap(captured) -> None:
    payload = service.cn_get_minute_bars(
        "002553", start_date="2026-10-30", end_date="2026-11-02"
    )
    assert payload["status"] == "ready"
    assert payload["data"]["count"] == 2
    assert payload["data"]["dates"] == ["2026-10-30"]
    assert payload["data"]["available_range"] == ["2026-10-29", "2026-10-30"]
    assert payload["data"]["requested_range"] == {
        "start_date": "2026-10-30",
        "end_date": "2026-11-02",
    }


def test_empty_source_window(captured) -> None:
    service.sources.fetch_minute_frame = lambda symbol, period: EMPTY_FRAME
    payload = service.cn_get_minute_bars("002553")
    assert payload["status"] == "empty"
    assert payload["data"]["available_range"] == []


def test_period_and_symbol_conversion(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_fetch(symbol: str, period: str) -> pd.DataFrame:
        seen.append((symbol, period))
        return minute_frame(TWO_DAY_ROWS)

    monkeypatch.setattr(service.sources, "fetch_minute_frame", fake_fetch)
    assert service.cn_get_minute_bars("600000", "5")["status"] == "ready"
    assert service.cn_get_minute_bars("600000.SH", "5")["status"] == "ready"
    assert service.cn_get_minute_bars("SZ002553", "15")["status"] == "ready"
    assert seen == [("sh600000", "5"), ("sh600000", "5"), ("sz002553", "15")]


def test_invalid_period_does_not_call_source(captured) -> None:
    payload = service.cn_get_minute_bars("002553", "7")
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "invalid_argument"
    assert captured == []


def test_invalid_symbol(captured) -> None:
    payload = service.cn_get_minute_bars("abc")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_symbol"
    assert captured == []


@pytest.mark.parametrize("field,value", [("start_date", "2026/01/05"), ("end_date", "20260105")])
def test_invalid_dates(captured, field: str, value: str) -> None:
    payload = service.cn_get_minute_bars("002553", **{field: value})
    assert payload["error"]["code"] == "invalid_argument"
    assert captured == []


def test_start_after_end(captured) -> None:
    payload = service.cn_get_minute_bars(
        "002553", start_date="2026-10-30", end_date="2026-10-29"
    )
    assert payload["error"]["code"] == "invalid_argument"
    assert captured == []


def test_upstream_failure_is_envelope(monkeypatch) -> None:
    def boom(symbol: str, period: str) -> pd.DataFrame:
        raise TimeoutError("timed out")

    monkeypatch.setattr(service.sources, "fetch_minute_frame", boom)
    payload = service.cn_get_minute_bars("002553")
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "upstream_error"


def test_bj_code_uses_bj_prefix(monkeypatch) -> None:
    seen: list[str] = []

    def fake_fetch(symbol: str, period: str) -> pd.DataFrame:
        seen.append(symbol)
        return minute_frame(TWO_DAY_ROWS)

    monkeypatch.setattr(service.sources, "fetch_minute_frame", fake_fetch)
    payload = service.cn_get_minute_bars("920418.BJ")
    assert payload["ok"] is True
    assert payload["data"]["code"] == "920418.BJ"
    assert payload["data"]["count"] == 4
    assert seen == ["bj920418"]
    assert "warnings" not in payload


def test_legacy_bj_code_warns(monkeypatch) -> None:
    monkeypatch.setattr(
        service.sources, "fetch_minute_frame", lambda symbol, period: minute_frame(TWO_DAY_ROWS)
    )
    payload = service.cn_get_minute_bars("430418")
    assert payload["ok"] is True
    assert payload["data"]["code"] == "430418.BJ"
    assert payload["warnings"] == ["legacy_bj_code"]
    assert "北交所代码已迁移为 92xxxx，旧代码数据可能停更，请改用新代码" == payload["warning_message"]


def test_legacy_bj_empty_window_still_warns(monkeypatch) -> None:
    monkeypatch.setattr(
        service.sources, "fetch_minute_frame", lambda symbol, period: EMPTY_FRAME
    )
    payload = service.cn_get_minute_bars("830799")
    assert payload["status"] == "empty"
    assert payload["warnings"] == ["legacy_bj_code"]
