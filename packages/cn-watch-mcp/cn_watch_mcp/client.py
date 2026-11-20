"""Minimal loopback HTTP client for the cn-watch engine."""

from __future__ import annotations

from typing import Any

import requests

JSON_HEADERS = {"accept": "application/json"}
WATCHLIST_ERROR_CODES = {
    "invalid_symbol",
    "unsupported_market",
    "quote_unavailable",
    "watchlist_full",
    "protected_symbol",
    "persistence_error",
}


class EngineClientError(Exception):
    """Base class for failures that become an error envelope, never a protocol error."""


class EngineUnreachable(EngineClientError):
    """Connection failed or the engine did not answer within the timeout."""


class EngineHTTPError(EngineClientError):
    """The engine answered with a non-2xx status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class EngineAPIError(EngineClientError):
    """The engine rejected a write with a stable error code and Chinese message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class EngineResponseError(EngineClientError):
    """The engine answered 2xx but the body was not a JSON object."""


class WatchClient:
    """Loopback-only client. Redirects are not followed and environment proxies are ignored."""

    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.trust_env = False

    def get_json(
        self,
        path: str,
        params: dict[str, int] | None = None,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", path, params=params, actor=actor)

    def post_json(
        self, path: str, payload: dict[str, Any], *, actor: str | None = None
    ) -> dict[str, Any]:
        return self._request("POST", path, json_body=payload, actor=actor)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, int] | None = None,
        json_body: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        headers = dict(JSON_HEADERS)
        if actor:
            headers["X-Actor"] = actor
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise EngineUnreachable(f"cannot reach cn-watch engine: {type(exc).__name__}") from exc
        if not 200 <= response.status_code < 300:
            code, message = self._error_detail(response)
            if code is not None:
                raise EngineAPIError(response.status_code, code, message or code)
            raise EngineHTTPError(
                response.status_code,
                f"cn-watch engine returned HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EngineResponseError("cn-watch engine returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise EngineResponseError("cn-watch engine returned a non-object JSON body")
        if payload.get("ok") is False:
            code, message = self._payload_error(payload)
            if code is not None:
                raise EngineAPIError(response.status_code, code, message or code)
        return payload

    @staticmethod
    def _error_detail(response: requests.Response) -> tuple[str | None, str | None]:
        try:
            payload = response.json()
        except ValueError:
            return None, None
        if not isinstance(payload, dict):
            return None, None
        return WatchClient._payload_error(payload)

    @staticmethod
    def _payload_error(payload: dict[str, Any]) -> tuple[str | None, str | None]:
        raw_code = payload.get("code")
        message = payload.get("message")
        raw_error = payload.get("error")
        if isinstance(raw_error, dict):
            if not isinstance(raw_code, str) or not raw_code:
                raw_code = raw_error.get("code")
            if not isinstance(message, str) or not message.strip():
                nested = raw_error.get("message")
                message = nested if isinstance(nested, str) else None
        elif isinstance(raw_error, str) and raw_error in WATCHLIST_ERROR_CODES:
            if not isinstance(raw_code, str) or not raw_code:
                raw_code = raw_error
        code = raw_code if isinstance(raw_code, str) and raw_code else None
        if not isinstance(message, str) or not message.strip():
            fallback = raw_error if isinstance(raw_error, str) else None
            message = fallback if fallback and fallback not in WATCHLIST_ERROR_CODES else None
        return code, message

    def close(self) -> None:
        self._session.close()
