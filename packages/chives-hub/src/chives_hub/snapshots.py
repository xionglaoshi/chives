"""Daily equity snapshot: one row per trading day, written after the close."""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any, Optional

from .calendar import TradingCalendar
from .models import CN_TZ

logger = logging.getLogger("chives_hub.snapshots")


class SnapshotService:
    def __init__(
        self,
        store: Any,
        portfolio: Any,
        calendar: TradingCalendar,
        *,
        close_time: time = time(15, 5),
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.portfolio = portfolio
        self.calendar = calendar
        self.close_time = close_time
        self.enabled = enabled

    def due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        local = now.astimezone(CN_TZ)
        if not self.calendar.is_trading_day(local.date()):
            return False
        close_at = datetime.combine(local.date(), self.close_time, tzinfo=CN_TZ)
        if local < close_at:
            return False
        return self.store.get_snapshot(local.date()) is None

    def maybe_write(self, now: datetime) -> Optional[dict[str, Any]]:
        if not self.due(now):
            return None
        values = self.portfolio.snapshot_values()
        if not values:
            return None
        local = now.astimezone(CN_TZ)
        created = self.store.insert_snapshot(
            day=local.date(),
            market_value_cny=values["market_value_cny"],
            total_assets_cny=values["total_assets_cny"],
            pnl_cny=values["pnl_cny"],
            day_pnl_cny=values["day_pnl_cny"],
            quote_time=values.get("quote_time"),
            now=now,
        )
        if not created:
            return None
        logger.info("daily snapshot written for %s", local.date().isoformat())
        return self.store.get_snapshot(local.date())
