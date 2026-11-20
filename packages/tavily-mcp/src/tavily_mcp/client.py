"""Minimal read-only HTTP client for the Tavily search and extract endpoints."""

from __future__ import annotations

import json
from typing import Any

import requests

from tavily_mcp.redact import Redactor

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 20.0
MAX_ERROR_BODY = 300


class UpstreamError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _status_code(status: int) -> str:
    if status in (401, 403):
        return "unauthorized"
    if status == 429:
        return "rate_limited"
    if status in (432, 433):
        return "plan_limit"
    return "upstream_error"


class TavilyClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = READ_TIMEOUT,
        session: Any | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = (CONNECT_TIMEOUT, timeout)
        self._redactor = redactor or Redactor(api_key)
        if session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        else:
            self._session = session

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._post("/search", params)

    def extract(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._post("/extract", params)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "dsh-tavily-mcp/0.1.0",
        }
        try:
            response = self._session.post(
                self._base_url + path,
                data=body,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout as exc:
            raise UpstreamError("upstream_unreachable", "Tavily request timed out") from exc
        except requests.exceptions.RequestException as exc:
            message = self._redactor.text(f"Tavily request failed ({type(exc).__name__})")
            raise UpstreamError("upstream_unreachable", message) from exc

        status = response.status_code
        text = response.text or ""
        if 200 <= status < 300:
            try:
                data = response.json()
            except ValueError as exc:
                raise UpstreamError("upstream_error", "Tavily returned a non-JSON response") from exc
            if not isinstance(data, dict):
                raise UpstreamError("upstream_error", "Tavily returned an unexpected response shape")
            return data

        detail = " ".join(text.split())[:MAX_ERROR_BODY]
        message = f"Tavily returned HTTP {status}"
        if detail:
            message = f"{message}: {detail}"
        raise UpstreamError(_status_code(status), self._redactor.text(message))
