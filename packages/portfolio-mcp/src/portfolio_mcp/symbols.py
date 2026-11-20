"""A-share code normalization (`NNNNNN.SH/.SZ/.BJ`), including exchange-traded funds."""

from __future__ import annotations

import re
from dataclasses import dataclass

from portfolio_mcp.errors import PortfolioError

# A bare 1-6 digit code is left-padded; Excel strips the leading zeros of e.g. 000001.
_CODE_RE = re.compile(
    r"^(?:(?P<prefix>SH|SZ|BJ))?(?P<digits>\d{1,6})(?:\.(?P<suffix>SH|SZ|BJ|SS))?$"
)

SH_PREFIXES = ("6", "5", "11")  # 5xxxxx: Shanghai-listed ETF/LOF funds
SZ_PREFIXES = ("0", "3", "12", "158", "159", "16", "18")  # 159xxx/16xxxx: Shenzhen-listed funds
BJ_PREFIXES = ("81", "92", "43", "83", "87", "88")


@dataclass(frozen=True)
class Symbol:
    canonical: str
    exchange: str
    digits: str

    @property
    def tencent(self) -> str:
        """Vendor-style quote key: sh600000, sz000001, bj920418."""
        return f"{self.exchange.lower()}{self.digits}"


def _infer_exchange(digits: str) -> str | None:
    if digits.startswith(SH_PREFIXES):
        return "SH"
    if digits.startswith(SZ_PREFIXES):
        return "SZ"
    if digits.startswith(BJ_PREFIXES):
        return "BJ"
    return None


def normalize_symbol(code: object) -> Symbol:
    """Return the canonical symbol or raise PortfolioError('invalid_code')."""
    if not isinstance(code, str):
        raise PortfolioError("invalid_code", "code must be a string", field="code")
    text = code.strip().upper()
    if re.fullmatch(r"\d{6}\.OF", text):
        return Symbol(text, "OF", text[:6])
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    match = _CODE_RE.match(text)
    if match is None:
        raise PortfolioError(
            "invalid_code",
            "unrecognized A-share code; use NNNNNN.SH/.SZ/.BJ or a 6-digit bare code",
            field="code",
        )

    digits = match.group("digits").zfill(6)
    inferred = _infer_exchange(digits)
    if inferred is None:
        raise PortfolioError(
            "invalid_code",
            "code is not a Shanghai/Shenzhen/Beijing A-share code",
            field="code",
        )

    explicit = match.group("prefix") or match.group("suffix")
    if explicit == "SS":
        explicit = "SH"
    if explicit is not None and explicit != inferred:
        raise PortfolioError(
            "invalid_code",
            "exchange suffix does not match the code prefix",
            field="code",
        )

    return Symbol(canonical=f"{digits}.{inferred}", exchange=inferred, digits=digits)
