from __future__ import annotations

import pandas as pd
import pytest

from cn_research_mcp import sources
from cn_research_mcp.infra import audit_sources_text
from cn_research_mcp.sources import ENDPOINTS, Sources, akshare_symbol
from cn_research_mcp.symbols import normalize_symbol


def _recorder(monkeypatch, *, missing: set[str] | None = None):
    calls: list[tuple[str, tuple, dict]] = []
    missing = missing or set()

    def rec(name, *args, **kwargs):
        calls.append((name, args, kwargs))
        if name in missing:
            raise AttributeError(name)
        return pd.DataFrame()

    monkeypatch.setattr(sources, "_ak", rec)
    return calls


@pytest.mark.parametrize(
    "name",
    [
        "bond_cb_list_em",
        "bond_cb_realtime_sina",
        "index_zh_daily_em",
        "index_stock_cons_csindex",
        "stock_gdfx_free_top_10_em",
        "stock_fund_stock_holder",
        "stock_zygc_em",
        "bond_zh_cov",
        "bond_zh_hs_cov_spot",
        "stock_zh_index_daily_em",
    ],
)
def test_audit_allows_instrument_names(name):
    assert audit_sources_text(f'def f():\n    return _ak("{name}")\n') == []


def test_cb_list_uses_current_name(monkeypatch):
    calls = _recorder(monkeypatch)
    Sources().cb_list()
    assert [name for name, _, _ in calls] == ["bond_cb_list_em"]


def test_cb_list_falls_back_to_legacy_name(monkeypatch):
    calls = _recorder(monkeypatch, missing={"bond_cb_list_em"})
    Sources().cb_list()
    assert [name for name, _, _ in calls] == ["bond_cb_list_em", "bond_zh_cov"]


def test_cb_spot_uses_current_name_and_falls_back(monkeypatch):
    calls = _recorder(monkeypatch)
    Sources().cb_spot()
    assert calls[0][0] == "bond_cb_realtime_sina"
    calls = _recorder(monkeypatch, missing={"bond_cb_realtime_sina"})
    Sources().cb_spot()
    assert [name for name, _, _ in calls] == ["bond_cb_realtime_sina", "bond_zh_hs_cov_spot"]


def test_index_bars_uses_current_name_and_passes_dates(monkeypatch):
    calls = _recorder(monkeypatch)
    Sources().index_bars("sh000300", "20260101", "20261116")
    name, _, kwargs = calls[0]
    assert name == "index_zh_daily_em"
    assert kwargs == {"symbol": "sh000300", "start_date": "20260101", "end_date": "20261116"}


def test_index_bars_falls_back_to_legacy_name(monkeypatch):
    calls = _recorder(monkeypatch, missing={"index_zh_daily_em"})
    Sources().index_bars("sh000300", "20260101", "20261116")
    assert [name for name, _, _ in calls] == ["index_zh_daily_em", "stock_zh_index_daily_em"]


def test_index_constituents_passes_digits(monkeypatch):
    calls = _recorder(monkeypatch)
    Sources().index_constituents("000300")
    assert calls[0] == ("index_stock_cons_csindex", (), {"symbol": "000300"})


def test_holders_top10_uses_lower_prefix_and_date(monkeypatch):
    calls = _recorder(monkeypatch)
    Sources().holders_top10(normalize_symbol("600519"), "20260930")
    assert calls[0] == ("stock_gdfx_free_top_10_em", (), {"symbol": "sh600519", "date": "20260930"})


def test_fund_holders_uses_digits(monkeypatch):
    calls = _recorder(monkeypatch)
    Sources().fund_holders(normalize_symbol("000001"))
    assert calls[0] == ("stock_fund_stock_holder", (), {"symbol": "000001"})


def test_business_segments_uses_upper_prefix(monkeypatch):
    calls = _recorder(monkeypatch)
    Sources().business_segments(normalize_symbol("600519"))
    assert calls[0] == ("stock_zygc_em", (), {"symbol": "SH600519"})


def test_instrument_endpoint_metadata():
    assert ENDPOINTS["cb_list"].source == "eastmoney"
    assert ENDPOINTS["cb_spot"].source == "sina"
    assert ENDPOINTS["index_bars"].source == "eastmoney"
    assert ENDPOINTS["index_constituents"].source == "csindex"
    assert ENDPOINTS["holders_top10"].symbol_style == "lower_prefix"
    assert ENDPOINTS["fund_holders"].symbol_style == "digits"
    assert ENDPOINTS["business_segments"].symbol_style == "upper_prefix"
    assert all("push2" not in endpoint.host for endpoint in ENDPOINTS.values())


def test_akshare_symbol_style_errors():
    with pytest.raises(ValueError):
        akshare_symbol(normalize_symbol("600519"), "nope")
