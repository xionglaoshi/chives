from __future__ import annotations

import pytest

from cn_research_mcp.sources import ENDPOINTS, akshare_symbol
from cn_research_mcp.symbols import InvalidSymbol, UnsupportedMarket, normalize_symbol


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("SH600519", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("600519.ss", "600519.SH"),
        ("000001", "000001.SZ"),
        ("300750.SZ", "300750.SZ"),
        ("SZ002553", "002553.SZ"),
        ("688981", "688981.SH"),
        (" 601318 ", "601318.SH"),
    ],
)
def test_canonical_forms(raw, canonical):
    assert normalize_symbol(raw).canonical == canonical


@pytest.mark.parametrize("raw", ["920418", "430047.BJ", "830799", "BJ920418", "880001"])
def test_beijing_rejected_as_unsupported(raw):
    with pytest.raises(UnsupportedMarket):
        normalize_symbol(raw)


@pytest.mark.parametrize("raw", ["", "abc", "12345", "1234567", "600519.SZ", "000001.SH", "500001", None, 600519])
def test_invalid_codes(raw):
    with pytest.raises(InvalidSymbol):
        normalize_symbol(raw)


def test_akshare_symbol_styles():
    sym = normalize_symbol("600519")
    assert akshare_symbol(sym, "digits") == "600519"
    assert akshare_symbol(sym, "lower_prefix") == "sh600519"
    assert akshare_symbol(sym, "upper_prefix") == "SH600519"
    sz = normalize_symbol("000001")
    assert akshare_symbol(sz, "lower_prefix") == "sz000001"
    assert akshare_symbol(sz, "upper_prefix") == "SZ000001"


def test_akshare_symbol_unknown_style():
    with pytest.raises(ValueError):
        akshare_symbol(normalize_symbol("600519"), "weird")


def test_every_symbol_endpoint_has_a_known_style():
    for name, endpoint in ENDPOINTS.items():
        if endpoint.symbol_style is not None:
            akshare_symbol(normalize_symbol("600519"), endpoint.symbol_style)
