"""Small shared validators for the hub v1.1 write endpoints.

Every free-text field goes through the portfolio-mcp cleaner so instruction-like
or credential-like text is rejected before it is stored (same rules as plans).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from .portfolio_view import ensure_portfolio_path


class ApiError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 200) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def only(payload: Mapping[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(payload) - allowed)
    if extra:
        raise ApiError("unexpected_field", "不支持的字段: " + ", ".join(extra))


def clean_text(
    value: Any,
    field: str,
    max_chars: int,
    *,
    allow_empty: bool = False,
) -> str:
    ensure_portfolio_path()
    from portfolio_mcp.errors import PortfolioError
    from portfolio_mcp.sanitize import clean_free_text

    try:
        return clean_free_text(value, field=field, max_chars=max_chars, allow_empty=allow_empty)
    except PortfolioError as exc:
        raise ApiError(exc.code if exc.code else "invalid_value", str(exc)) from exc


def clean_body(value: Any, *, max_chars: int) -> str:
    """Keep markdown structure, drop control bytes; never trusted as instructions."""
    if not isinstance(value, str):
        raise ApiError("invalid_value", "body_markdown 必须是字符串")
    if len(value) > max_chars:
        raise ApiError("too_large", f"body_markdown 不得超过 {max_chars} 字符")
    kept = "".join(
        char
        for char in value
        if char in {"\n", "\t"} or (ord(char) >= 32 and char not in {"\x7f"})
    )
    return kept.replace("\r\n", "\n").replace("\r", "\n")


def number(
    value: Any,
    field: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    integer: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("invalid_value", f"{field} 必须是数字")
    result = float(value)
    if not math.isfinite(result):
        raise ApiError("invalid_value", f"{field} 必须是有限数字")
    if integer and not result.is_integer():
        raise ApiError("invalid_value", f"{field} 必须是整数")
    if minimum is not None and result < minimum:
        raise ApiError("bad_value", f"{field} 不得小于 {minimum:g}")
    if maximum is not None and result > maximum:
        raise ApiError("bad_value", f"{field} 不得大于 {maximum:g}")
    return result


def as_int(value: Any, field: str, *, minimum: int = 0, maximum: int = 2**31 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("invalid_value", f"{field} 必须是整数")
    if value < minimum or value > maximum:
        raise ApiError("bad_value", f"{field} 必须在 {minimum}..{maximum}")
    return value


def as_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError("invalid_value", f"{field} 必须是布尔值")
    return value
