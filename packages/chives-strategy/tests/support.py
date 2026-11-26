from __future__ import annotations

from pathlib import Path

from chives_strategy.db import AlertStore
from chives_strategy.service import HubService
from chives_strategy.strategy import ZhushenglangStrategy


def build_service(paths: dict[str, Path], backtests=None) -> HubService:
    strategy = ZhushenglangStrategy(paths["surge"], paths["daily"])
    return HubService({strategy.id: strategy}, AlertStore(paths["hub"]), backtests=backtests)
