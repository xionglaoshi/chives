"""Minimal loopback, GET-only HTTP client for the market-watch engine."""

from __future__ import annotations

import json
from typing import Any

import requests

JSON_HEADERS = {"accept": "application/json"}
MAX_BYTES = 512 * 1024


class EngineClientError(Exception):
    """Base class for failures that become an error envelope, never a protocol error."""


class EngineUnreachable(EngineClientError):
    """Connection failed or the engine did not answer within the timeout."""


class EngineHTTPError(EngineClientError):
    """The engine answered with a non-2xx status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class EngineResponseError(EngineClientError):
    """The engine answered 2xx but the body was not a JSON object."""


class ResponseTooLarge(EngineClientError):
    """The body exceeded the size cap."""


class MarketClient:
    """Loopback-only client. Redirects are not followed and environment proxies are ignored."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.trust_env = False

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._session.get(
                f"{self.base_url}{path}",
                params=params,
                headers=JSON_HEADERS,
                timeout=self.timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise EngineUnreachable(
                f"cannot reach market-watch engine: {type(exc).__name__}"
            ) from exc
        try:
            if not 200 <= response.status_code < 300:
                raise EngineHTTPError(
                    response.status_code,
                    f"market-watch engine returned HTTP {response.status_code}",
                )
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_BYTES:
                raise ResponseTooLarge("market-watch engine response exceeds 512KB")
            chunks: list[bytes] = []
            total = 0
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ResponseTooLarge("market-watch engine response exceeds 512KB")
                    chunks.append(chunk)
            except requests.RequestException as exc:
                raise EngineUnreachable(
                    f"cannot read market-watch engine response: {type(exc).__name__}"
                ) from exc
        finally:
            response.close()
        try:
            payload = json.loads(b"".join(chunks).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise EngineResponseError("market-watch engine returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise EngineResponseError("market-watch engine returned a non-object JSON body")
        return payload

    def close(self) -> None:
        self._session.close()
