"""Runtime settings: pinned upstream URL, FMP_TEST_MODE guard and API key lookup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

PRODUCTION_BASE_URL = "https://financialmodelingprep.com"
API_KEY_NAME = "FMP_API_KEY"
DOTENV_ENV = "DSH_FINANCE_SECRETS"
# <repo>/packages/fmp-mcp/src/fmp_mcp/config.py -> parents[4] is <repo>
DEFAULT_SECRETS_PATH = Path(__file__).resolve().parents[4] / "config" / "secrets.env"


class ConfigError(RuntimeError):
    """Raised when the configured upstream/base URL is not allowed."""


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str | None
    key_source: str | None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def read_key_file(path: Path) -> str | None:
    """Return FMP_API_KEY from a dotenv-style file, or None. Never logs the value."""
    try:
        text = path.expanduser().read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        if not sep or name.strip() != API_KEY_NAME:
            continue
        value = _unquote(value)
        if value:
            return value
    return None


def resolve_api_key(environ: Mapping[str, str] | None = None) -> tuple[str | None, str | None]:
    """Three-step lookup: process env, DSH_FINANCE_SECRETS file, repository default file."""
    env = os.environ if environ is None else environ
    value = (env.get(API_KEY_NAME) or "").strip()
    if value:
        return value, "environment"
    explicit = (env.get(DOTENV_ENV) or "").strip()
    if explicit:
        # An explicit path is authoritative: do not silently fall back to the default file.
        value = read_key_file(Path(explicit))
        return (value, "secrets_file") if value else (None, None)
    value = read_key_file(DEFAULT_SECRETS_PATH)
    return (value, "default_secrets_file") if value else (None, None)


def resolve_base_url(environ: Mapping[str, str] | None = None) -> str:
    """Production is pinned; FMP_BASE_URL exists only as a loopback test hook."""
    env = os.environ if environ is None else environ
    override = (env.get("FMP_BASE_URL") or "").strip()
    if not override:
        return PRODUCTION_BASE_URL
    if env.get("FMP_TEST_MODE") != "1":
        raise ConfigError("FMP_BASE_URL is only allowed when FMP_TEST_MODE=1")
    parsed = urlparse(override)
    if parsed.scheme != "http":
        raise ConfigError("FMP_BASE_URL must use http in test mode")
    if parsed.username or parsed.password:
        raise ConfigError("FMP_BASE_URL must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConfigError("FMP_BASE_URL must be a bare origin")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("FMP_BASE_URL must point at a loopback host in test mode")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("FMP_BASE_URL has an invalid port") from exc
    if port is None or not 1 <= port <= 65535:
        raise ConfigError("FMP_BASE_URL must include a valid port")
    return f"http://127.0.0.1:{port}"


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    base_url = resolve_base_url(env)
    api_key, source = resolve_api_key(env)
    return Settings(base_url=base_url, api_key=api_key, key_source=source)
