from __future__ import annotations

import pytest

from cn_market_gateway import config
from cn_market_gateway.codes import (
    InvalidCode,
    is_overseas_symbol,
    normalize_code,
    normalize_overseas_symbol,
)


@pytest.mark.parametrize(
    "value,canonical",
    [
        ("600519", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("600519.SS", "600519.SH"),
        ("002553", "002553.SZ"),
        ("sz002553", "002553.SZ"),
        ("920418", "920418.BJ"),
        ("920418.BJ", "920418.BJ"),
        ("000300", "000300.SH"),
        ("000300.SH", "000300.SH"),
        ("399006", "399006.SZ"),
        ("000001", "000001.SZ"),
        ("000001.SH", "000001.SH"),
    ],
)
def test_normalize_code(value, canonical):
    assert normalize_code(value).canonical == canonical


@pytest.mark.parametrize(
    "value",
    ["", "60051", "1234567", "600519.SZ", "SH002553", "123456.BJ", "abc", None, 600519],
)
def test_invalid_codes(value):
    with pytest.raises(InvalidCode):
        normalize_code(value)


def test_index_flag_and_bj_code():
    assert normalize_code("000300.SH").is_index is True
    assert normalize_code("600519").is_index is False
    assert normalize_code("920418").exchange == "BJ"


def test_overseas_symbols():
    assert is_overseas_symbol("usNVDA")
    assert is_overseas_symbol("usBRK.B")
    assert is_overseas_symbol("hk00700")
    assert not is_overseas_symbol("NVDA")
    assert normalize_overseas_symbol("usNVDA") == "usNVDA"
    with pytest.raises(InvalidCode):
        normalize_overseas_symbol("sz000001")


def test_push2_is_forbidden_for_every_host_shape():
    assert config.is_forbidden_host("push2his.eastmoney.com")
    assert config.is_forbidden_host("push2.eastmoney.com")
    assert config.is_forbidden_host("PUSH2.EASTMONEY.COM")
    assert not config.is_forbidden_host("datacenter.eastmoney.com")


def test_bse50_index_is_recognised():
    from cn_market_gateway.codes import normalize_code

    for raw in ("899050", "899050.BJ", "bj899050"):
        code = normalize_code(raw)
        assert code.canonical == "899050.BJ" and code.is_index
