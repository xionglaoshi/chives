"""Private portfolio overview and history.

Valuation is **not** re-implemented here: the hub inserts
``packages/portfolio-mcp/src`` into ``sys.path`` and reuses
``PortfolioStore`` / ``PortfolioService`` / ``TencentQuoteClient``.  That keeps
the hub's numbers identical to ``portfolio_valuation``.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .models import CN_TZ, fmt_iso

logger = logging.getLogger("chives_hub.portfolio")

_UNSET = object()
RISK_TTL_SECONDS = 600.0


def ensure_portfolio_path() -> Path:
    """Insert the sibling portfolio-mcp source tree once; return its path."""
    root = Path(__file__).resolve().parents[3] / "portfolio-mcp" / "src"
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root


def _pct(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number * 100.0 if math.isfinite(number) else None


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


class PortfolioView:
    def __init__(
        self,
        store: Any,
        *,
        profile_dir: Optional[Path] = None,
        service: Any = _UNSET,
        risk_ttl: float = RISK_TTL_SECONDS,
        now: Optional[Any] = None,
    ) -> None:
        self.store = store
        self.profile_dir = profile_dir
        self._service = service
        self._risk_ttl = risk_ttl
        self._clock = now
        self._lock = threading.Lock()
        self._risk_cache: Optional[tuple[tuple[Any, ...], datetime, Any, Optional[str]]] = None
        self._risk_inflight = False

    # -- service ---------------------------------------------------------
    def service(self) -> Any:
        if self._service is not _UNSET and self._service is not None:
            return self._service
        ensure_portfolio_path()
        from portfolio_mcp.quotes import TencentQuoteClient
        from portfolio_mcp.service import PortfolioService
        from portfolio_mcp.store import PortfolioStore

        portfolio_store = PortfolioStore(profile_dir=self.profile_dir)
        self._service = PortfolioService(portfolio_store, quotes=TencentQuoteClient())
        return self._service

    def _now(self) -> datetime:
        if callable(self._clock):
            return self._clock()
        return datetime.now(CN_TZ)

    # -- valuation -------------------------------------------------------
    def _base_overview(self) -> dict[str, Any]:
        now = self._now()
        payload = self.service().valuation()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise RuntimeError("portfolio valuation returned no data")
        positions: list[dict[str, Any]] = []
        industry_by_code = self._industry_map()
        day_pnl_total = 0.0
        prev_value_total = 0.0
        for item in data.get("positions") or []:
            qty = item.get("qty_shares")
            price = item.get("price_cny")
            prev_close = item.get("prev_close_cny")
            day_pnl: Optional[float] = None
            if qty is not None and price is not None and prev_close is not None:
                day_pnl = float(qty) * (float(price) - float(prev_close))
                day_pnl_total += day_pnl
                prev_value_total += float(qty) * float(prev_close)
            positions.append(
                {
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "industry": item.get("industry") or industry_by_code.get(str(item.get("code"))),
                    "qty": qty,
                    "cost_price_cny": item.get("cost_price_cny_per_share", item.get("cost_price_cny")),
                    "price_cny": price,
                    "prev_close_cny": prev_close,
                    "change_pct": item.get("change_pct"),
                    "market_value_cny": item.get("market_value_cny"),
                    "pnl_cny": item.get("pnl_cny"),
                    "pnl_pct": item.get("pnl_pct"),
                    "day_pnl_cny": day_pnl,
                    "weight_pct": (
                        None
                        if item.get("weight") is None
                        else float(item["weight"]) * 100.0
                    ),
                    "sellable_today": bool(item.get("sellable_today")),
                    "price_unavailable": bool(item.get("price_unavailable")),
                }
            )
        total_market_value = float(data.get("total_market_value_cny") or 0.0)
        cash = float(data.get("cash_cny") or 0.0)
        total_assets = float(data.get("total_assets_cny") or 0.0)
        totals = {
            "market_value_cny": total_market_value,
            "cost_cny": float(data.get("total_cost_cny") or 0.0),
            "pnl_cny": float(data.get("total_pnl_cny") or 0.0),
            "pnl_pct": float(data.get("total_pnl_pct") or 0.0),
            "day_pnl_cny": day_pnl_total,
            "day_pnl_pct": (
                day_pnl_total / prev_value_total * 100.0 if prev_value_total > 0 else None
            ),
            "cash_cny": cash,
            "total_assets_cny": total_assets,
            "position_ratio_pct": (
                total_market_value / total_assets * 100.0 if total_assets > 0 else None
            ),
        }
        return {
            "ok": True,
            "private": True,
            "as_of": fmt_iso(now),
            "quote_time": data.get("quote_time"),
            "empty": not positions,
            "totals": totals,
            "positions": positions,
        }

    def _industry_map(self) -> dict[str, Any]:
        """Industry labels live in the portfolio file, not the valuation payload."""
        try:
            store = getattr(self.service(), "_store", None)
            if store is None:
                return {}
            state = store.snapshot()
            return {
                str(item.get("code")): item.get("industry")
                for item in getattr(state, "positions", []) or []
                if item.get("code")
            }
        except Exception:  # noqa: BLE001 - industry is optional metadata
            return {}

    def _risk(self, positions: list[dict[str, Any]], now: datetime) -> tuple[Any, Optional[str]]:
        fingerprint = tuple(
            sorted((str(item.get("code")), item.get("qty"), item.get("cost_price_cny")) for item in positions)
        )
        with self._lock:
            cached = self._risk_cache
            if cached is not None:
                cached_key, cached_at, cached_value, cached_reason = cached
                if cached_key == fingerprint and (now - cached_at).total_seconds() < self._risk_ttl:
                    return cached_value, cached_reason
            if self._risk_inflight:
                return None, "risk_pending"
            self._risk_inflight = True

        def compute() -> None:
            value: Any = None
            reason: Optional[str] = None
            try:
                result = self.service().risk({"window_days": 250})
                data = result.get("data") if isinstance(result, dict) else None
                if not isinstance(data, dict) or not result.get("ok", True):
                    reason = "risk_unavailable"
                else:
                    mapped = {
                        "annualized_vol_pct": _pct(data.get("annualized_vol_ratio")),
                        "beta": _finite(data.get("beta")),
                        "max_drawdown_pct": _pct(data.get("max_drawdown_ratio")),
                        "top1_weight_pct": _pct(data.get("top1_weight_ratio")),
                        "effective_n": _finite(data.get("effective_n")),
                    }
                    if all(item is None for item in mapped.values()):
                        reason = "risk_unavailable"
                    else:
                        value = mapped
            except Exception as exc:  # noqa: BLE001 - risk is optional, never log holdings
                logger.warning("portfolio risk unavailable: %s", type(exc).__name__)
                reason = "risk_unavailable"
            with self._lock:
                self._risk_cache = (fingerprint, now, value, reason)
                self._risk_inflight = False

        worker = threading.Thread(target=compute, name="chives-hub-risk", daemon=True)
        worker.start()
        worker.join(timeout=2.5)
        if worker.is_alive():
            return None, "risk_pending"
        with self._lock:
            cached = self._risk_cache
        if cached is None or cached[0] != fingerprint:
            return None, "risk_pending"
        return cached[2], cached[3]

    def overview(self) -> dict[str, Any]:
        payload = self._base_overview()
        now = self._now()
        if payload["positions"]:
            risk, reason = self._risk(payload["positions"], now)
        else:
            risk, reason = None, "empty_portfolio"
        payload["risk"] = risk
        if risk is None:
            payload["risk_reason"] = reason
        payload["history_days"] = self.store.count_snapshots()
        return payload

    def snapshot_values(self) -> Optional[dict[str, Any]]:
        try:
            payload = self._base_overview()
        except Exception as exc:  # noqa: BLE001 - snapshot failure must not kill the poller
            logger.warning("portfolio snapshot unavailable: %s", type(exc).__name__)
            return None
        totals = payload["totals"]
        return {
            "market_value_cny": totals["market_value_cny"],
            "total_assets_cny": totals["total_assets_cny"],
            "pnl_cny": totals["pnl_cny"],
            "day_pnl_cny": totals["day_pnl_cny"],
            "quote_time": payload.get("quote_time"),
        }

    def history(self, days: int = 90) -> dict[str, Any]:
        days = max(1, min(int(days), 3650))
        rows = self.store.list_snapshots(days)
        points = [
            {
                "date": row["day"],
                "market_value_cny": row["market_value_cny"],
                "total_assets_cny": row["total_assets_cny"],
                "pnl_cny": row["pnl_cny"],
                "day_pnl_cny": row["day_pnl_cny"],
            }
            for row in rows
        ]
        return {
            "ok": True,
            "private": True,
            "points": points,
            "note": "只有从启用日起的快照，不回补历史",
        }
