from __future__ import annotations

import json

import pytest
import requests

from helpers import FakeResponse, FakeSession
from x_mcp.client import (
    EXPANSIONS,
    TWEET_FIELDS,
    USER_FIELDS,
    UpstreamError,
    XClient,
)
from x_mcp.redact import Redactor

TOKEN = "AAAA" + "FAKE" + "TOKEN" + "1234567890"


def _client(session: FakeSession, token: str = TOKEN, clock=lambda: 1000.0) -> XClient:
    return XClient(
        "https://api.x.com",
        token,
        session=session,
        redactor=Redactor(token),
        clock=clock,
    )


def _call_tool(client: XClient, tool: str):
    if tool == "search":
        return client.search_recent({"query": "q", "max_results": 10})
    if tool == "post":
        return client.get_post("1")
    if tool == "user":
        return client.get_user("someone")
    if tool == "posts":
        return client.user_posts({"user_id": "42", "max_results": 5})
    return client.counts_recent({"query": "q", "granularity": "day"})


def test_search_uses_the_recent_endpoint_and_key_lives_only_in_the_header() -> None:
    session = FakeSession([FakeResponse(200, {"data": []})])
    _client(session).search_recent({"query": "hello", "max_results": 10})
    call = session.calls[0]
    assert call["url"] == "https://api.x.com/2/tweets/search/recent"
    assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in call["url"]
    assert TOKEN not in json.dumps(call["params"])
    assert "Authorization" not in json.dumps(call["params"])
    assert call["allow_redirects"] is False
    assert call["params"]["tweet.fields"] == TWEET_FIELDS
    assert call["params"]["user.fields"] == USER_FIELDS
    assert call["params"]["expansions"] == EXPANSIONS


def test_each_tool_targets_the_documented_endpoint() -> None:
    session = FakeSession([FakeResponse(200, {"data": {}}) for _ in range(4)])
    client = _client(session)
    client.get_post("123")
    client.get_user("someone")
    client.user_posts({"user_id": "42", "max_results": 5, "pagination_token": "abc"})
    client.counts_recent({"query": "q", "granularity": "day"})
    assert session.calls[0]["url"] == "https://api.x.com/2/tweets/123"
    assert session.calls[1]["url"] == "https://api.x.com/2/users/by/username/someone"
    assert session.calls[2]["url"] == "https://api.x.com/2/users/42/tweets"
    assert session.calls[3]["url"] == "https://api.x.com/2/tweets/counts/recent"
    assert "query" not in session.calls[0]["params"]
    assert session.calls[2]["params"]["pagination_token"] == "abc"
    assert session.calls[3]["params"] == {"query": "q", "granularity": "day"}


def test_optional_parameters_are_dropped_when_none() -> None:
    session = FakeSession([FakeResponse(200, {"data": []})])
    _client(session).search_recent(
        {"query": "q", "max_results": 10, "next_token": None, "start_time": None, "end_time": None}
    )
    params = session.calls[0]["params"]
    assert "next_token" not in params
    assert "start_time" not in params
    assert "end_time" not in params


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "auth_failed"),
        (403, "forbidden"),
        (404, "not_found"),
        (429, "rate_limited"),
        (500, "http_error"),
        (302, "http_error"),
        (400, "http_error"),
    ],
)
def test_status_mapping(status: int, code: str) -> None:
    session = FakeSession([FakeResponse(status, text="upstream says no")])
    with pytest.raises(UpstreamError) as info:
        _client(session).search_recent({"query": "x", "max_results": 10})
    assert info.value.code == code
    assert info.value.status == status


def test_forbidden_explains_the_developer_console() -> None:
    session = FakeSession([FakeResponse(403, text="not in plan")])
    with pytest.raises(UpstreamError) as info:
        _client(session).counts_recent({"query": "q", "granularity": "day"})
    assert "Developer Console" in str(info.value)


def test_rate_limit_parses_reset_header() -> None:
    session = FakeSession(
        [FakeResponse(429, text="slow down", headers={"x-rate-limit-reset": "1120"})]
    )
    with pytest.raises(UpstreamError) as info:
        _client(session, clock=lambda: 1000.0).search_recent({"query": "q", "max_results": 10})
    assert info.value.code == "rate_limited"
    assert info.value.reset_at_epoch == 1120
    assert info.value.retry_after_seconds == 120


def test_rate_limit_falls_back_to_retry_after() -> None:
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "30"})])
    with pytest.raises(UpstreamError) as info:
        _client(session, clock=lambda: 1000.0).search_recent({"query": "q", "max_results": 10})
    assert info.value.retry_after_seconds == 30
    assert info.value.reset_at_epoch == 1030


def test_rate_limit_without_headers_still_maps() -> None:
    session = FakeSession([FakeResponse(429)])
    with pytest.raises(UpstreamError) as info:
        _client(session).search_recent({"query": "q", "max_results": 10})
    assert info.value.code == "rate_limited"
    assert info.value.reset_at_epoch is None
    assert info.value.retry_after_seconds is None


def test_rate_limited_calls_are_not_retried() -> None:
    session = FakeSession([FakeResponse(429), FakeResponse(200, {"data": []})])
    with pytest.raises(UpstreamError):
        _client(session).search_recent({"query": "q", "max_results": 10})
    assert len(session.calls) == 1


def test_redirects_are_not_followed() -> None:
    session = FakeSession([FakeResponse(301, text="", headers={"Location": "https://evil.example"})])
    with pytest.raises(UpstreamError) as info:
        _client(session).search_recent({"query": "x", "max_results": 10})
    assert info.value.code == "http_error"
    assert session.calls[0]["allow_redirects"] is False
    assert session.calls[0]["url"] == "https://api.x.com/2/tweets/search/recent"


def test_timeout_maps_to_network_error() -> None:
    session = FakeSession(error=requests.exceptions.ReadTimeout("slow"))
    with pytest.raises(UpstreamError) as info:
        _client(session).get_user("someone")
    assert info.value.code == "network_error"


def test_connection_error_maps_to_network_error() -> None:
    session = FakeSession(error=requests.exceptions.ConnectionError("down"))
    with pytest.raises(UpstreamError) as info:
        _client(session).get_post("1")
    assert info.value.code == "network_error"


def test_non_json_success_is_malformed_response() -> None:
    session = FakeSession([FakeResponse(200, payload=None, text="not json")])
    with pytest.raises(UpstreamError) as info:
        _client(session).get_post("1")
    assert info.value.code == "malformed_response"


def test_json_list_success_is_malformed_response() -> None:
    session = FakeSession([FakeResponse(200, payload=[1, 2, 3])])
    with pytest.raises(UpstreamError) as info:
        _client(session).get_user("someone")
    assert info.value.code == "malformed_response"


@pytest.mark.parametrize(
    ("tool", "body", "code"),
    [
        ("search", {"errors": [{"title": "Not Found"}]}, "not_found"),
        (
            "post",
            {"errors": [{"type": "https://api.twitter.com/2/problems/resource-not-found"}]},
            "not_found",
        ),
        (
            "user",
            {
                "errors": [
                    {
                        "title": "Authorization Error",
                        "detail": "Not authorized to see this user's posts",
                    }
                ]
            },
            "forbidden",
        ),
        (
            "posts",
            {"errors": [{"title": "Forbidden", "detail": "This account is protected"}]},
            "forbidden",
        ),
        (
            "counts",
            {"errors": [{"type": "https://api.twitter.com/2/problems/not-authorized-for-resource"}]},
            "forbidden",
        ),
        ("search", {"data": [], "errors": [{"title": "Invalid Request"}]}, "http_error"),
        ("posts", {"data": [], "errors": [{"title": "Not Found"}]}, "not_found"),
        (
            "post",
            {"errors": [{"type": "https://api.twitter.com/2/problems/invalid-request"}]},
            "http_error",
        ),
        ("user", {"errors": [{"title": "Authorization Error"}]}, "forbidden"),
        (
            "counts",
            {"errors": [{"title": "Not Found", "type": "about:blank/resource-not-found"}]},
            "not_found",
        ),
    ],
)
def test_200_with_errors_and_no_data_is_an_error(tool: str, body: dict, code: str) -> None:
    session = FakeSession([FakeResponse(200, body)])
    with pytest.raises(UpstreamError) as info:
        _call_tool(_client(session), tool)
    assert info.value.code == code
    assert info.value.status == 200
    assert len(str(info.value)) <= 300


def test_200_error_message_is_redacted_and_explains_forbidden() -> None:
    body = {
        "errors": [
            {
                "title": "Authorization Error",
                "detail": f"Not authorized; token {TOKEN} " + "x" * 1000,
            }
        ]
    }
    session = FakeSession([FakeResponse(200, body)])
    with pytest.raises(UpstreamError) as info:
        _client(session).get_user("someone")
    message = str(info.value)
    assert info.value.code == "forbidden"
    assert TOKEN not in message
    assert "protected" in message or "permission" in message
    assert len(message) <= 300


def test_200_with_data_and_errors_is_returned_as_partial_success() -> None:
    body = {"data": [{"id": "1"}], "errors": [{"title": "Partial Error", "detail": "one post unavailable"}]}
    session = FakeSession([FakeResponse(200, body)])
    result = _call_tool(_client(session), "search")
    assert result["data"] == [{"id": "1"}]
    assert result["errors"] == [{"title": "Partial Error", "detail": "one post unavailable"}]


def test_200_empty_result_without_errors_is_not_an_error() -> None:
    session = FakeSession([FakeResponse(200, {"meta": {"result_count": 0}})])
    assert _call_tool(_client(session), "search") == {"meta": {"result_count": 0}}


def test_echoed_bearer_token_is_redacted_in_the_exception() -> None:
    body = json.dumps({"detail": f"invalid token {TOKEN}", "header": f"Bearer {TOKEN}"})
    session = FakeSession([FakeResponse(401, text=body)])
    with pytest.raises(UpstreamError) as info:
        _client(session).search_recent({"query": "q", "max_results": 10})
    message = str(info.value)
    assert TOKEN not in message
    assert "***" in message
    assert info.value.code == "auth_failed"


def test_error_body_is_bounded() -> None:
    session = FakeSession([FakeResponse(500, text="x" * 5000)])
    with pytest.raises(UpstreamError) as info:
        _client(session).get_user("someone")
    assert len(str(info.value)) < 500
