"""Runtime configuration for the scraper.

Everything here is read from environment variables once at start-up.  There are
no credential files, no API keys and no paths accepted from tool arguments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from scrape_mcp import __version__

DEFAULT_MIN_INTERVAL_SECONDS = 1.0
DEFAULT_REQUESTS_PER_MINUTE = 600
ROBOTS_TTL_SECONDS = 3600.0


class ConfigError(RuntimeError):
    """Raised before the server starts when the environment is malformed."""


@dataclass(frozen=True)
class Settings:
    allow_hosts: tuple[str, ...] = ()
    allow_loopback: bool = False
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    user_agent: str = field(default=f"dsh-finance-scrape/{__version__}")


def _parse_hosts(raw: str) -> tuple[str, ...]:
    hosts: list[str] = []
    for item in raw.split(","):
        host = item.strip().lower().rstrip(".")
        if not host:
            continue
        if "/" in host or ":" in host or "@" in host or any(ch.isspace() for ch in host):
            raise ConfigError("SCRAPE_ALLOW_HOSTS must be a comma-separated list of domain names")
        hosts.append(host)
    return tuple(hosts)


def _parse_float(values: dict[str, str], name: str, default: float) -> float:
    raw = (values.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if value < 0:
        raise ConfigError(f"{name} must not be negative")
    return value


def _parse_int(values: dict[str, str], name: str, default: int) -> int:
    raw = (values.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < 1:
        raise ConfigError(f"{name} must be at least 1")
    return value


def load_settings(env: dict[str, str] | None = None) -> Settings:
    values = os.environ if env is None else env
    return Settings(
        allow_hosts=_parse_hosts(values.get("SCRAPE_ALLOW_HOSTS") or ""),
        allow_loopback=values.get("SCRAPE_TEST_ALLOW_LOOPBACK") == "1",
        min_interval_seconds=_parse_float(
            values, "SCRAPE_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS
        ),
        requests_per_minute=_parse_int(
            values, "SCRAPE_MAX_REQUESTS_PER_MINUTE", DEFAULT_REQUESTS_PER_MINUTE
        ),
    )
