"""A-share / ETF / index code normalization for the gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass

_MAIN_RE = re.compile(r"^(?:(?P<prefix>SH|SZ|BJ))?(?P<digits>\d{6})(?:\.(?P<suffix>SH|SZ|SS|BJ))?$")
_OVERSEAS_RE = re.compile(r"^us[A-Z]{1,6}(\.[A-Z])?$|^hk\d{5}$")

INDEX_UNIVERSE: dict[str, dict[str, str]] = {
    "000001.SH": {"name": "上证指数", "symbol": "sh000001"},
    "399001.SZ": {"name": "深证成指", "symbol": "sz399001"},
    "399006.SZ": {"name": "创业板指", "symbol": "sz399006"},
    "000300.SH": {"name": "沪深300", "symbol": "sh000300"},
    "000905.SH": {"name": "中证500", "symbol": "sh000905"},
    "000852.SH": {"name": "中证1000", "symbol": "sh000852"},
    "000688.SH": {"name": "科创50", "symbol": "sh000688"},
    "000016.SH": {"name": "上证50", "symbol": "sh000016"},
    "899050.BJ": {"name": "北证50", "symbol": "bj899050"},
}
# Bare digits that are unambiguous index codes (000001 is both Ping An Bank and the Shanghai index).
_BARE_INDEX = {
    "000300": "000300.SH",
    "000905": "000905.SH",
    "000852": "000852.SH",
    "000688": "000688.SH",
    "000016": "000016.SH",
    "399001": "399001.SZ",
    "399006": "399006.SZ",
    "899050": "899050.BJ",
}
_SH_INDEX_DIGITS = {"000001", "000300", "000905", "000852", "000688", "000016"}
_SZ_INDEX_DIGITS = {"399001", "399006"}
_BJ_PREFIXES = ("92", "43", "83", "87", "88")
_BJ_INDEX_DIGITS = {"899050"}


class InvalidCode(ValueError):
    """Raised when an input code is not a supported A-share/ETF/index code."""


@dataclass(frozen=True)
class Code:
    canonical: str
    exchange: str
    digits: str
    is_index: bool

    @property
    def symbol(self) -> str:
        return f"{self.exchange.lower()}{self.digits}"

    @property
    def is_legacy_bj(self) -> bool:
        return self.exchange == "BJ" and self.digits.startswith(("43", "83", "87", "88"))


def _prefix_exchange(digits: str) -> str | None:
    if digits.startswith("6") or digits.startswith("5"):
        return "SH"
    if digits.startswith(("0", "1", "3")):
        return "SZ"
    if digits.startswith(_BJ_PREFIXES):
        return "BJ"
    return None


def _explicit_allowed(exchange: str, digits: str) -> bool:
    if exchange == "SH":
        return digits.startswith(("5", "6")) or digits in _SH_INDEX_DIGITS
    if exchange == "SZ":
        return digits.startswith(("0", "1", "3")) or digits in _SZ_INDEX_DIGITS
    if exchange == "BJ":
        return digits.startswith(_BJ_PREFIXES) or digits in _BJ_INDEX_DIGITS
    return False


def normalize_code(value: object) -> Code:
    if not isinstance(value, str):
        raise InvalidCode("代码必须是 6 位数字字符串，例如 600519、sh600519 或 600519.SH")
    text = value.strip().upper()
    match = _MAIN_RE.match(text)
    if match is None:
        raise InvalidCode(f"无法识别的代码 {value!r}；请用 6 位数字、sh600000 或 600000.SH 形式")
    digits = match.group("digits")
    explicit = match.group("prefix") or match.group("suffix")
    if explicit == "SS":
        explicit = "SH"
    prefix = match.group("prefix")
    suffix = match.group("suffix")
    if prefix and suffix and prefix != ("SH" if suffix == "SS" else suffix):
        raise InvalidCode(f"代码 {value!r} 的交易所前后缀冲突")
    if explicit is not None and not _explicit_allowed(explicit, digits):
        raise InvalidCode(f"代码 {value!r} 与交易所 {explicit} 不匹配")

    if explicit is not None:
        exchange = explicit
    elif digits in _BARE_INDEX:
        exchange = _BARE_INDEX[digits].split(".")[1]
    else:
        inferred = _prefix_exchange(digits)
        if inferred is None:
            raise InvalidCode(f"代码 {value!r} 不是沪深京 A 股、ETF 或指数代码")
        exchange = inferred

    canonical = f"{digits}.{exchange}"
    is_index = canonical in INDEX_UNIVERSE or (exchange == "SH" and digits in _SH_INDEX_DIGITS) or (
        exchange == "SZ" and digits in _SZ_INDEX_DIGITS
    ) or (exchange == "BJ" and digits in _BJ_INDEX_DIGITS)
    return Code(canonical=canonical, exchange=exchange, digits=digits, is_index=is_index)


def is_overseas_symbol(value: object) -> bool:
    return isinstance(value, str) and _OVERSEAS_RE.fullmatch(value) is not None


def normalize_overseas_symbol(value: object) -> str:
    if not is_overseas_symbol(value):
        raise InvalidCode(f"海外代码 {value!r} 不合法；请用 usNVDA、usBRK.B 或 hk00700 形式")
    return str(value)
