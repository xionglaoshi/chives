"""Runtime configuration for the loopback strategy service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8869
DEFAULT_SCHEDULE = time(15, 35)
DEFAULT_RETRIES = 3
DEFAULT_START_DATE = "2020-01-01"


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages").is_dir() and (parent / "docs").is_dir():
            return parent
    return Path.cwd()


def _env_path(name: str, fallback: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    return Path(raw).expanduser() if raw else fallback


@dataclass(frozen=True)
class HubConfig:
    host: str
    port: int
    db_path: Path
    daily_db: Path
    surge_db: Path
    surge_state: Path
    start_date: str
    schedule_time: time
    retries: int
    allowed_strategies: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "HubConfig":
        root = repo_root()
        host = (os.environ.get("STRATEGY_HUB_HOST") or DEFAULT_HOST).strip()
        raw_port = (os.environ.get("STRATEGY_HUB_PORT") or str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError(f"STRATEGY_HUB_PORT 不是整数：{raw_port}") from exc
        if not 0 <= port <= 65535:
            raise ValueError(f"STRATEGY_HUB_PORT 超出范围：{port}")
        raw_time = (os.environ.get("STRATEGY_HUB_SCHEDULE") or "15:35").strip()
        try:
            hour, minute = (int(part) for part in raw_time.split(":", 1))
            schedule = time(hour, minute)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"STRATEGY_HUB_SCHEDULE 需要 HH:MM：{raw_time}") from exc
        raw_retries = (os.environ.get("STRATEGY_HUB_RETRIES") or str(DEFAULT_RETRIES)).strip()
        try:
            retries = max(1, int(raw_retries))
        except ValueError as exc:
            raise ValueError(f"STRATEGY_HUB_RETRIES 不是整数：{raw_retries}") from exc
        allowed_raw = (os.environ.get("CHIVES_STRATEGIES") or "").strip()
        allowed = tuple(part.strip() for part in allowed_raw.split(",") if part.strip())
        return cls(
            host=host,
            port=port,
            db_path=_env_path("STRATEGY_HUB_DB", root / "runtime" / "strategy-hub" / "strategy.sqlite"),
            daily_db=_env_path("CN_DAILY_STORE_DB", root / "runtime" / "marketdata" / "daily.sqlite"),
            surge_db=_env_path("SURGE_ENGINE_DB", root / "runtime" / "surge" / "surge.sqlite"),
            surge_state=_env_path("SURGE_ENGINE_STATE", root / "runtime" / "surge" / "state.json"),
            start_date=(os.environ.get("STRATEGY_HUB_REPLAY_START") or DEFAULT_START_DATE).strip(),
            schedule_time=schedule,
            retries=retries,
            allowed_strategies=allowed,
        )
