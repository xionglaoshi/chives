"""Unit tests for the deterministic rule helpers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from paper_broker_mcp.rules import (
    RuleError,
    check_buy_lot,
    check_sell_lot,
    fees_for,
    is_trading_session,
    money,
    normalize_code,
    parse_as_of,
    validate_quantity,
)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600000.SH", "600000.SH"),
        ("600000", "600000.SH"),
        ("sh600000", "600000.SH"),
        ("600000.SS", "600000.SH"),
        ("000001.SZ", "000001.SZ"),
        ("sz000001", "000001.SZ"),
        ("300750", "300750.SZ"),
        ("688001.SH", "688001.SH"),
        ("830799.BJ", "830799.BJ"),
        ("830799", "830799.BJ"),
    ],
)
def test_normalize_code(raw: str, expected: str) -> None:
    assert normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "ABC", "60000", "600000.HK", "123456", "SH000001.SZ", "000001.SH", "600000.BJ"])
def test_normalize_code_rejects(raw: str) -> None:
    with pytest.raises(RuleError) as info:
        normalize_code(raw)
    assert info.value.code == "invalid_code"


def test_money_rounds_half_up() -> None:
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(Decimal("2.675")) == Decimal("2.68")


def test_fees_buy_minimum_commission() -> None:
    fees = fees_for("buy", Decimal("10000.00"))
    assert fees == {"commission": Decimal("5.00"), "transfer_fee": Decimal("0.10"), "stamp_duty": Decimal("0.00")}


def test_fees_sell_includes_stamp_duty() -> None:
    fees = fees_for("sell", Decimal("11000.00"))
    assert fees == {"commission": Decimal("5.00"), "transfer_fee": Decimal("0.11"), "stamp_duty": Decimal("5.50")}


def test_fees_above_minimum_commission() -> None:
    fees = fees_for("buy", Decimal("1000000.00"))
    assert fees["commission"] == Decimal("250.00")
    assert fees["transfer_fee"] == Decimal("10.00")
    assert fees["stamp_duty"] == Decimal("0.00")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-11-03T09:30:00+08:00", True),
        ("2026-11-03T11:30:00+08:00", True),
        ("2026-11-03T13:00:00+08:00", True),
        ("2026-11-03T15:00:00+08:00", True),
        ("2026-11-03T09:29:59+08:00", False),
        ("2026-11-03T11:30:01+08:00", False),
        ("2026-11-03T12:59:59+08:00", False),
        ("2026-11-03T15:00:01+08:00", False),
        ("2026-11-07T10:00:00+08:00", False),
    ],
)
def test_trading_session(text: str, expected: bool) -> None:
    assert is_trading_session(at(text)) is expected


def test_parse_as_of_assumes_beijing_for_naive_input() -> None:
    parsed = parse_as_of("2026-11-03T10:00:00", at("2026-11-02T00:00:00+08:00"))
    assert parsed.isoformat() == "2026-11-03T10:00:00+08:00"


def test_parse_as_of_rejects_garbage() -> None:
    with pytest.raises(RuleError) as info:
        parse_as_of("tomorrow", at("2026-11-02T00:00:00+08:00"))
    assert info.value.code == "invalid_as_of"


@pytest.mark.parametrize("raw", [0, -1, 1.5, "abc", True, None])
def test_validate_quantity_rejects(raw: object) -> None:
    with pytest.raises(RuleError) as info:
        validate_quantity(raw)
    assert info.value.code == "invalid_quantity"


def test_validate_quantity_accepts_integral_values() -> None:
    assert validate_quantity(100) == 100
    assert validate_quantity(100.0) == 100
    assert validate_quantity("200") == 200


def test_board_lots() -> None:
    check_buy_lot("600000.SH", 100)
    with pytest.raises(RuleError):
        check_buy_lot("600000.SH", 150)
    with pytest.raises(RuleError):
        check_buy_lot("688001.SH", 100)
    check_buy_lot("688001.SH", 200)
    check_buy_lot("688001.SH", 250)
    check_sell_lot(500, 1000)
    check_sell_lot(1000, 1000)
    with pytest.raises(RuleError):
        check_sell_lot(150, 1000)
    check_sell_lot(150, 150)
