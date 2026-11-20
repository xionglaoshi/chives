"""Quote lookups that survive without the old card evaluator.

Cards are evaluated by cn-watch now; the hub only needs one latest price when a
card is created (sizing) and one day snapshot when outcomes are written.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

QUOTE_FIELDS = (
    "price",
    "prev_close",
    "open",
    "high",
    "low",
    "change_pct",
    "volume_ratio",
    "name",
)


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _quote_from(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "price": _num(item.get("price")),
        "prev_close": _num(item.get("prev_close")),
        "open": _num(item.get("open")),
        "high": _num(item.get("high")),
        "low": _num(item.get("low")),
        "change_pct": _num(item.get("change_pct")),
        "volume_ratio": _num(item.get("volume_ratio")),
        "name": item.get("name"),
    }


def _tencent_quote(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return _quote_from(item)
    return _quote_from(
        {
            "price": getattr(item, "price", None),
            "prev_close": getattr(item, "prev_close", None),
            "change_pct": getattr(item, "change_pct", None),
            "name": getattr(item, "name", None),
        }
    )


def quotes_for(
    sources: Any, codes: Iterable[str], *, now: datetime
) -> dict[str, dict[str, Any]]:
    """Return whatever quotes are available; missing codes stay absent."""
    wanted = [str(code) for code in codes if code]
    if not wanted:
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        state = sources.cn_state(now=now)
    except Exception:  # noqa: BLE001 - upstream failure simply means no quote
        state = None
    raw_quotes = state.get("quotes") if isinstance(state, Mapping) else None
    if isinstance(raw_quotes, Mapping):
        for code, item in raw_quotes.items():
            if isinstance(item, Mapping):
                result[str(code)] = _quote_from(item)
    missing = [code for code in wanted if code not in result]
    if missing:
        try:
            fetched = sources.tencent_quotes(missing, now=now)
        except Exception:  # noqa: BLE001
            fetched = None
        for code, item in (fetched or {}).items():
            result[str(code)] = _tencent_quote(item)
    return result


def latest_price(sources: Any, code: str, *, now: datetime) -> Optional[float]:
    quote = quotes_for(sources, [code], now=now).get(code)
    return _num((quote or {}).get("price"))
