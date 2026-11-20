"""Deterministic A-share trading rules: codes, sessions, lots, fees and money."""

from __future__ import annotations

import re
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from paper_broker_mcp.envelope import to_cn

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
COMMISSION_RATE = Decimal("0.00025")
COMMISSION_MIN = Decimal("5.00")
TRANSFER_RATE = Decimal("0.00001")
STAMP_RATE = Decimal("0.0005")

MORNING_OPEN = time(9, 30)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)

_CODE_RE = re.compile(r"^(?:(sh|sz|bj))?(\d{6})(?:\.(SH|SZ|SS|BJ))?$", re.IGNORECASE)


class RuleError(ValueError):
    """A business-rule rejection carrying one of the documented error codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def decimal_of(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def normalize_code(raw: object) -> str:
    text = str(raw or "").strip()
    match = _CODE_RE.fullmatch(text)
    if not match:
        raise RuleError("invalid_code", f"unrecognized A-share code: {text!r}")
    prefix, digits, suffix = match.group(1), match.group(2), match.group(3)
    suffix = suffix.upper() if suffix else None
    prefix = prefix.upper() if prefix else None
    if prefix is not None and suffix is not None:
        opposite = "SH" if suffix == "SS" else suffix
        if prefix != opposite:
            raise RuleError("invalid_code", f"code/exchange mismatch: {text!r}")
    explicit = prefix or ("SH" if suffix == "SS" else suffix)
    if digits.startswith(("6", "9")):
        inferred = "SH"
    elif digits.startswith(("0", "2", "3")):
        inferred = "SZ"
    elif digits.startswith(("4", "8")):
        inferred = "BJ"
    else:
        raise RuleError("invalid_code", f"cannot infer exchange for code: {digits}")
    if explicit is not None and explicit != inferred:
        raise RuleError("invalid_code", f"code/exchange mismatch: {text!r}")
    return f"{digits}.{inferred}"


def is_star_board(code: str) -> bool:
    return code.startswith("688")


def tencent_symbol(code: str) -> str:
    digits, _, exchange = code.partition(".")
    return f"{exchange.lower()}{digits}"


def parse_as_of(raw: object, fallback: datetime) -> datetime:
    if raw is None or str(raw).strip() == "":
        return fallback
    text = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuleError("invalid_as_of", f"as_of is not ISO-8601: {text!r}") from exc
    return to_cn(parsed)


def trade_date_of(value: datetime) -> str:
    return value.date().isoformat()


def is_trading_session(value: datetime) -> bool:
    local = to_cn(value)
    if local.weekday() >= 5:
        return False
    clock = local.time()
    return (MORNING_OPEN <= clock <= MORNING_CLOSE) or (AFTERNOON_OPEN <= clock <= AFTERNOON_CLOSE)


def validate_side(raw: object) -> str:
    side = str(raw or "").strip().lower()
    if side not in {"buy", "sell"}:
        raise RuleError("invalid_side", "side must be 'buy' or 'sell'")
    return side


def validate_quantity(raw: object) -> int:
    if isinstance(raw, bool):
        raise RuleError("invalid_quantity", "quantity must be a positive integer")
    if isinstance(raw, int):
        quantity = raw
    elif isinstance(raw, float) and raw.is_integer():
        quantity = int(raw)
    elif isinstance(raw, str) and raw.strip().isdigit():
        quantity = int(raw.strip())
    else:
        raise RuleError("invalid_quantity", "quantity must be a positive integer")
    if quantity <= 0:
        raise RuleError("invalid_quantity", "quantity must be a positive integer")
    return quantity


def check_buy_lot(code: str, quantity: int) -> None:
    if is_star_board(code):
        if quantity < 200:
            raise RuleError("lot_size", "STAR-board buys need at least 200 shares")
        return
    if quantity % 100 != 0:
        raise RuleError("lot_size", "buy quantity must be a multiple of 100 shares")


def check_sell_lot(quantity: int, sellable: int) -> None:
    if quantity % 100 == 0:
        return
    if quantity != sellable:
        raise RuleError("lot_size", "odd-lot sells must clear the entire sellable position")


def fees_for(side: str, gross: Decimal) -> dict[str, Decimal]:
    commission = max(COMMISSION_MIN, money(gross * COMMISSION_RATE))
    transfer_fee = money(gross * TRANSFER_RATE)
    stamp_duty = money(gross * STAMP_RATE) if side == "sell" else ZERO
    return {
        "commission": money(commission),
        "transfer_fee": transfer_fee,
        "stamp_duty": stamp_duty,
    }


def total_fees(fees: dict[str, Decimal]) -> Decimal:
    return money(sum(fees.values(), ZERO))
