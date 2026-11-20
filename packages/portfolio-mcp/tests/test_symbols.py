from __future__ import annotations

import pytest

from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.symbols import normalize_symbol


@pytest.mark.parametrize(
    ("raw", "canonical", "tencent"),
    [
        ("600000", "600000.SH", "sh600000"),
        ("600000.SH", "600000.SH", "sh600000"),
        ("SH600000", "600000.SH", "sh600000"),
        ("sh600000", "600000.SH", "sh600000"),
        ("600000.SS", "600000.SH", "sh600000"),
        ("000001", "000001.SZ", "sz000001"),
        ("000001.SZ", "000001.SZ", "sz000001"),
        ("300750", "300750.SZ", "sz300750"),
        ("002553.SZ", "002553.SZ", "sz002553"),
        ("920418", "920418.BJ", "bj920418"),
        ("920418.BJ", "920418.BJ", "bj920418"),
        ("430418", "430418.BJ", "bj430418"),
        ("830799.BJ", "830799.BJ", "bj830799"),
        # Exchange-traded funds are A-share instruments and are allowed in the book.
        ("510300", "510300.SH", "sh510300"),
        ("510300.SH", "510300.SH", "sh510300"),
        ("588000", "588000.SH", "sh588000"),
        ("159919", "159919.SZ", "sz159919"),
        ("159919.SZ", "159919.SZ", "sz159919"),
        ("160123", "160123.SZ", "sz160123"),
        # Excel strips leading zeros: left-pad rather than guess an exchange.
        ("1", "000001.SZ", "sz000001"),
        ("1.0", "000001.SZ", "sz000001"),
        (" 600000 ", "600000.SH", "sh600000"),
    ],
)
def test_normalize(raw: str, canonical: str, tencent: str) -> None:
    symbol = normalize_symbol(raw)
    assert symbol.canonical == canonical
    assert symbol.tencent == tencent


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "AAPL",
        "00700.HK",
        "600000.HK",
        "600000.SZ",
        "000001.SH",
        "900901",
        "200002",
        "400001",
        "123456789",
        "60000A",
        None,
        600000,
    ],
)
def test_reject_non_a_share(raw: object) -> None:
    with pytest.raises(PortfolioError) as excinfo:
        normalize_symbol(raw)
    assert excinfo.value.code == "invalid_code"
