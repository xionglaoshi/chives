"""Minimal read-only HTTP client for the five X API v2 endpoints."""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

from x_mcp.redact import Redactor

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 20.0
MAX_ERROR_BODY = 300

TWEET_FIELDS = "created_at,author_id,public_metrics,lang,conversation_id,entities"
USER_FIELDS = "id,name,username,created_at,description,public_metrics,verified"
EXPANSIONS = "author_id"


class UpstreamError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        reset_at_epoch: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.reset_at_epoch = reset_at_epoch
        self.retry_after_seconds = retry_after_seconds


NOT_FOUND_MARKERS = ("not found", "could not find", "resource-not-found")
FORBIDDEN_MARKERS = ("authorization", "forbidden", "not authorized", "not-authorized", "protected")

ERROR_MESSAGES = {
    "not_found": (
        "X API returned HTTP 200 but the requested resource was not found "
        "(it may be deleted or unavailable)"
    ),
    "forbidden": (
        "X API returned HTTP 200 but access was denied: the account may be protected "
        "or you may not have permission to view it"
    ),
    "http_error": "X API returned HTTP 200 without data but with an errors payload",
}


def _status_code(status: int) -> str:
    if status == 401:
        return "auth_failed"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    return "http_error"


def error_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    errors = raw.get("errors")
    if not isinstance(errors, list):
        return []
    return [item for item in errors if isinstance(item, dict)]


def has_data(raw: dict[str, Any]) -> bool:
    if "data" not in raw:
        return False
    data = raw.get("data")
    if isinstance(data, (list, dict, str)):
        return bool(data)
    return data is not None


def _error_text(item: dict[str, Any]) -> str:
    parts = [
        value.strip()
        for key in ("title", "type", "detail", "message")
        if isinstance((value := item.get(key)), str) and value.strip()
    ]
    return ": ".join(parts)


def error_summary(errors: list[dict[str, Any]], *, limit: int = MAX_ERROR_BODY) -> str:
    texts = [text for text in (_error_text(item) for item in errors[:3]) if text]
    return " ".join("; ".join(texts).split())[:limit]


def classify_errors(errors: list[dict[str, Any]]) -> str:
    blob = " ".join(_error_text(item) for item in errors).lower()
    if any(marker in blob for marker in NOT_FOUND_MARKERS):
        return "not_found"
    if any(marker in blob for marker in FORBIDDEN_MARKERS):
        return "forbidden"
    return "http_error"


def error_message(errors: list[dict[str, Any]]) -> str:
    message = ERROR_MESSAGES[classify_errors(errors)]
    summary = error_summary(errors)
    if summary:
        message = f"{message}: {summary}"
    return " ".join(message.split())[:MAX_ERROR_BODY]


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None) or {}
    for key, value in headers.items():
        if str(key).lower() == name:
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            return None if value is None else str(value).strip()
    return None


def _header_int(response: Any, name: str) -> int | None:
    raw = _header(response, name)
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


class XClient:
    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        *,
        timeout: float = READ_TIMEOUT,
        session: Any | None = None,
        redactor: Redactor | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = bearer_token
        self._timeout = (CONNECT_TIMEOUT, timeout)
        self._redactor = redactor or Redactor(bearer_token)
        self._clock = clock
        if session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        else:
            self._session = session

    def search_recent(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._get(
            "/2/tweets/search/recent",
            {
                "query": params["query"],
                "max_results": params["max_results"],
                "next_token": params.get("next_token"),
                "start_time": params.get("start_time"),
                "end_time": params.get("end_time"),
                "tweet.fields": TWEET_FIELDS,
                "user.fields": USER_FIELDS,
                "expansions": EXPANSIONS,
            },
        )

    def get_post(self, tweet_id: str) -> dict[str, Any]:
        return self._get(
            f"/2/tweets/{tweet_id}",
            {
                "tweet.fields": TWEET_FIELDS,
                "user.fields": USER_FIELDS,
                "expansions": EXPANSIONS,
            },
        )

    def get_user(self, username: str) -> dict[str, Any]:
        return self._get(f"/2/users/by/username/{username}", {"user.fields": USER_FIELDS})

    def user_posts(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._get(
            f"/2/users/{params['user_id']}/tweets",
            {
                "max_results": params["max_results"],
                "pagination_token": params.get("pagination_token"),
                "tweet.fields": TWEET_FIELDS,
                "user.fields": USER_FIELDS,
                "expansions": EXPANSIONS,
            },
        )

    def counts_recent(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._get(
            "/2/tweets/counts/recent",
            {"query": params["query"], "granularity": params["granularity"]},
        )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {key: value for key, value in params.items() if value is not None}
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "dsh-x-mcp/0.1.0",
        }
        try:
            response = self._session.get(
                self._base_url + path,
                params=query,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout as exc:
            raise UpstreamError("network_error", "X request timed out") from exc
        except requests.exceptions.RequestException as exc:
            message = self._redactor.text(f"X request failed ({type(exc).__name__})")
            raise UpstreamError("network_error", message) from exc

        status = response.status_code
        text = response.text or ""
        if 200 <= status < 300:
            try:
                data = response.json()
            except ValueError as exc:
                raise UpstreamError(
                    "malformed_response", "X returned a non-JSON response", status=status
                ) from exc
            if not isinstance(data, dict):
                raise UpstreamError(
                    "malformed_response", "X returned an unexpected response shape", status=status
                )
            errors = error_items(data)
            if errors and not has_data(data):
                raise UpstreamError(
                    classify_errors(errors),
                    self._redactor.text(error_message(errors)),
                    status=status,
                )
            return data

        detail = " ".join(text.split())[:MAX_ERROR_BODY]
        if status == 429:
            reset = _header_int(response, "x-rate-limit-reset")
            retry = _header_int(response, "retry-after")
            if retry is None and reset is not None:
                retry = max(0, reset - int(self._clock()))
            if reset is None and retry is not None:
                reset = int(self._clock()) + retry
            message = "X API rate limit reached; the tool does not retry automatically"
            if retry is not None:
                message = f"{message}; retry after {retry} seconds"
            if reset is not None:
                message = f"{message} (reset at epoch {reset})"
            if detail:
                message = f"{message}: {detail}"
            raise UpstreamError(
                "rate_limited",
                self._redactor.text(message),
                status=status,
                reset_at_epoch=reset,
                retry_after_seconds=retry,
            )

        message = f"X API returned HTTP {status}"
        if status == 401:
            message = "X API rejected the bearer token (HTTP 401)"
        elif status == 403:
            message = (
                "X API returned HTTP 403: this endpoint may not be included in your X API plan; "
                "check your plan in the Developer Console"
            )
        elif status == 404:
            message = "X API returned HTTP 404: the requested resource was not found"
        if detail:
            message = f"{message}: {detail}"
        raise UpstreamError(_status_code(status), self._redactor.text(message), status=status)
