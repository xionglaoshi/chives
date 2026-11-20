from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from helpers import StubClient, tweet, user
from x_mcp.budget import DailyBudget
from x_mcp.client import UpstreamError
from x_mcp.ratelimit import TokenBucket
from x_mcp.redact import Redactor
from x_mcp.service import MAX_DESCRIPTION_CHARS, MAX_TEXT_CHARS, XService

DAY = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)
TOKEN = "AAAA" + "FAKE" + "TOKEN" + "1234567890"


def _service(
    client: StubClient | None,
    local_tmp: Path,
    *,
    limit: int = 500,
    clock: dict[str, datetime] | None = None,
    capacity: int = 100,
) -> tuple[XService, DailyBudget]:
    current = clock if clock is not None else {"now": DAY}
    budget = DailyBudget(limit, local_tmp / "budget.json", now=lambda: current["now"])
    limiter = TokenBucket(capacity, 1.0, clock=lambda: 0.0)
    return XService(client, redactor=Redactor(None), budget=budget, limiter=limiter), budget


def test_search_envelope_and_field_whitelist(local_tmp: Path) -> None:
    client = StubClient(
        search={
            "data": [tweet("1"), tweet("2")],
            "includes": {"users": [user()]},
            "meta": {"result_count": 2, "next_token": "next-1"},
        }
    )
    service, _ = _service(client, local_tmp)
    payload = service.search_recent({"query": "hello", "max_results": 10})
    assert payload["ok"] is True
    assert payload["source"] == "x"
    assert payload["status"] == "ready"
    datetime.fromisoformat(payload["as_of"])
    data = payload["data"]
    assert data["query"] == "hello"
    assert data["count"] == 2
    assert data["untrusted_text"] is True
    assert data["next_token"] == "next-1"
    assert data["budget"] == {"used_today": 2, "remaining": 498}
    assert "unexpected_field" not in data["results"][0]
    assert set(data["results"][0]) <= {
        "id",
        "text",
        "created_at",
        "author_id",
        "public_metrics",
        "lang",
        "conversation_id",
        "entities",
    }
    assert "unexpected_field" not in data["users"][0]
    assert data["users"][0]["username"] == "testuser"


def test_empty_search_is_empty_and_free(local_tmp: Path) -> None:
    client = StubClient(search={"meta": {"result_count": 0}})
    service, budget = _service(client, local_tmp)
    payload = service.search_recent({"query": "nothing", "max_results": 10})
    assert payload["ok"] is True
    assert payload["status"] == "empty"
    assert payload["data"]["count"] == 0
    assert payload["data"]["budget"] == {"used_today": 0, "remaining": 500}
    assert budget.snapshot().used_today == 0


def test_get_post_and_user_envelopes(local_tmp: Path) -> None:
    client = StubClient(post={"data": tweet("9")}, user={"data": user("7")})
    service, _ = _service(client, local_tmp)
    post = service.get_post({"tweet_id": "9"})
    assert post["status"] == "ready"
    assert post["data"]["post"]["id"] == "9"
    assert post["data"]["budget"] == {"used_today": 1, "remaining": 499}
    account = service.get_user({"username": "@testuser"})
    assert account["status"] == "ready"
    assert account["data"]["user"]["id"] == "7"
    assert account["data"]["budget"] == {"used_today": 2, "remaining": 498}
    assert client.user_calls == ["testuser"]


def test_user_posts_envelope_and_budget(local_tmp: Path) -> None:
    client = StubClient(posts={"data": [tweet("1"), tweet("2")], "meta": {"next_token": "n"}})
    service, _ = _service(client, local_tmp)
    payload = service.user_posts({"user_id": "42", "max_results": 5})
    assert payload["status"] == "ready"
    assert payload["data"]["count"] == 2
    assert payload["data"]["user_id"] == "42"
    assert payload["data"]["next_token"] == "n"
    assert payload["data"]["budget"]["used_today"] == 2


def test_counts_envelope(local_tmp: Path) -> None:
    client = StubClient(
        counts={
            "data": [{"start": "2026-11-01T00:00:00Z", "end": "2026-11-02T00:00:00Z", "tweet_count": 4}],
            "meta": {"total_tweet_count": 4},
        }
    )
    service, _ = _service(client, local_tmp)
    payload = service.counts_recent({"query": "q"})
    assert payload["status"] == "ready"
    assert payload["data"]["count"] == 1
    assert payload["data"]["total_tweet_count"] == 4
    assert payload["data"]["buckets"][0]["tweet_count"] == 4
    assert payload["data"]["budget"] == {"used_today": 1, "remaining": 499}


def test_counts_without_meta_uses_the_bucket_sum(local_tmp: Path) -> None:
    client = StubClient(
        counts={"data": [{"start": "a", "end": "b", "tweet_count": 3}, {"start": "c", "end": "d", "tweet_count": 2}]}
    )
    service, _ = _service(client, local_tmp)
    assert service.counts_recent({"query": "q"})["data"]["total_tweet_count"] == 5


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("search_recent", {"query": ""}),
        ("search_recent", {"query": "a", "max_results": 9}),
        ("get_post", {"tweet_id": "abc"}),
        ("get_user", {"username": "bad-name"}),
        ("user_posts", {"user_id": "abc"}),
        ("counts_recent", {"query": "a", "granularity": "week"}),
    ],
)
def test_invalid_arguments_never_reach_the_client_or_the_budget(
    local_tmp: Path, method: str, args: dict
) -> None:
    client = StubClient()
    service, budget = _service(client, local_tmp)
    payload = getattr(service, method)(args)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert payload["data"] == {}
    assert client.search_calls == []
    assert client.post_calls == []
    assert client.user_calls == []
    assert client.posts_calls == []
    assert client.counts_calls == []
    assert budget.snapshot().used_today == 0


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("search_recent", {"query": "q"}),
        ("get_post", {"tweet_id": "1"}),
        ("get_user", {"username": "someone"}),
        ("user_posts", {"user_id": "42"}),
        ("counts_recent", {"query": "q"}),
    ],
)
def test_missing_key_is_reported_for_every_tool(local_tmp: Path, method: str, args: dict) -> None:
    service, _ = _service(None, local_tmp)
    payload = getattr(service, method)(args)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_key"
    assert "scripts/install-keys.py" in payload["error"]["message"]


@pytest.mark.parametrize(
    "code", ["auth_failed", "forbidden", "not_found", "http_error", "network_error", "malformed_response"]
)
def test_upstream_codes_are_passed_through(local_tmp: Path, code: str) -> None:
    client = StubClient(error=UpstreamError(code, "upstream said no"))
    service, budget = _service(client, local_tmp)
    payload = service.search_recent({"query": "q", "max_results": 10})
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == code
    assert payload["data"] == {}
    assert budget.snapshot().used_today == 0


def test_rate_limited_carries_reset_fields_and_does_not_retry(local_tmp: Path) -> None:
    client = StubClient(
        error=UpstreamError(
            "rate_limited",
            "X API rate limit reached",
            status=429,
            reset_at_epoch=1120,
            retry_after_seconds=120,
        )
    )
    service, budget = _service(client, local_tmp)
    payload = service.search_recent({"query": "q", "max_results": 10})
    assert payload["error"]["code"] == "rate_limited"
    assert payload["data"]["reset_at_epoch"] == 1120
    assert payload["data"]["retry_after_seconds"] == 120
    assert len(client.search_calls) == 1
    assert budget.snapshot().used_today == 0


def test_budget_exhausted_blocks_the_call_and_explains_the_reset(local_tmp: Path) -> None:
    client = StubClient(search={"data": [tweet()]})
    service, budget = _service(client, local_tmp, limit=3)
    payload = service.search_recent({"query": "q", "max_results": 10})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "budget_exhausted"
    assert "used 0 of 3" in payload["error"]["message"]
    assert payload["data"]["budget"] == {"used_today": 0, "remaining": 3}
    assert payload["data"]["reset_at"].startswith("2026-11-04T00:00:00")
    assert isinstance(payload["data"]["reset_at_epoch"], int)
    assert client.search_calls == []
    assert budget.snapshot().used_today == 0


def test_budget_exhaustion_after_a_successful_call(local_tmp: Path) -> None:
    client = StubClient(user={"data": user()}, search={"data": [tweet()]})
    service, _ = _service(client, local_tmp, limit=1)
    assert service.get_user({"username": "testuser"})["ok"] is True
    payload = service.search_recent({"query": "q", "max_results": 10})
    assert payload["error"]["code"] == "budget_exhausted"
    assert payload["data"]["budget"] == {"used_today": 1, "remaining": 0}


def test_search_charges_only_the_returned_resources(local_tmp: Path) -> None:
    client = StubClient(search={"data": [tweet("1"), tweet("2")]})
    service, _ = _service(client, local_tmp, limit=10)
    payload = service.search_recent({"query": "q", "max_results": 10})
    assert payload["data"]["budget"] == {"used_today": 2, "remaining": 8}


def test_budget_resets_across_days(local_tmp: Path) -> None:
    clock = {"now": DAY}
    client = StubClient(user={"data": user()})
    service, _ = _service(client, local_tmp, limit=1, clock=clock)
    assert service.get_user({"username": "a"})["ok"] is True
    assert service.get_user({"username": "b"})["error"]["code"] == "budget_exhausted"
    clock["now"] = DAY.replace(day=4)
    second = service.get_user({"username": "c"})
    assert second["ok"] is True
    assert second["data"]["budget"] == {"used_today": 1, "remaining": 0}


def test_failed_calls_refund_the_reservation(local_tmp: Path) -> None:
    client = StubClient(error=UpstreamError("forbidden", "plan does not include it"))
    service, budget = _service(client, local_tmp, limit=5)
    service.get_user({"username": "someone"})
    service.search_recent({"query": "q", "max_results": 10})
    assert budget.snapshot().used_today == 0


def test_echoed_token_is_redacted_in_tool_output(local_tmp: Path) -> None:
    client = StubClient(error=UpstreamError("auth_failed", f"invalid token {TOKEN}"))
    budget = DailyBudget(10, local_tmp / "budget.json", now=lambda: DAY)
    service = XService(
        client,
        redactor=Redactor(TOKEN),
        budget=budget,
        limiter=TokenBucket(100, 1.0, clock=lambda: 0.0),
    )
    payload = service.get_user({"username": "someone"})
    rendered = json.dumps(payload, ensure_ascii=False)
    assert TOKEN not in rendered
    assert TOKEN[:16] not in rendered
    assert "***" in payload["error"]["message"]


@pytest.mark.parametrize(
    ("method", "args", "raw", "code"),
    [
        ("search_recent", {"query": "q"}, {"search": {"errors": [{"title": "Not Found"}]}}, "not_found"),
        (
            "get_post",
            {"tweet_id": "1"},
            {
                "post": {
                    "errors": [
                        {
                            "title": "Authorization Error",
                            "detail": "Not authorized to see this user's posts",
                        }
                    ]
                }
            },
            "forbidden",
        ),
        (
            "get_user",
            {"username": "someone"},
            {"user": {"errors": [{"type": "https://api.twitter.com/2/problems/resource-not-found"}]}},
            "not_found",
        ),
        (
            "user_posts",
            {"user_id": "42"},
            {"posts": {"errors": [{"title": "Forbidden", "detail": "This account is protected"}]}},
            "forbidden",
        ),
        (
            "counts_recent",
            {"query": "q"},
            {"counts": {"errors": [{"title": "Invalid Request"}]}},
            "http_error",
        ),
    ],
)
def test_200_errors_without_data_is_not_an_empty_success(
    local_tmp: Path, method: str, args: dict, raw: dict, code: str
) -> None:
    service, budget = _service(StubClient(**raw), local_tmp)
    payload = getattr(service, method)(args)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == code
    assert payload["data"] == {}
    assert len(payload["error"]["message"]) <= 300
    assert budget.snapshot().used_today == 0


@pytest.mark.parametrize(
    ("method", "args", "raw"),
    [
        (
            "search_recent",
            {"query": "q"},
            {"search": {"data": [tweet("1")], "errors": [{"title": "Partial Error"}]}},
        ),
        (
            "get_post",
            {"tweet_id": "1"},
            {"post": {"data": tweet("1"), "errors": [{"title": "Partial Error"}]}},
        ),
        (
            "get_user",
            {"username": "someone"},
            {"user": {"data": user(), "errors": [{"title": "Partial Error"}]}},
        ),
        (
            "user_posts",
            {"user_id": "42"},
            {"posts": {"data": [tweet("1")], "errors": [{"title": "Partial Error"}]}},
        ),
        (
            "counts_recent",
            {"query": "q"},
            {
                "counts": {
                    "data": [{"start": "a", "end": "b", "tweet_count": 1}],
                    "errors": [{"title": "Partial Error"}],
                }
            },
        ),
    ],
)
def test_200_partial_success_keeps_data_and_reports_warnings(
    local_tmp: Path, method: str, args: dict, raw: dict
) -> None:
    service, _ = _service(StubClient(**raw), local_tmp)
    payload = getattr(service, method)(args)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert len(payload["warnings"]) == 1
    assert "Partial Error" in payload["warnings"][0]
    assert len(payload["warnings"][0]) <= 300


@pytest.mark.parametrize(
    ("method", "args", "code"),
    [
        ("search_recent", {"query": "q"}, "malformed_response"),
        ("get_post", {"tweet_id": "1"}, "malformed_response"),
        ("get_user", {"username": "someone"}, "not_found"),
        ("user_posts", {"user_id": "42"}, "malformed_response"),
        ("counts_recent", {"query": "q"}, "malformed_response"),
    ],
)
def test_bad_upstream_shapes_are_rejected_and_refunded(
    local_tmp: Path, method: str, args: dict, code: str
) -> None:
    client = StubClient(
        search={"data": "oops"},
        post={"nothing": True},
        user={"errors": [{"message": "User not found"}]},
        posts={"data": {"not": "a list"}},
        counts={"data": {"not": "a list"}},
    )
    service, budget = _service(client, local_tmp)
    payload = getattr(service, method)(args)
    assert payload["error"]["code"] == code
    assert budget.snapshot().used_today == 0


def test_deleted_post_maps_to_not_found(local_tmp: Path) -> None:
    client = StubClient(post={"errors": [{"message": "Could not find tweet with id: [1]."}]})
    service, _ = _service(client, local_tmp)
    payload = service.get_post({"tweet_id": "1"})
    assert payload["error"]["code"] == "not_found"


def test_long_text_is_truncated(local_tmp: Path) -> None:
    client = StubClient(
        search={"data": [tweet(text="x" * 5000)]},
        user={"data": user(description="y" * 3000)},
    )
    service, _ = _service(client, local_tmp)
    row = service.search_recent({"query": "q"})["data"]["results"][0]
    assert len(row["text"]) == MAX_TEXT_CHARS
    assert row["truncated"] is True
    account = service.get_user({"username": "someone"})["data"]["user"]
    assert len(account["description"]) == MAX_DESCRIPTION_CHARS
    assert account["truncated"] is True


def test_metrics_drop_booleans_and_non_integers(local_tmp: Path) -> None:
    client = StubClient(
        search={"data": [tweet(public_metrics={"like_count": 2, "flag": True, "text": "x"})]}
    )
    service, _ = _service(client, local_tmp)
    metrics = service.search_recent({"query": "q"})["data"]["results"][0]["public_metrics"]
    assert metrics == {"like_count": 2}


def test_local_rate_limit_does_not_charge_budget(local_tmp: Path) -> None:
    client = StubClient(search={"data": [tweet()]})
    service, budget = _service(client, local_tmp, capacity=1)
    assert service.search_recent({"query": "a"})["ok"] is True
    blocked = service.search_recent({"query": "b"})
    assert blocked["error"]["code"] == "rate_limited"
    assert blocked["data"]["retry_after_seconds"] > 0
    assert len(client.search_calls) == 1
    assert budget.snapshot().used_today == 1


def test_internal_error_envelope_shape(local_tmp: Path) -> None:
    service, _ = _service(StubClient(), local_tmp)
    payload = service.internal_error()
    assert payload["ok"] is False
    assert payload["source"] == "x"
    assert payload["status"] == "error"
    assert payload["data"] == {}
    assert payload["error"]["code"] == "internal_error"


def test_token_echoed_inside_tweet_text_is_redacted(local_tmp: Path) -> None:
    client = StubClient(search={"data": [tweet(text=f"leaked {TOKEN}")]})
    budget = DailyBudget(10, local_tmp / "budget.json", now=lambda: DAY)
    service = XService(
        client,
        redactor=Redactor(TOKEN),
        budget=budget,
        limiter=TokenBucket(100, 1.0, clock=lambda: 0.0),
    )
    payload = service.search_recent({"query": "q"})
    rendered = json.dumps(payload, ensure_ascii=False)
    assert TOKEN not in rendered
    assert TOKEN[:16] not in rendered
    assert "***" in payload["data"]["results"][0]["text"]


def test_token_never_reaches_a_log_record(local_tmp: Path, caplog) -> None:
    client = StubClient(error=UpstreamError("auth_failed", f"invalid token {TOKEN}"))
    budget = DailyBudget(10, local_tmp / "budget.json", now=lambda: DAY)
    service = XService(
        client,
        redactor=Redactor(TOKEN),
        budget=budget,
        limiter=TokenBucket(100, 1.0, clock=lambda: 0.0),
    )
    with caplog.at_level("DEBUG"):
        service.get_user({"username": "someone"})
    assert TOKEN not in caplog.text
