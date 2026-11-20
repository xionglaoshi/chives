from __future__ import annotations

import json

import pytest
import requests

from helpers import FakeResponse, FakeSession
from tavily_mcp.client import TavilyClient, UpstreamError
from tavily_mcp.redact import Redactor

KEY = "tvly-test-key"


def _client(session: FakeSession, key: str = KEY) -> TavilyClient:
    return TavilyClient("https://api.tavily.com", key, session=session, redactor=Redactor(key))


def test_key_is_only_in_the_authorization_header() -> None:
    session = FakeSession([FakeResponse(200, {"results": []})])
    _client(session).search({"query": "hello", "max_results": 3})
    call = session.calls[0]
    assert call["url"] == "https://api.tavily.com/search"
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert KEY not in call["url"]
    body = call["data"].decode("utf-8")
    assert KEY not in body
    assert "Authorization" not in body
    assert call["allow_redirects"] is False


def test_extract_key_is_only_in_the_authorization_header() -> None:
    session = FakeSession([FakeResponse(200, {"results": []})])
    _client(session).extract({"urls": ["https://example.com/a"]})
    call = session.calls[0]
    assert call["url"] == "https://api.tavily.com/extract"
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert KEY not in call["data"].decode("utf-8")


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "unauthorized"), (403, "unauthorized"), (429, "rate_limited"), (432, "plan_limit"), (433, "plan_limit"), (500, "upstream_error"), (404, "upstream_error")],
)
def test_status_mapping(status: int, code: str) -> None:
    session = FakeSession([FakeResponse(status, text="upstream says no")])
    with pytest.raises(UpstreamError) as info:
        _client(session).search({"query": "x"})
    assert info.value.code == code


def test_redirects_are_not_followed() -> None:
    session = FakeSession([FakeResponse(302, text="")])
    with pytest.raises(UpstreamError) as info:
        _client(session).search({"query": "x"})
    assert info.value.code == "upstream_error"
    assert session.calls[0]["allow_redirects"] is False


def test_timeout_maps_to_unreachable() -> None:
    session = FakeSession(error=requests.exceptions.ReadTimeout("slow"))
    with pytest.raises(UpstreamError) as info:
        _client(session).search({"query": "x"})
    assert info.value.code == "upstream_unreachable"


def test_connection_error_maps_to_unreachable() -> None:
    session = FakeSession(error=requests.exceptions.ConnectionError("down"))
    with pytest.raises(UpstreamError) as info:
        _client(session).extract({"urls": ["https://example.com/a"]})
    assert info.value.code == "upstream_unreachable"


def test_non_json_success_is_upstream_error() -> None:
    session = FakeSession([FakeResponse(200, payload=None, text="not json")])
    with pytest.raises(UpstreamError) as info:
        _client(session).search({"query": "x"})
    assert info.value.code == "upstream_error"


def test_echoed_bearer_token_is_redacted_in_the_exception() -> None:
    body = json.dumps({"detail": f"invalid API key {KEY}"})
    session = FakeSession([FakeResponse(401, text=body)])
    with pytest.raises(UpstreamError) as info:
        _client(session).search({"query": "BADKEY"})
    message = str(info.value)
    assert KEY not in message
    assert "***" in message
    assert info.value.code == "unauthorized"
