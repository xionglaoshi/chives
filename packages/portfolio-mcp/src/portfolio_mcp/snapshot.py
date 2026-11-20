"""One JSON snapshot of the local portfolio for the Chives dashboard.

This module is read-only: it never writes the portfolio, never starts the MCP server,
and never sends the holdings anywhere except to the same quote source `valuation()`
already uses.
"""

from __future__ import annotations

from typing import Any

from portfolio_mcp.service import PortfolioService
from portfolio_mcp.store import PortfolioStore


def _today_pnl(item: dict[str, Any]) -> float | None:
    price = item.get("price_cny")
    prev_close = item.get("prev_close_cny")
    qty = item.get("qty_shares")
    if price is None or prev_close is None or qty is None:
        return None
    return (float(price) - float(prev_close)) * float(qty)


def _empty_state() -> dict[str, Any]:
    return {
        "status": "empty",
        "as_of": None,
        "cash": None,
        "summary": {
            "position_count": 0,
            "priced_count": 0,
            "unpriced_count": 0,
            "total_market_value": 0.0,
            "total_cost": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "today_pnl": None,
            "today_pnl_pct": None,
        },
        "positions": [],
        "unpriced": [],
        "warnings": [],
    }


def _error_state(message: str) -> dict[str, Any]:
    state = _empty_state()
    state["status"] = "error"
    state["warnings"] = [{"code": "snapshot_failed", "message": message}]
    return state


def build_snapshot(
    store: PortfolioStore | None = None,
    service: PortfolioService | None = None,
) -> dict[str, Any]:
    """Read the holdings and return the dashboard snapshot (a plain dict)."""
    try:
        portfolio = store if store is not None else PortfolioStore()
        state = portfolio.snapshot()
        reader = service if service is not None else PortfolioService(portfolio)
        payload = reader.valuation()
    except Exception as exc:  # defensive: the CLI must always print JSON
        return _error_state(type(exc).__name__)

    if payload.get("ok") is False:
        error = payload.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
        return _error_state(str(message or "持仓读取失败"))

    data = payload.get("data") or {}
    rows = data.get("positions") or []
    positions: list[dict[str, Any]] = []
    unpriced: list[dict[str, Any]] = []
    today_total = 0.0
    today_base = 0.0
    today_known = bool(rows)
    for item in rows:
        today = _today_pnl(item)
        code = str(item.get("code") or "")
        name = str(item.get("name") or "")
        if today is None:
            today_known = False
        else:
            today_total += today
            prev_close = item.get("prev_close_cny")
            qty = item.get("qty_shares")
            if prev_close is not None and qty is not None:
                today_base += float(prev_close) * float(qty)
        positions.append(
            {
                "code": code,
                "name": name,
                "qty": item.get("qty_shares"),
                "cost_price": item.get("cost_price_cny_per_share"),
                "price": item.get("price_cny"),
                "prev_close": item.get("prev_close_cny"),
                "change_pct": item.get("change_pct"),
                "market_value": item.get("market_value_cny"),
                "pnl": item.get("pnl_cny"),
                "pnl_pct": item.get("pnl_pct"),
                "today_pnl": today,
                "price_available": not bool(item.get("price_unavailable")),
                "quote_time": item.get("quote_time"),
            }
        )
        if item.get("price_unavailable"):
            unpriced.append(
                {
                    "code": code,
                    "name": name,
                    "reason": "行情缺失或停牌，已从汇总与权重中排除",
                }
            )

    positions.sort(
        key=lambda row: (
            row["market_value"] is None,
            -(row["market_value"] or 0.0),
            row["code"],
        )
    )
    today_pnl = today_total if today_known else None
    today_pnl_pct = (
        (today_total / today_base * 100)
        if today_known and today_base > 0
        else None
    )

    summary = {
        "position_count": int(data.get("count") or 0),
        "priced_count": int(data.get("priced_count") or 0),
        "unpriced_count": int(data.get("unpriced_count") or 0),
        "total_market_value": data.get("total_market_value_cny"),
        "total_cost": data.get("total_cost_cny"),
        "total_pnl": data.get("total_pnl_cny"),
        "total_pnl_pct": data.get("total_pnl_pct"),
        "today_pnl": today_pnl,
        "today_pnl_pct": today_pnl_pct,
    }
    warnings = [
        {"code": str(item.get("code") or "warning"), "message": str(item.get("message") or "")}
        for item in payload.get("warnings") or []
        if isinstance(item, dict)
    ]
    status = "empty" if not rows else str(payload.get("status") or "ok")
    return {
        "status": status,
        "as_of": None if not rows else (data.get("quote_time") or data.get("fetched_at")),
        "cash": state.cash,
        "summary": summary,
        "positions": positions,
        "unpriced": unpriced,
        "warnings": warnings,
    }
