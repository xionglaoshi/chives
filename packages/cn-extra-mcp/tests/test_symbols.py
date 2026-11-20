from __future__ import annotations

import pytest

from cn_extra_mcp.symbols import InvalidSymbol, normalize_symbol


@pytest.mark.parametrize(
    "raw,canonical,sina",
    [
        ("002553", "002553.SZ", "sz002553"),
        ("002553.SZ", "002553.SZ", "sz002553"),
        ("002553.sz", "002553.SZ", "sz002553"),
        ("SZ002553", "002553.SZ", "sz002553"),
        ("sz002553", "002553.SZ", "sz002553"),
        ("600000", "600000.SH", "sh600000"),
        ("600000.SH", "600000.SH", "sh600000"),
        ("600000.SS", "600000.SH", "sh600000"),
        ("688981", "688981.SH", "sh688981"),
        ("300750", "300750.SZ", "sz300750"),
        (" 002553.SZ ", "002553.SZ", "sz002553"),
        ("920418", "920418.BJ", "bj920418"),
        ("920418.BJ", "920418.BJ", "bj920418"),
        ("920418.bj", "920418.BJ", "bj920418"),
        (" 920418.BJ ", "920418.BJ", "bj920418"),
        ("430418", "430418.BJ", "bj430418"),
        ("430418.BJ", "430418.BJ", "bj430418"),
        ("830799", "830799.BJ", "bj830799"),
        ("871981", "871981.BJ", "bj871981"),
        ("889999", "889999.BJ", "bj889999"),
    ],
)
def test_normalize(raw: str, canonical: str, sina: str) -> None:
    symbol = normalize_symbol(raw)
    assert symbol.canonical == canonical
    assert symbol.sina == sina


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abc",
        "00255",
        "0025530",
        "002553.HK",
        "SH002553",
        "SZ600000",
        "400001",
        "510300",
        "920418.SH",
        "920418.SZ",
        "920418.SS",
        "600519.BJ",
        "000001.BJ",
        "123456.BJ",
        "92041.BJ",
        "92041A.BJ",
        "BJ920418",
        "430418.SH",
        "830799.SS",
    ],
)
def test_invalid(raw: str) -> None:
    with pytest.raises(InvalidSymbol):
        normalize_symbol(raw)


def test_non_string() -> None:
    with pytest.raises(InvalidSymbol):
        normalize_symbol(2553)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw,legacy",
    [
        ("920418.BJ", False),
        ("920418", False),
        ("430418.BJ", True),
        ("430418", True),
        ("830799", True),
        ("871981", True),
        ("889999", True),
        ("600519.SH", False),
        ("002553", False),
    ],
)
def test_legacy_bj_flag(raw: str, legacy: bool) -> None:
    assert normalize_symbol(raw).legacy_bj is legacy
