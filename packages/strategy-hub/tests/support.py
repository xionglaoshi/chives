from __future__ import annotations

from pathlib import Path

from strategy_hub.db import AlertStore
from strategy_hub.service import HubService
from strategy_hub.strategy import ZhushenglangStrategy


def build_service(paths: dict[str, Path], backtests=None) -> HubService:
    strategy = ZhushenglangStrategy(paths["surge"], paths["daily"])
    return HubService({strategy.id: strategy}, AlertStore(paths["hub"]), backtests=backtests)
