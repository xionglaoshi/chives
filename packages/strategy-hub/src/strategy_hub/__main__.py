"""`strategy-hub` entry point: build the local service and serve on loopback."""

from __future__ import annotations

import argparse
import logging
import sys

from .backtest import BacktestJobStore, BacktestManager
from .config import HubConfig, repo_root
from .daemon import HubDaemon
from .db import AlertStore
from .scheduler import Scheduler, SubprocessRunner
from .service import HubService
from .strategy import ZhushenglangStrategy


def build_service(config: HubConfig) -> HubService:
    strategy = ZhushenglangStrategy(config.surge_db, config.daily_db)
    alerts = AlertStore(config.db_path)
    strategies = {strategy.id: strategy}
    manager = BacktestManager(
        strategies,
        BacktestJobStore(config.db_path),
        run_root=repo_root() / "runtime" / "surge" / "backtest",
    )
    return HubService(strategies, alerts, backtests=manager)


def main(argv: list[str] | None = None) -> int:
    config = HubConfig.from_env()
    parser = argparse.ArgumentParser(prog="strategy-hub", description="Loopback strategy service for Chives")
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=config.port)
    parser.add_argument("--no-scheduler", action="store_true")
    parsed = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    service = build_service(config)
    daemon = HubDaemon(service, host=parsed.host, port=parsed.port)
    scheduler = Scheduler(
        service,
        SubprocessRunner(
            daily_db=config.daily_db,
            surge_db=config.surge_db,
            surge_state=config.surge_state,
        ),
        schedule=config.schedule_time,
        retries=config.retries,
        start_date=config.start_date,
    )
    service.scheduler_state = scheduler.snapshot
    if not parsed.no_scheduler:
        scheduler.start()
    logging.info("strategy-hub listening on %s:%s", parsed.host, daemon.port)
    try:
        daemon.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        daemon.httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
