"""Tiny JSON-over-HTTP client for chives-hub (stdlib only, loopback only)."""

from __future__ import annotations

import json
from http.client import HTTPException
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from hub_mcp.config import resolve_base_url
from hub_mcp.errors import HubError

DEFAULT_TIMEOUT = 5.0
MAX_RESPONSE_BYTES = 512 * 1024


class HubClient:
    """Call the hub with a hard timeout and a hard response-size cap."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self.base_url = resolve_base_url(base_url)
        self.timeout = float(timeout)
        self.max_bytes = int(max_bytes)
        # Never inherit HTTP(S)_PROXY: the hub is loopback-only.
        self._opener = build_opener(ProxyHandler({}))

    # -- public ----------------------------------------------------------
    def get_json(self, path: str, query: list[tuple[str, Any]] | None = None) -> dict[str, Any]:
        return self.request_json("GET", path, query=query)

    def post_json(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", path, body=body)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, Any]] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.base_url + path
        if query:
            pairs = [(key, str(value)) for key, value in query if value is not None]
            if pairs:
                url = f"{url}?{urlencode(pairs)}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(dict(body), ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, method=method, headers=headers)
        try:
            response = self._opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            # The hub returns machine-readable JSON even for 404s; keep it.
            return self._decode(exc.read(self.max_bytes + 1), status=exc.code)
        except (URLError, TimeoutError, OSError, HTTPException) as exc:
            reason = getattr(exc, "reason", exc)
            raise HubError("hub_unreachable", f"chives-hub 不可达：{reason}") from exc
        try:
            status = int(getattr(response, "status", 200))
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_len = int(declared)
                except ValueError:
                    declared_len = -1
                if declared_len > self.max_bytes:
                    raise HubError("response_too_large", "chives-hub 响应超过 512KB 上限")
            raw = response.read(self.max_bytes + 1)
        finally:
            response.close()
        return self._decode(raw, status=status)

    # -- internals -------------------------------------------------------
    def _decode(self, raw: bytes, *, status: int) -> dict[str, Any]:
        if len(raw) > self.max_bytes:
            raise HubError("response_too_large", "chives-hub 响应超过 512KB 上限")
        if not raw:
            raise HubError("invalid_response", f"chives-hub 返回空响应（HTTP {status}）")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HubError("invalid_response", f"chives-hub 返回非 JSON（HTTP {status}）") from exc
        if not isinstance(payload, dict):
            raise HubError("invalid_response", "chives-hub 返回的 JSON 不是对象")
        if "ok" not in payload:
            payload["ok"] = status < 400
        if payload.get("ok") is False:
            error = payload.get("error")
            if not isinstance(error, dict) or "code" not in error:
                payload["error"] = {
                    "code": "hub_error",
                    "message": f"chives-hub 错误（HTTP {status}）",
                }
        return payload
