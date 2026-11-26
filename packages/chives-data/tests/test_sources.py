from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from chives_data.sources import (
    parse_bond_frame,
    parse_global_sina,
    parse_global_tencent,
    parse_sina_index_daily,
    parse_sina_minutes,
    parse_sina_quotes,
    parse_tencent_kline,
    parse_tencent_minutes,
    parse_tencent_quotes,
    rate_items,
)
from fakes import FIXTURES, load_json


def test_tencent_quote_parser_keeps_raw_units():
    text = (FIXTURES / "tencent_quotes.txt").read_text(encoding="utf-8")
    rows = parse_tencent_quotes(text)
    assert rows["sz002553"]["volume_lots"] == 153401
    assert rows["sz002553"]["amount_wan"] == 23251
    assert rows["sz002553"]["quote_time"].tzinfo is not None


def test_sina_quote_parser_units():
    line = (
        'var hq_str_sh600000="浦发银行,9.98,10.02,10.15,10.20,9.95,10.15,10.16,'
        "84250800,853310000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,"
        '2026-11-02,13:52:37,00";'
    )
    rows = parse_sina_quotes(line)
    assert rows["sh600000"]["volume_shares"] == 84250800
    assert rows["sh600000"]["amount_yuan"] == 853310000.0
    assert rows["sh600000"]["quote_time"].isoformat().endswith("+08:00")


def test_index_fixture_parser_applies_lot_factor_when_amount_is_present():
    bars = parse_sina_index_daily(load_json("index_bars.json"))
    first = bars[0]
    assert first["volume_shares"] == int(load_json("index_bars.json")["records"][0]["volume"] * 100)
    assert first["amount_yuan"] == load_json("index_bars.json")["records"][0]["amount"]


def test_tencent_kline_parser_units():
    payload = {
        "data": {
            "sh600519": {
                "day": [
                    ["2026-11-03", "10.0", "10.5", "10.6", "9.9", "1234"],
                ]
            }
        }
    }
    bars = parse_tencent_kline(payload, "sh600519", start=date(2026, 11, 1), end=date(2026, 11, 10))
    assert bars[0]["volume_shares"] == 123400
    assert bars[0]["amount_yuan"] is None


def test_sina_minute_parser_units():
    rows = parse_sina_minutes(
        [
            {
                "day": "2026-11-03 09:31:00",
                "open": "10.0",
                "high": "10.1",
                "low": "9.9",
                "close": "10.0",
                "volume": "100",
                "amount": "1000.0",
            }
        ]
    )
    assert rows[0]["volume_shares"] == 100
    assert rows[0]["ts"].tzinfo is not None


def test_tencent_minute_parser_differences_cumulative_values():
    payload = {
        "data": {
            "sh600519": {
                "data": {
                    "date": "20261103",
                    "data": ["0931 10.0 100 100000", "0932 10.1 250 250500"],
                }
            }
        }
    }
    day, rows = parse_tencent_minutes(payload, "sh600519")
    assert day == date(2026, 11, 3)
    assert rows[0]["volume_shares"] == 10000
    assert rows[1]["volume_shares"] == 15000
    assert rows[1]["amount_yuan"] == 150500.0


def test_global_fixtures_parse():
    tencent = parse_global_tencent(
        (FIXTURES / "global" / "tencent_global.txt").read_text(encoding="utf-8"),
        now=datetime(2026, 11, 17, tzinfo=None),
    )
    sina = parse_global_sina(
        (FIXTURES / "global" / "sina_global.txt").read_text(encoding="utf-8"),
        now=datetime(2026, 11, 17, tzinfo=None),
    )
    assert "usDJI" in tencent and "hkHSI" in tencent
    assert "hf_CHA50CFD" in sina and "gb_hxc" in sina


def test_bond_frame_and_rate_items():
    frame = [
        {"日期": "2026-11-14", "美国国债收益率10年": 4.2, "中国国债收益率10年": 1.8},
        {"日期": "2026-11-17", "美国国债收益率10年": 4.25, "中国国债收益率10年": 1.82},
    ]
    series = parse_bond_frame(frame)
    items = rate_items(series, now=datetime(2026, 11, 17, tzinfo=None))
    us10 = next(item for item in items if item["key"] == "us10y")
    assert us10["price"] == 4.25
    assert us10["change_bp"] == 5.0
    spread = next(item for item in items if item["key"] == "cn_us_10y_spread")
    assert spread["price"] == pytest.approx(2.43)
