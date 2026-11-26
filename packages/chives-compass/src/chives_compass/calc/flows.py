"""Pure helpers for the main-net-inflow rankings (contract v1.3).

The vendor ``clist`` endpoint sorts server-side by ``f62``, but the sector
ranking has to be restricted to the engine's industry universe and the stock
ranking is filtered locally (ST / new listings / Beijing), so every response is
re-sorted and cut here.  ``sector_*`` sorts only rows that are already inside
the universe; ``stock_*`` reuses the same exclusion rules as ``/movers``.
Nothing in this module performs I/O or reads the clock.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from ..models import FlowRow
from .movers import filter_movers

FLOW_KINDS: tuple[str, ...] = ("sector_in", "sector_out", "stock_in", "stock_out")
SECTOR_KINDS = frozenset({"sector_in", "sector_out"})
STOCK_KINDS = frozenset({"stock_in", "stock_out"})
#: Shown verbatim in every ``/flows`` payload; the wording is the contract's.
FLOW_DEFINITION = "主力净流入（厂商口径，仅作辅助参考）"


def is_inflow(kind: str) -> bool:
    return kind.endswith("_in")


def sort_flows(rows: Sequence[FlowRow], kind: str) -> list[FlowRow]:
    """Descending for ``*_in`` (largest inflow first), ascending for ``*_out``."""
    if kind not in FLOW_KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if is_inflow(kind):
        return sorted(
            rows,
            key=lambda row: (
                row.main_net_yuan is None,
                -(row.main_net_yuan or 0.0),
                row.code,
            ),
        )
    return sorted(
        rows,
        key=lambda row: (
            row.main_net_yuan is None,
            row.main_net_yuan or 0.0,
            row.code,
        ),
    )


def select_flows(
    rows: Iterable[FlowRow],
    kind: str,
    limit: int,
    *,
    include_st: bool = False,
    include_new: bool = False,
    include_bj: bool = False,
) -> list[FlowRow]:
    """Filter (stocks only), sort and cut to ``limit`` rows."""
    candidates = list(rows)
    if kind in STOCK_KINDS:
        candidates = filter_movers(
            candidates,
            include_st=include_st,
            include_new=include_new,
            include_bj=include_bj,
        )
    return sort_flows(candidates, kind)[:limit]
