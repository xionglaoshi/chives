"""Engine address resolution with a hard loopback-only rule."""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

DEFAULT_ENGINE = "http://127.0.0.1:8866"
ENV_NAME = "MARKET_WATCH_URL"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class EngineConfigError(ValueError):
    """MARKET_WATCH_URL is malformed or points outside the local host."""


def resolve_engine_base(env: Mapping[str, str] | None = None) -> str:
    """Return the configured engine base URL, refusing any non-loopback host."""
    source = os.environ if env is None else env
    raw = source.get(ENV_NAME, "").strip() or DEFAULT_ENGINE
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise EngineConfigError(f"{ENV_NAME} is not a valid URL: {exc}") from exc
    if parts.scheme not in {"http", "https"}:
        raise EngineConfigError(f"{ENV_NAME} must use http or https")
    if parts.username is not None or parts.password is not None:
        raise EngineConfigError(f"{ENV_NAME} must not contain credentials")
    try:
        host = (parts.hostname or "").lower()
        parts.port
    except ValueError as exc:
        raise EngineConfigError(f"{ENV_NAME} is not a valid URL: {exc}") from exc
    if host not in LOOPBACK_HOSTS:
        raise EngineConfigError(
            f"{ENV_NAME} must point at a loopback host (127.0.0.1, localhost, [::1]), "
            f"got {host or '<empty>'}"
        )
    if parts.path.rstrip("/") or parts.query or parts.fragment:
        raise EngineConfigError(f"{ENV_NAME} must be an origin without a path, query or fragment")
    return raw.rstrip("/")
