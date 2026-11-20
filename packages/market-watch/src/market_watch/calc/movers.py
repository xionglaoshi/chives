"""Pure helpers for the all-A mover lists (normalise, filter, sort).

The vendor ``clist`` endpoint already sorts server-side, but the local
filtering (ST / new listings / Beijing) would otherwise leave the list short or
out of order, so every response is filtered and re-sorted here.  Nothing in
this module performs I/O or reads the clock.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Optional, Sequence

from ..models import MoverRow
from .metrics import is_new_stock, is_st_stock

MOVER_KINDS: tuple[str, ...] = ("gainers", "losers", "active")
#: Boards whose daily price limit is 20% or 30% (ChiNext, STAR, Beijing).
WIDE_LIMIT_PREFIXES: tuple[str, ...] = ("300", "301", "688", "689")
#: A main-board first-day listing can gain at most 44%; anything at or above
#: that on a 10%-limit board cannot be an ordinary trading day.
IPO_FIRST_DAY_GAIN_PCT = 44.0


def normalize_stock_code(code: str) -> Optional[str]:
    """``600519`` / ``600519.sh`` -> ``600519.SH``; ``920627`` -> ``920627.BJ``."""
    text = str(code or "").strip().upper()
    if "." in text:
        digits, suffix = text.split(".", 1)
        if len(digits) == 6 and digits.isdigit() and suffix in {"SH", "SZ", "BJ"}:
            return f"{digits}.{suffix}"
        return None
    digits = text
    if len(digits) != 6 or not digits.isdigit():
        return None
    if digits.startswith("920"):
        return f"{digits}.BJ"
    if digits[0] in {"6", "9"}:
        return f"{digits}.SH"
    if digits[0] in {"0", "2", "3"}:
        return f"{digits}.SZ"
    if digits[0] in {"4", "8"}:
        return f"{digits}.BJ"
    return None


def is_beijing(code: str) -> bool:
    return str(code or "").upper().endswith(".BJ")


def is_wide_limit_board(code: str) -> bool:
    """True for ChiNext / STAR / Beijing rows (20% or 30% daily limit)."""
    digits = str(code or "").split(".", 1)[0]
    return is_beijing(code) or digits.startswith(WIDE_LIMIT_PREFIXES)


def is_abnormal_new_listing(code: str, change_pct: Optional[float]) -> bool:
    """A ``>= 44%`` move on a 10%-limit board is treated as a new listing."""
    if change_pct is None:
        return False
    return float(change_pct) >= IPO_FIRST_DAY_GAIN_PCT and not is_wide_limit_board(code)


def is_new_listing(name: str, code: str, change_pct: Optional[float]) -> bool:
    """Conservative new-listing test: ``N``/``C`` prefix or an impossible move."""
    return is_new_stock(name) or is_abnormal_new_listing(code, change_pct)


def filter_movers(
    rows: Iterable[MoverRow],
    *,
    include_st: bool = False,
    include_new: bool = False,
    include_bj: bool = False,
) -> list[MoverRow]:
    """Apply the contract's default exclusions and keep the canonical code form."""
    result: list[MoverRow] = []
    for row in rows:
        code = normalize_stock_code(row.code)
        if code is None:
            continue
        if not include_bj and is_beijing(code):
            continue
        if not include_st and is_st_stock(row.name):
            continue
        if not include_new and is_new_listing(row.name, code, row.change_pct):
            continue
        result.append(row if row.code == code else replace(row, code=code))
    return result


def sort_movers(rows: Sequence[MoverRow], kind: str) -> list[MoverRow]:
    """Deterministic ordering: gainers/losers by change, active by amount."""
    if kind == "gainers":
        return sorted(
            rows,
            key=lambda row: (
                -(row.change_pct if row.change_pct is not None else -1e18),
                row.code,
            ),
        )
    if kind == "losers":
        return sorted(
            rows,
            key=lambda row: (
                row.change_pct if row.change_pct is not None else 1e18,
                row.code,
            ),
        )
    if kind == "active":
        return sorted(
            rows, key=lambda row: (-(row.amount_yuan or 0.0), row.code)
        )
    raise ValueError(f"unknown kind: {kind}")


def select_movers(
    rows: Iterable[MoverRow],
    kind: str,
    limit: int,
    *,
    include_st: bool = False,
    include_new: bool = False,
    include_bj: bool = False,
) -> list[MoverRow]:
    kept = filter_movers(
        rows,
        include_st=include_st,
        include_new=include_new,
        include_bj=include_bj,
    )
    return sort_movers(kept, kind)[:limit]
