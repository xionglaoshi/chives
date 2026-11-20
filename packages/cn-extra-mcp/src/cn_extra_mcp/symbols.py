"""Stock-code normalization for Sina / Tencent A-share endpoints."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CODE_RE = re.compile(r"^(?:(?P<prefix>SH|SZ))?(?P<digits>\d{6})(?:\.(?P<suffix>SH|SZ|SS|BJ))?$")

BJ_PREFIXES = ("92", "43", "83", "87", "88")
LEGACY_BJ_PREFIXES = ("43", "83", "87", "88")


class InvalidSymbol(ValueError):
    """Raised when a code is not a supported Shanghai/Shenzhen/Beijing A-share code."""


@dataclass(frozen=True)
class Symbol:
    canonical: str
    sina: str
    exchange: str
    digits: str

    @property
    def legacy_bj(self) -> bool:
        """True for pre-migration Beijing codes (43/83/87/88) that may be stale."""
        return self.exchange == "BJ" and self.digits.startswith(LEGACY_BJ_PREFIXES)


def _infer_exchange(digits: str) -> str | None:
    if digits.startswith("6"):
        return "SH"
    if digits.startswith(("0", "3")):
        return "SZ"
    if digits.startswith(BJ_PREFIXES):
        return "BJ"
    return None


def normalize_symbol(code: str) -> Symbol:
    if not isinstance(code, str):
        raise InvalidSymbol("code must be a string")
    text = code.strip().upper()
    match = _CODE_RE.match(text)
    if match is None:
        raise InvalidSymbol(f"unrecognized A-share code: {code!r}")

    digits = match.group("digits")
    inferred = _infer_exchange(digits)
    if inferred is None:
        raise InvalidSymbol(f"code is not a Shanghai/Shenzhen/Beijing A-share code: {code!r}")

    explicit = match.group("prefix") or match.group("suffix")
    if explicit == "SS":
        explicit = "SH"
    if explicit is not None and explicit != inferred:
        raise InvalidSymbol(f"exchange does not match code: {code!r}")

    exchange = explicit or inferred
    # Sina and Tencent both address Beijing codes as "bj" + 6 digits.
    return Symbol(
        canonical=f"{digits}.{exchange}",
        sina=f"{exchange.lower()}{digits}",
        exchange=exchange,
        digits=digits,
    )


_OVERSEAS_RE = re.compile(r"^us[A-Z]{1,6}(\.[A-Z])?$|^hk\d{5}$")


def is_overseas_symbol(value: object) -> bool:
    """True for Tencent-style US/HK codes such as usNVDA, usBRK.B or hk00700 (exact case)."""
    return isinstance(value, str) and _OVERSEAS_RE.fullmatch(value) is not None


def normalize_overseas_symbol(value: object) -> str:
    if not is_overseas_symbol(value):
        raise InvalidSymbol(f"unrecognized overseas symbol (expected usXXXX or hkNNNNN): {value!r}")
    return str(value)
