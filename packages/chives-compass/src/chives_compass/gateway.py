"""Loopback client for the cn-market-gateway ``POST /v1/call`` API.

This is the only outbound transport of market-watch: every external datum is
read through the gateway, so the rule layer owns no vendor host list.
"""

from __future__ import annotations

import http.client
import json
import time as _time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlparse

from .models import CN_TZ, fmt_iso

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8868"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BYTES = 4 * 1024 * 1024


class SourceError(Exception):
    """Upstream failure; ``code`` is a short machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_gateway_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise SourceError("bad_gateway_url", "网关地址必须是 http(s)")
    if (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise SourceError("bad_gateway_url", "网关地址必须是回环地址")
    if parsed.username is not None or parsed.password is not None:
        raise SourceError("bad_gateway_url", "网关地址不允许包含凭据")
    return value.rstrip("/")


class GatewayClient:
    """JSON-over-HTTP client with health counters and no proxy/redirects."""

    def __init__(
        self,
        base_url: str = DEFAULT_GATEWAY_URL,
        *,
        timeout: float = 5.0,
        clock: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.base_url = validate_gateway_url(base_url)
        self.timeout = float(timeout)
        self._clock = clock or (lambda: _time.monotonic())
        self.requests = 0
        self.failures = 0
        self.last_error: Optional[str] = None
        self.last_ok: Optional[str] = None
        self._tools: dict[str, dict[str, Any]] = {}

    def call(self, tool: str, args: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        body = json.dumps({"tool": tool, "args": dict(args or {})}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/v1/call",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.requests += 1
        token = self._tools.setdefault(tool, {"requests": 0, "failures": 0, "last_error": None})
        token["requests"] += 1
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES + 1)
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as exc:
            self._fail(tool, token, type(exc).__name__)
            raise SourceError("gateway_unavailable", "行情网关不可用") from exc
        if len(raw) > MAX_BYTES:
            self._fail(tool, token, "response_too_large")
            raise SourceError("gateway_unavailable", "行情网关响应过大")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._fail(tool, token, "invalid_json")
            raise SourceError("gateway_unavailable", "行情网关返回了非 JSON") from exc
        if not isinstance(payload, dict):
            self._fail(tool, token, "invalid_payload")
            raise SourceError("gateway_unavailable", "行情网关返回了非对象")
        status = payload.get("status")
        if status == "unavailable":
            message = payload.get("message") if isinstance(payload.get("message"), str) else "数据暂时取不到"
            self._fail(tool, token, "unavailable")
            raise SourceError("gateway_unavailable", message)
        if status not in {"ok", "partial"}:
            self._fail(tool, token, "invalid_status")
            raise SourceError("gateway_unavailable", "行情网关返回了未知状态")
        token["last_error"] = None
        self.last_error = None
        self.last_ok = fmt_iso(self._now())
        return payload

    def data(self, tool: str, args: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        payload = self.call(tool, args)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SourceError("gateway_unavailable", "行情网关返回缺少 data")
        return data

    def _now(self):
        from datetime import datetime

        return datetime.now(CN_TZ)

    def _fail(self, tool: str, token: dict[str, Any], error: str) -> None:
        self.failures += 1
        token["failures"] += 1
        token["last_error"] = error
        self.last_error = error

    def health(self, now: Any = None) -> dict[str, Any]:
        return {
            "ok": self.failures == 0 or self.requests > self.failures,
            "requests": self.requests,
            "failures": self.failures,
            "last_error": self.last_error,
            "last_ok": self.last_ok,
            "url": self.base_url,
            "tools": {name: dict(value) for name, value in self._tools.items()},
        }

    def snapshot(self) -> dict[str, Any]:
        return self.health()
