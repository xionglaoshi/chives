"""HTTP client for the local cn-market-gateway ``POST /v1/call`` endpoint.

Only loopback is allowed. Redirects are refused so a loopback request can never
be bounced to another host. No third-party dependency is needed.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8868"
CALL_PATH = "/v1/call"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class GatewayError(Exception):
    """Transport or envelope failure; clients translate it to their own error type."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise GatewayError("redirect_refused", f"refused redirect (HTTP {code})")


def normalize_gateway_url(raw: str) -> str:
    """Validate one gateway base URL; only loopback http(s) with a port is accepted."""
    text = raw.strip()
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise GatewayError("invalid_config", "gateway URL is not a valid URL") from exc
    if parts.scheme not in ("http", "https"):
        raise GatewayError("invalid_config", "gateway URL must be http(s)")
    if (parts.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise GatewayError("invalid_config", "gateway URL must point at loopback")
    try:
        port = parts.port
    except ValueError as exc:
        raise GatewayError("invalid_config", "gateway URL has an invalid port") from exc
    if port is None:
        raise GatewayError("invalid_config", "gateway URL must include a port")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise GatewayError("invalid_config", "gateway URL must not include a path or query")
    return text.rstrip("/")


def resolve_gateway_url(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    raw = (source.get("PORTFOLIO_GATEWAY_URL") or "").strip()
    if not raw:
        return DEFAULT_GATEWAY_URL
    return normalize_gateway_url(raw)


def call(
    base_url: str,
    tool: str,
    args: Mapping[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    """POST one tool call and return the decoded envelope."""
    url = base_url.rstrip("/") + CALL_PATH
    body = json.dumps({"tool": tool, "args": dict(args)}, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "portfolio-mcp/0.1",
        },
    )
    opener = build_opener(_RefuseRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except GatewayError:
        raise
    except HTTPError as exc:
        raise GatewayError("upstream_error", f"gateway returned HTTP {exc.code}") from exc
    except (URLError, OSError, ValueError) as exc:
        raise GatewayError(
            "upstream_error", f"gateway request failed ({type(exc).__name__})"
        ) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise GatewayError("upstream_error", "gateway response is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayError("upstream_error", "gateway returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise GatewayError("upstream_error", "gateway returned a non-object envelope")
    return payload
