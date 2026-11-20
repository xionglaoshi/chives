"""Stock-code normalization. Output form is NNNNNN.SH / NNNNNN.SZ; Beijing codes are refused."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CODE_RE = re.compile(r"^(?:(?P<prefix>SH|SZ|BJ))?(?P<digits>\d{6})(?:\.(?P<suffix>SH|SZ|SS|BJ))?$")

BJ_PREFIXES = ("92", "43", "83", "87", "88")


class InvalidSymbol(ValueError):
    """The code is malformed or not a known A-share code."""


class UnsupportedMarket(ValueError):
    """The code is a valid A-share code from a market this server does not cover (Beijing)."""


@dataclass(frozen=True)
class Symbol:
    canonical: str
    exchange: str
    digits: str


def _infer_exchange(digits: str) -> str | None:
    if digits.startswith("6"):
        return "SH"
    if digits.startswith(("0", "3")):
        return "SZ"
    if digits.startswith(BJ_PREFIXES):
        return "BJ"
    return None


def normalize_symbol(code: object) -> Symbol:
    if not isinstance(code, str):
        raise InvalidSymbol("code must be a string")
    text = code.strip().upper()
    match = _CODE_RE.match(text)
    if match is None:
        raise InvalidSymbol(f"unrecognized A-share code: {code!r}")
    digits = match.group("digits")
    inferred = _infer_exchange(digits)
    if inferred is None:
        raise InvalidSymbol(f"not a Shanghai/Shenzhen/Beijing A-share code: {code!r}")
    explicit = match.group("prefix") or match.group("suffix")
    if explicit == "SS":
        explicit = "SH"
    if explicit is not None and explicit != inferred:
        raise InvalidSymbol(f"exchange does not match code: {code!r}")
    if inferred == "BJ":
        raise UnsupportedMarket(f"Beijing Stock Exchange codes are not supported: {code!r}")
    return Symbol(canonical=f"{digits}.{inferred}", exchange=inferred, digits=digits)
