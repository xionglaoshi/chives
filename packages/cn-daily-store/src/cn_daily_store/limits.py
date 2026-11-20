"""Price-limit rules from ``docs/strategy/zhushenglang-spec.md`` section 0.

Pure functions only; the store supplies the previous valid raw close, the board
and the ST flag.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MAIN_BOARDS = frozenset({"sh_main", "sz_main"})
ALL_BOARDS = frozenset({"sh_main", "sz_main", "chinext", "star"})
CHINEXT_REFORM = date(2020, 8, 24)
CENT = Decimal("0.01")
_PRICE_QUANT = Decimal("0.001")


def round_half_up_to_cent(value: float | str | Decimal) -> Decimal:
    """Round a price to the nearest cent, halves away from zero."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def round_price(value: float | str | Decimal) -> Decimal:
    """Round an adjusted price to 0.001 (source qfq precision)."""
    return Decimal(str(value)).quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)


def limit_ratio_for(board: str, day: date, st: bool) -> Decimal | None:
    """Return the daily price-limit ratio applicable on ``day``.

    Main board 10% (ST 5%); ChiNext 20% from 2020-08-24 (including ST), before
    that 10% (ST 5%); STAR 20% (also for ST).  Unknown boards return ``None``.
    """
    if board in MAIN_BOARDS:
        return Decimal("0.05") if st else Decimal("0.10")
    if board == "chinext":
        if day >= CHINEXT_REFORM:
            return Decimal("0.20")
        return Decimal("0.05") if st else Decimal("0.10")
    if board == "star":
        return Decimal("0.20")
    return None


def limit_price_from(prev_close: float | str | Decimal, ratio: Decimal) -> Decimal:
    """``round_half_up(prev_close * (1 + ratio), 2)``."""
    base = Decimal(str(prev_close))
    return (base * (Decimal("1") + ratio)).quantize(CENT, rounding=ROUND_HALF_UP)


def is_st_name(name: str | None) -> bool:
    """Approximate ST/*ST from a security abbreviation."""
    if not name:
        return False
    compact = "".join(str(name).upper().split())
    return re.match(r"^(?:\*ST|S\*ST|SST|ST)(?![A-Z])", compact) is not None


def is_delisting_name(name: str | None) -> bool:
    """Approximate the delisting-consolidation board from the abbreviation."""
    if not name:
        return False
    compact = "".join(str(name).split())
    return compact.startswith("退市") or compact.startswith("退")
