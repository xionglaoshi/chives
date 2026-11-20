"""Whitelisted position fields, value validation and account-level fields."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.sanitize import clean_free_text
from portfolio_mcp.symbols import normalize_symbol

PORTFOLIO_VERSION = 1
MAX_POSITIONS = 100

POSITION_ORDER: tuple[str, ...] = (
    "code",
    "name",
    "qty",
    "available_qty",
    "cost_price",
    "opened_date",
    "industry",
    "note",
)

REQUIRED_FIELDS: tuple[str, ...] = ("code", "name", "qty", "cost_price")
TEXT_LIMITS: dict[str, int] = {"name": 20, "industry": 20, "note": 60}


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _as_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise PortfolioError("invalid_value", f"{field} must be an integer", field=field)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise PortfolioError("invalid_value", f"{field} must be an integer", field=field)


def validate_qty(value: Any) -> int:
    qty = _as_int(value, field="qty")
    if qty <= 0:
        raise PortfolioError("invalid_value", "qty must be a positive integer (shares)", field="qty")
    return qty


def validate_available_qty(value: Any, *, qty: int | None = None) -> int:
    available = _as_int(value, field="available_qty")
    if available < 0:
        raise PortfolioError(
            "invalid_value", "available_qty must be zero or a positive integer (shares)", field="available_qty"
        )
    if qty is not None and available > qty:
        raise PortfolioError(
            "invalid_value", "available_qty must not exceed qty", field="available_qty"
        )
    return available


def validate_cost_price(value: Any) -> float:
    if not _is_number(value):
        raise PortfolioError(
            "invalid_value", "cost_price must be a positive number (CNY per share)", field="cost_price"
        )
    cost = float(value)
    if cost <= 0:
        raise PortfolioError(
            "invalid_value", "cost_price must be a positive number (CNY per share)", field="cost_price"
        )
    return cost


def validate_opened_date(value: Any, *, today: date | None = None) -> str:
    if not isinstance(value, str):
        raise PortfolioError(
            "invalid_value", "opened_date must be a YYYY-MM-DD string", field="opened_date"
        )
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise PortfolioError(
            "invalid_value", "opened_date must be a valid YYYY-MM-DD date", field="opened_date"
        ) from exc
    if parsed > (today or date.today()):
        raise PortfolioError(
            "invalid_value", "opened_date must not be later than today", field="opened_date"
        )
    return parsed.isoformat()


def validate_cash(value: Any) -> float:
    if not _is_number(value):
        raise PortfolioError(
            "invalid_value", "cash must be a number >= 0 (CNY)", field="cash"
        )
    cash = float(value)
    if cash < 0:
        raise PortfolioError("invalid_value", "cash must be >= 0 (CNY)", field="cash")
    return cash


def validate_position(raw: Any, *, today: date | None = None) -> dict[str, Any]:
    """Validate one full position row and return the canonical field order."""
    if not isinstance(raw, dict):
        raise PortfolioError("invalid_argument", "each row must be a JSON object")
    unknown = sorted(key for key in raw if key not in POSITION_ORDER)
    if unknown:
        raise PortfolioError(
            "unknown_field",
            "unknown field(s): " + ", ".join(unknown) + "; allowed: " + ", ".join(POSITION_ORDER),
        )
    missing = [name for name in REQUIRED_FIELDS if raw.get(name) in (None, "")]
    if missing:
        raise PortfolioError(
            "missing_field",
            "missing required field(s): " + ", ".join(missing),
            field=missing[0],
        )

    symbol = normalize_symbol(raw["code"])
    name = clean_free_text(raw["name"], field="name", max_chars=64 if str(raw.get("code","")).endswith(".OF") else TEXT_LIMITS["name"])
    qty = validate_qty(raw["qty"])
    cost_price = validate_cost_price(raw["cost_price"])

    row: dict[str, Any] = {
        "code": symbol.canonical,
        "name": name,
        "qty": qty,
        "available_qty": None,
        "cost_price": cost_price,
        "opened_date": None,
        "industry": None,
        "note": None,
    }

    if raw.get("available_qty") is not None:
        row["available_qty"] = validate_available_qty(raw["available_qty"], qty=qty)
    if raw.get("opened_date") is not None:
        row["opened_date"] = validate_opened_date(raw["opened_date"], today=today)
    if raw.get("industry") not in (None, ""):
        row["industry"] = clean_free_text(
            raw["industry"], field="industry", max_chars=TEXT_LIMITS["industry"]
        )
    if raw.get("note") not in (None, ""):
        row["note"] = clean_free_text(raw["note"], field="note", max_chars=TEXT_LIMITS["note"])
    return row


def validate_update_fields(raw: Any, *, today: date | None = None) -> dict[str, Any]:
    """Validate a partial position update (code cannot be changed here)."""
    if not isinstance(raw, dict):
        raise PortfolioError("invalid_argument", "fields must be a JSON object")
    if not raw:
        raise PortfolioError("invalid_argument", "fields must contain at least one field")
    unknown = sorted(key for key in raw if key not in POSITION_ORDER)
    if unknown:
        raise PortfolioError(
            "unknown_field",
            "unknown field(s): " + ", ".join(unknown) + "; allowed: " + ", ".join(POSITION_ORDER),
        )
    if "code" in raw:
        raise PortfolioError(
            "invalid_value",
            "code cannot be changed; use portfolio_remove_position then import a new row",
            field="code",
        )

    partial: dict[str, Any] = {}
    if "name" in raw:
        partial["name"] = clean_free_text(
            raw["name"], field="name", max_chars=TEXT_LIMITS["name"]
        )
    if "qty" in raw:
        partial["qty"] = validate_qty(raw["qty"])
    if "cost_price" in raw:
        partial["cost_price"] = validate_cost_price(raw["cost_price"])
    if "available_qty" in raw:
        partial["available_qty"] = (
            None if raw["available_qty"] is None else validate_available_qty(raw["available_qty"])
        )
    if "opened_date" in raw:
        partial["opened_date"] = (
            None
            if raw["opened_date"] is None
            else validate_opened_date(raw["opened_date"], today=today)
        )
    for field in ("industry", "note"):
        if field in raw:
            value = raw[field]
            partial[field] = (
                None
                if value in (None, "")
                else clean_free_text(value, field=field, max_chars=TEXT_LIMITS[field])
            )
    return partial


def merge_position(before: dict[str, Any], partial: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Apply a partial update and re-validate the merged row (available_qty <= qty etc.)."""
    merged = dict(before)
    merged.update(partial)
    return validate_position(merged, today=today)


def unique_codes(rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for row in rows:
        code = row["code"]
        if code in seen:
            raise PortfolioError("duplicate_code", f"duplicate position code: {code}", field="code")
        seen.add(code)


def validate_positions(rows: Any, *, today: date | None = None) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise PortfolioError("invalid_argument", "rows must be a list of position objects")
    if len(rows) > MAX_POSITIONS:
        raise PortfolioError(
            "too_many_positions", f"at most {MAX_POSITIONS} positions are supported"
        )
    validated = [validate_position(row, today=today) for row in rows]
    unique_codes(validated)
    return validated
