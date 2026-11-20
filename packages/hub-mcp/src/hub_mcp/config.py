"""Resolve and validate CHIVES_HUB_URL and HUB_MCP_PROFILE.

The hub is a loopback-only service by contract, so the MCP server refuses to
start against anything else.  Validation is purely lexical: no DNS lookup and
no network access happens before the address has been accepted.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from hub_mcp.errors import HubConfigError

DEFAULT_HUB_URL = "http://127.0.0.1:8867"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
# Review layer offline (2026-11-16): the default profile is ``core`` (signals and plans only) while the review /
# battle-card / settings feature is redesigned. ``agent`` and ``readonly`` still expose the full v2 tool set and are
# kept for tests and for bringing the feature back (set HUB_MCP_PROFILE=agent).
DEFAULT_PROFILE = "core"
PROFILES = ("core", "core_readonly", "agent", "readonly")


def validate_base_url(raw: str) -> str:
    """Return a normalized ``scheme://host[:port]`` or raise HubConfigError."""
    if not isinstance(raw, str) or not raw.strip():
        raise HubConfigError("CHIVES_HUB_URL 不能为空")
    text = raw.strip()
    try:
        parsed = urlsplit(text)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise HubConfigError("CHIVES_HUB_URL 不是合法的 URL") from exc
    if parsed.scheme not in {"http", "https"}:
        raise HubConfigError("CHIVES_HUB_URL 必须是 http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise HubConfigError("CHIVES_HUB_URL 不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise HubConfigError("CHIVES_HUB_URL 不能包含查询参数或片段")
    if parsed.path not in {"", "/"}:
        raise HubConfigError("CHIVES_HUB_URL 不能包含路径")
    if host not in LOOPBACK_HOSTS:
        raise HubConfigError("CHIVES_HUB_URL 必须是回环地址（127.0.0.1/localhost/::1）")
    if port is not None and not 1 <= port <= 65535:
        raise HubConfigError("CHIVES_HUB_URL 的端口必须在 1..65535")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return f"{parsed.scheme}://{netloc}"


def resolve_base_url(raw: str | None = None) -> str:
    """Read the environment (empty means default) and validate it."""
    value = raw if raw is not None else os.environ.get("CHIVES_HUB_URL", "")
    if value is None or not value.strip():
        value = DEFAULT_HUB_URL
    return validate_base_url(value)


def validate_profile(raw: str) -> str:
    """Return a known tool profile or raise HubConfigError (startup failure)."""
    if not isinstance(raw, str) or not raw.strip():
        raise HubConfigError("HUB_MCP_PROFILE 不能为空")
    text = raw.strip().lower()
    if text not in PROFILES:
        raise HubConfigError(
            "HUB_MCP_PROFILE 只接受 core/core_readonly/agent/readonly，收到未知值；已拒绝启动"
        )
    return text


def resolve_profile(raw: str | None = None) -> str:
    """Read HUB_MCP_PROFILE (empty means ``core``) and validate it."""
    value = raw if raw is not None else os.environ.get("HUB_MCP_PROFILE", "")
    if value is None or not value.strip():
        value = DEFAULT_PROFILE
    return validate_profile(value)
