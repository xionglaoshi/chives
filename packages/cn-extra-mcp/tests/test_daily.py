from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cn_extra_mcp import daily, global_market, server

FRAME = pd.read_csv(Path(__file__).parent / "fixtures/daily/sz300750_20261110_17.csv")


@pytest.fixture
def calls(monkeypatch) -> list[tuple[str, str, str, str]]:
    seen: list[tuple[str, str, str, str]] = []

    def fake(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
        seen.append((symbol, start, end, adjust))
        return FRAME.copy()

    global_market.clear_cache()
    monkeypatch.setattr(daily.sources, "fetch_daily_frame", fake)
    monkeypatch.setattr(global_market, "_sleep", lambda s: None)
    monkeypatch.setattr(daily, "_today", lambda: date(2026, 11, 17))
    return seen


def test_bars_carry_amount_and_turnover(calls) -> None:
    payload = daily.cn_get_daily_bars("300750.SZ", "2026-11-10", "2026-11-17")
    assert payload["ok"] and payload["status"] == "ready"
    data = payload["data"]
    assert data["code"] == "300750.SZ" and data["count"] == 5 and data["latest_date"] == "2026-11-16"
    last = data["bars"][-1]
    assert last["date"] == "2026-11-16"
    assert last["close"] == 240.5
    assert last["volume_shares"] == 36113461
    assert last["amount_yuan"] == pytest.approx(8.65489e9, rel=1e-5)
    assert last["turnover_pct"] == pytest.approx(0.8476, abs=1e-4)
    # turnover is volume / float shares, as the source defines it
    assert last["turnover_pct"] == pytest.approx(last["volume_shares"] / last["float_shares"] * 100, abs=1e-3)
    assert calls == [("sz300750", "20261110", "20261117", "")]


def test_vwap_from_amount_falls_inside_day_range(calls) -> None:
    for bar in daily.cn_get_daily_bars("300750", "2026-11-10", "2026-11-17")["data"]["bars"]:
        vwap = bar["amount_yuan"] / bar["volume_shares"]
        assert bar["low"] <= vwap <= bar["high"]


def test_default_range_and_adjust_mapping(calls) -> None:
    daily.cn_get_daily_bars("300750", adjust="qfq")
    assert calls == [("sz300750", "20260918", "20261117", "qfq")]


def test_rows_outside_requested_range_are_dropped(calls) -> None:
    payload = daily.cn_get_daily_bars("300750", "2026-11-12", "2026-11-13")
    assert [b["date"] for b in payload["data"]["bars"]] == ["2026-11-12", "2026-11-13"]


def test_empty_frame_is_empty_not_error(monkeypatch, calls) -> None:
    monkeypatch.setattr(daily.sources, "fetch_daily_frame", lambda *a: pd.DataFrame())
    payload = daily.cn_get_daily_bars("300750", "2026-11-01", "2026-11-02")
    assert payload["ok"] and payload["status"] == "empty" and payload["data"]["bars"] == []


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"code": "abc"}, "invalid_symbol"),
        ({"code": "300750", "adjust": "xx"}, "invalid_argument"),
        ({"code": "300750", "start_date": "2026/11/01"}, "invalid_argument"),
        ({"code": "300750", "start_date": "2026-11-17", "end_date": "2026-11-01"}, "invalid_argument"),
        ({"code": "300750", "start_date": "2020-01-01", "end_date": "2026-11-17"}, "invalid_argument"),
    ],
)
def test_bad_arguments_do_not_call_source(calls, kwargs, code) -> None:
    payload = daily.cn_get_daily_bars(**kwargs)
    assert payload["ok"] is False and payload["error"]["code"] == code
    assert calls == []


def test_upstream_failure_and_timeout(monkeypatch, calls) -> None:
    def boom(*a):
        raise ConnectionError("reset")

    monkeypatch.setattr(daily.sources, "fetch_daily_frame", boom)
    assert daily.cn_get_daily_bars("300750")["error"]["code"] == "upstream_error"

    global_market.clear_cache()
    monkeypatch.setattr(daily.sources, "fetch_daily_frame", lambda *a: time.sleep(1))
    monkeypatch.setattr(global_market, "AKSHARE_TIMEOUT", 0.05)
    assert daily.cn_get_daily_bars("300750")["error"]["code"] == "upstream_timeout"


def test_cached_within_ttl(calls) -> None:
    daily.cn_get_daily_bars("300750", "2026-11-10", "2026-11-17")
    daily.cn_get_daily_bars("300750", "2026-11-10", "2026-11-17")
    assert len(calls) == 1


def test_dispatch(calls) -> None:
    assert server.dispatch("cn_get_daily_bars", {"code": "300750.SZ"})["status"] == "ready"
    assert server.dispatch("cn_get_daily_bars", {})["ok"] is False
