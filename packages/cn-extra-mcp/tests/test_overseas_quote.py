from __future__ import annotations

import urllib.error

import pytest

from cn_extra_mcp import global_market as gm
from cn_extra_mcp import sources
from cn_extra_mcp.symbols import InvalidSymbol, is_overseas_symbol, normalize_overseas_symbol
from test_global_snapshot import NOW, REAL_TENCENT, TENCENT  # noqa: F401


@pytest.fixture
def calls(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []
    gm.clear_cache()
    monkeypatch.setattr(gm, "_now", lambda: NOW)
    monkeypatch.setattr(gm, "_sleep", lambda seconds: None)

    def fake(symbols, timeout=8.0):
        seen.append(list(symbols))
        return REAL_TENCENT + "\n" + TENCENT

    monkeypatch.setattr(sources, "fetch_tencent_text", fake)
    return seen


@pytest.mark.parametrize("symbol", ["usNVDA", "usBRK.B", "usA", "hk00700", "usGOOGL", "hk09988"])
def test_valid_symbols(symbol: str) -> None:
    assert is_overseas_symbol(symbol)
    assert normalize_overseas_symbol(symbol) == symbol


@pytest.mark.parametrize(
    "symbol",
    ["usnvda", "NVDA", "us", "usTOOLONGX", "us123", "hk0700", "hk007000", "hkHSI", "sh600000", "usBRK.BB",
     "usNVDA ", " usNVDA", "usNVDA,usAMD", "", None, 5, "us.B", "../etc"],
)
def test_invalid_symbols(symbol) -> None:
    assert not is_overseas_symbol(symbol)
    with pytest.raises(InvalidSymbol):
        normalize_overseas_symbol(symbol)


def test_quote_returns_fields_without_fundamentals(calls) -> None:
    payload = gm.cn_get_overseas_quote(["usNVDA", "hk00700"])
    assert payload["ok"] and payload["status"] == "ready"
    assert calls == [["usNVDA", "hk00700"]]
    nvda, tencent = payload["data"]
    assert nvda == {
        "key": "usNVDA",
        "name": "英伟达",
        "price": 162.85,
        "prev_close": 166.19,
        "change_pct": -2.01,
        "quote_time": "2026-11-13T16:00:01-05:00",
        "quote_tz": "America/New_York",
        "source": "qt.gtimg.cn",
        "stale": False,
    }
    assert tencent["quote_tz"] == "Asia/Hong_Kong"
    assert tencent["quote_time"] == "2026-11-16T10:38:43+08:00"
    assert tencent["price"] == 392.6 and tencent["change_pct"] == 1.55


def test_class_share_symbol(calls) -> None:
    brk = gm.cn_get_overseas_quote(["usBRK.B"])["data"][0]
    assert brk["price"] == 592.94


def test_duplicates_are_collapsed(calls) -> None:
    payload = gm.cn_get_overseas_quote(["usNVDA", "usNVDA", "usAMD"])
    assert [i["key"] for i in payload["data"]] == ["usNVDA", "usAMD"]
    assert calls == [["usNVDA", "usAMD"]]


@pytest.mark.parametrize(
    "bad",
    [[], "usNVDA", None, ["usnvda"], ["usNVDA", "bad"], [f"us{c}" for c in "ABCDEFGHIJK"], [1], {"a": 1}],
)
def test_invalid_arguments_rejected_locally(calls, bad) -> None:
    payload = gm.cn_get_overseas_quote(bad)
    assert payload["ok"] is False and payload["error"]["code"] == "invalid_argument"
    assert calls == []


def test_ten_symbols_allowed(calls) -> None:
    ten = ["usNVDA", "usTSLA", "usAAPL", "usMU", "usTSM", "usAVGO", "usAMD", "usSMCI", "usANET", "usFSLR"]
    payload = gm.cn_get_overseas_quote(ten)
    assert payload["ok"] and len(payload["data"]) == 10


def test_unknown_symbol_item_has_reason(calls) -> None:
    payload = gm.cn_get_overseas_quote(["usZZZZ"])
    assert payload["ok"] is True
    assert payload["data"][0]["price"] is None and payload["data"][0]["reason"] == "not_found_upstream"


def test_upstream_failure_is_error_envelope(monkeypatch) -> None:
    gm.clear_cache()

    def boom(symbols, timeout=8.0):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(sources, "fetch_tencent_text", boom)
    payload = gm.cn_get_overseas_quote(["usNVDA"])
    assert payload["ok"] is False and payload["error"]["code"] == "upstream_error"


def test_quote_cache_hit(calls) -> None:
    gm.cn_get_overseas_quote(["usNVDA"])
    gm.cn_get_overseas_quote(["usNVDA"])
    assert len(calls) == 1


def test_stale_flag_on_old_quote(calls, monkeypatch) -> None:
    monkeypatch.setattr(gm, "_now", lambda: NOW.replace(day=25))
    assert gm.cn_get_overseas_quote(["usNVDA"])["data"][0]["stale"] is True
