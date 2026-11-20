from __future__ import annotations

import time

import pandas as pd
import pytest

from cn_research_mcp import service as service_module
from helpers import load, make_service

BARS = load("index_bars")
CONS = load("index_cons")


def _svc(**kw):
    kw.setdefault("index_bars", BARS)
    kw.setdefault("index_constituents", CONS)
    return make_service(**kw)


# ---------------------------------------------------------------- index argument
@pytest.mark.parametrize(
    "value,canonical,name",
    [
        ("沪深300", "000300.SH", "沪深300"),
        ("000300", "000300.SH", "沪深300"),
        ("000300.SH", "000300.SH", "沪深300"),
        ("sh000300", "000300.SH", "沪深300"),
        ("上证指数", "000001.SH", "上证指数"),
        ("399001", "399001.SZ", "深证成指"),
        ("399006.SZ", "399006.SZ", "创业板指"),
        ("科创50", "000688.SH", "科创50"),
        ("000016", "000016.SH", "上证50"),
    ],
)
def test_index_whitelist_accepts_names_and_codes(value, canonical, name):
    svc, _ = _svc()
    out = svc.cn_get_index_bars(index=value, limit=1)
    assert out["data"]["index"] == canonical and out["data"]["index_name"] == name


@pytest.mark.parametrize(
    "value", ["000300.SZ", "399001.SH", "000000", "foo", "", None, 300, "000300.HK"]
)
def test_index_whitelist_rejects_unknown(value):
    svc, fake = _svc()
    out = svc.cn_get_index_bars(index=value)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


# ---------------------------------------------------------------- index bars
def test_index_bars_default_values_and_order():
    svc, _ = _svc()
    out = svc.cn_get_index_bars()
    assert out["status"] == "ready" and out["source"] == "eastmoney"
    data = out["data"]
    assert data["count"] == len(BARS)
    assert data["start"] == BARS["date"].iloc[0] and data["end"] == BARS["date"].iloc[-1]
    dates = [bar["date"] for bar in data["bars"]]
    assert dates == sorted(dates)


def test_index_bars_limit_keeps_last_rows():
    svc, _ = _svc()
    out = svc.cn_get_index_bars(limit=5)
    bars = out["data"]["bars"]
    assert len(bars) == 5
    assert bars[-1]["date"] == BARS["date"].iloc[-1]
    assert bars[0]["date"] == BARS["date"].iloc[-5]


def test_index_bars_start_end_filter_inclusive():
    svc, _ = _svc()
    start = BARS["date"].iloc[10]
    end = BARS["date"].iloc[20]
    out = svc.cn_get_index_bars(start=start, end=end)
    dates = [bar["date"] for bar in out["data"]["bars"]]
    assert dates[0] == start and dates[-1] == end
    assert len(dates) == 11


def test_index_bars_units_confirmed_by_default():
    svc, _ = _svc()
    out = svc.cn_get_index_bars(limit=2)
    units = out["data"]["units"]
    assert units["volume"]["confirmed"] is True and units["amount"]["confirmed"] is True
    for bar in out["data"]["bars"]:
        assert bar["volume_unit"] == "lot" and bar["amount_unit"] == "yuan"
        assert bar["volume_shares"] == pytest.approx(bar["volume"] * 100)
        assert bar["amount_yuan"] == pytest.approx(bar["amount"])


def test_index_bars_units_unconfirmed_keeps_raw_values():
    svc, _ = _svc(index_units_confirmed=False)
    out = svc.cn_get_index_bars(limit=2)
    units = out["data"]["units"]
    assert units["volume"]["confirmed"] is False
    assert units["volume"]["upstream"] == "unconfirmed" and units["amount"]["upstream"] == "unconfirmed"
    for bar in out["data"]["bars"]:
        assert bar["volume_unit"] == "unconfirmed"
        assert "volume_shares" not in bar and "amount_yuan" not in bar
        assert bar["volume"] is not None and bar["amount"] is not None


def test_index_bars_cache_one_call_for_same_window():
    svc, fake = _svc()
    svc.cn_get_index_bars(limit=10)
    svc.cn_get_index_bars(limit=10)
    assert fake.count("index_bars") == 1


def test_index_bars_different_windows_hit_upstream_again():
    svc, fake = _svc()
    svc.cn_get_index_bars(limit=10)
    svc.cn_get_index_bars(limit=20)
    assert fake.count("index_bars") == 2


@pytest.mark.parametrize("limit", [0, 751, -1, 1.5, "5", True])
def test_index_bars_bad_limit(limit):
    svc, fake = _svc()
    out = svc.cn_get_index_bars(limit=limit)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


@pytest.mark.parametrize("start,end", [("2026-13-01", None), ("2026/01/01", None), ("2026-01-01", "2025-01-01")])
def test_index_bars_bad_dates(start, end):
    svc, fake = _svc()
    out = svc.cn_get_index_bars(start=start, end=end)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_index_bars_empty_table():
    svc, _ = _svc(index_bars=BARS.iloc[0:0])
    out = svc.cn_get_index_bars()
    assert out["status"] == "empty" and out["data"]["bars"] == []


def test_index_bars_upstream_error():
    svc, _ = _svc(index_bars=ValueError("bad"))
    assert svc.cn_get_index_bars()["error"]["code"] == "upstream_error"


def test_index_bars_rate_limited():
    svc, _ = _svc(index_bars=RuntimeError("429"))
    assert svc.cn_get_index_bars()["error"]["code"] == "rate_limited"


def test_index_bars_timeout(monkeypatch):
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = _svc(index_bars=lambda *args: time.sleep(1))
    assert svc.cn_get_index_bars()["error"]["code"] == "upstream_timeout"


def test_index_bars_missing_columns():
    svc, _ = _svc(index_bars=BARS.drop(columns=["amount"]))
    assert svc.cn_get_index_bars()["error"]["code"] == "upstream_error"


# ---------------------------------------------------------------- constituents
def test_index_constituents_success():
    svc, _ = _svc()
    out = svc.cn_get_index_constituents()
    assert out["status"] == "ready" and out["source"] == "csindex"
    data = out["data"]
    assert data["index"] == "000300.SH" and data["as_of"] == "2026-11-11"
    assert data["count"] == len(CONS) and data["returned"] == len(CONS)
    assert all(row["code"][-3:] in (".SH", ".SZ") for row in data["rows"])
    assert {row["market"] for row in data["rows"]} <= {"sh", "sz"}


def test_index_constituents_limit_keeps_total_count():
    svc, _ = _svc()
    out = svc.cn_get_index_constituents(limit=5)
    assert out["data"]["count"] == len(CONS)
    assert out["data"]["returned"] == 5 and len(out["data"]["rows"]) == 5


def test_index_constituents_beijing_row_kept_and_marked():
    table = CONS.copy()
    table.loc[0, "成分券代码"] = "830799"
    table.loc[0, "成分券名称"] = "艾融软件"
    table.loc[0, "交易所"] = "北京证券交易所"
    svc, _ = _svc(index_constituents=table)
    out = svc.cn_get_index_constituents()
    row = out["data"]["rows"][0]
    assert row["code"] == "830799.BJ" and row["market"] == "bj"


def test_index_constituents_unsupported_shenzhen_indices_are_empty():
    svc, fake = _svc()
    out = svc.cn_get_index_constituents(index="399006")
    assert out["status"] == "empty" and "csindex" in out["data"]["reason"]
    assert fake.calls == []


def test_index_constituents_cache():
    svc, fake = _svc()
    svc.cn_get_index_constituents()
    svc.cn_get_index_constituents(limit=5)
    assert fake.count("index_constituents") == 1


@pytest.mark.parametrize("limit", [0, 1001, -1, 1.5, "5", True])
def test_index_constituents_bad_limit(limit):
    svc, fake = _svc()
    out = svc.cn_get_index_constituents(limit=limit)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_index_constituents_bad_index():
    svc, fake = _svc()
    out = svc.cn_get_index_constituents(index="foo")
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_index_constituents_empty_table():
    svc, _ = _svc(index_constituents=CONS.iloc[0:0])
    out = svc.cn_get_index_constituents()
    assert out["status"] == "empty" and out["data"]["rows"] == []


def test_index_constituents_upstream_error():
    svc, _ = _svc(index_constituents=ValueError("bad"))
    assert svc.cn_get_index_constituents()["error"]["code"] == "upstream_error"


def test_index_constituents_timeout(monkeypatch):
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = _svc(index_constituents=lambda *args: time.sleep(1))
    assert svc.cn_get_index_constituents()["error"]["code"] == "upstream_timeout"


def test_index_constituents_missing_columns():
    svc, _ = _svc(index_constituents=CONS.drop(columns=["交易所"]))
    assert svc.cn_get_index_constituents()["error"]["code"] == "upstream_error"
