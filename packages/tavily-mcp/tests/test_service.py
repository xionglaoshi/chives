from __future__ import annotations

import json
from datetime import datetime

from helpers import StubClient
from tavily_mcp.cache import TTLCache
from tavily_mcp.client import UpstreamError
from tavily_mcp.ratelimit import SlidingWindowLimiter
from tavily_mcp.redact import Redactor
from tavily_mcp.service import MAX_CONTENT_CHARS, TavilyService


def _service(client, **kwargs) -> TavilyService:
    return TavilyService(client, redactor=Redactor(None), **kwargs)


def test_search_envelope_and_truncation() -> None:
    client = StubClient(
        search_raw={
            "results": [
                {
                    "title": "Long",
                    "url": "https://example.com/1",
                    "content": "详" * 2500,
                    "score": 0.9,
                    "published_date": "2026-11-02",
                },
                {"title": "Short", "url": "https://example.com/2", "content": "short", "score": 0.5},
            ]
        }
    )
    payload = _service(client).search({"query": "q", "max_results": 2})
    assert payload["ok"] is True
    assert payload["source"] == "tavily"
    assert payload["status"] == "ready"
    datetime.fromisoformat(payload["as_of"])
    data = payload["data"]
    assert data["query"] == "q"
    assert data["count"] == 2
    assert data["untrusted_text"] is True
    assert data["results"][0]["title"] == "Long"
    assert data["results"][0]["url"] == "https://example.com/1"
    assert data["results"][0]["published_date"] == "2026-11-02"
    assert len(data["results"][0]["content"]) == MAX_CONTENT_CHARS
    assert data["results"][0]["truncated"] is True
    assert data["results"][1]["content"] == "short"
    assert "truncated" not in data["results"][1]
    assert data["results"][1]["published_date"] is None


def test_content_exactly_at_limit_is_not_truncated() -> None:
    client = StubClient(search_raw={"results": [{"content": "x" * MAX_CONTENT_CHARS}]})
    data = _service(client).search({"query": "q"})["data"]
    assert len(data["results"][0]["content"]) == MAX_CONTENT_CHARS
    assert "truncated" not in data["results"][0]


def test_empty_search_is_ok_but_not_cached() -> None:
    client = StubClient(search_raw={"results": []})
    service = _service(client)
    first = service.search({"query": "NORESULT"})
    second = service.search({"query": "NORESULT"})
    assert first["ok"] is True and first["status"] == "empty"
    assert first["data"]["count"] == 0
    assert first["data"]["untrusted_text"] is True
    assert second["status"] == "empty"
    assert len(client.search_calls) == 2


def test_extract_envelope_truncation_and_failed() -> None:
    client = StubClient(
        extract_raw={
            "results": [
                {"url": "https://example.com/a", "raw_content": "z" * 2500},
                {"url": "https://example.com/b", "content": "short"},
            ],
            "failed_results": [
                {"url": "https://bad.example/x", "error": "timeout"},
                "boom",
            ],
        }
    )
    payload = _service(client).extract({"urls": ["https://example.com/a", "https://example.com/b"]})
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    data = payload["data"]
    assert data["count"] == 2
    assert data["untrusted_text"] is True
    assert data["results"][0]["url"] == "https://example.com/a"
    assert len(data["results"][0]["content"]) == MAX_CONTENT_CHARS
    assert data["results"][0]["truncated"] is True
    assert data["results"][1]["content"] == "short"
    assert data["failed"][0] == {"url": "https://bad.example/x", "error": "timeout"}
    assert data["failed"][1]["error"] == "boom"


def test_empty_extract_is_empty() -> None:
    client = StubClient(extract_raw={"results": [], "failed_results": []})
    payload = _service(client).extract({"urls": ["https://example.com/a"]})
    assert payload["status"] == "empty"
    assert payload["data"]["count"] == 0
    assert payload["data"]["failed"] == []


def test_identical_search_is_cached() -> None:
    client = StubClient(search_raw={"results": [{"title": "t", "content": "c"}]})
    service = _service(client)
    first = service.search({"query": "cache me", "max_results": 3})
    second = service.search({"query": "cache me", "max_results": 3})
    assert len(client.search_calls) == 1
    assert first["data"] == second["data"]


def test_different_arguments_are_not_shared_in_cache() -> None:
    client = StubClient(search_raw={"results": [{"title": "t", "content": "c"}]})
    service = _service(client)
    service.search({"query": "a"})
    service.search({"query": "b"})
    assert len(client.search_calls) == 2


def test_errors_are_not_cached() -> None:
    client = StubClient(error=UpstreamError("unauthorized", "bad key"))
    service = _service(client)
    first = service.search({"query": "q"})
    second = service.search({"query": "q"})
    assert first["ok"] is False and first["error"]["code"] == "unauthorized"
    assert second["ok"] is False
    assert len(client.search_calls) == 2


def test_cache_expires_after_ttl() -> None:
    now = [0.0]
    cache = TTLCache(300.0, clock=lambda: now[0])
    client = StubClient(search_raw={"results": [{"title": "t", "content": "c"}]})
    service = _service(client, cache=cache, limiter=SlidingWindowLimiter(clock=lambda: now[0]))
    service.search({"query": "q"})
    now[0] = 299.0
    service.search({"query": "q"})
    assert len(client.search_calls) == 1
    now[0] = 300.5
    service.search({"query": "q"})
    assert len(client.search_calls) == 2


def test_rate_limit_blocks_the_twenty_first_upstream_call() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 60.0, clock=lambda: now[0])
    client = StubClient(search_raw={"results": [{"title": "t", "content": "c"}]})
    service = _service(client, limiter=limiter, cache=TTLCache(clock=lambda: now[0]))
    assert service.search({"query": "a"})["ok"] is True
    assert service.search({"query": "b"})["ok"] is True
    blocked = service.search({"query": "c"})
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "rate_limited"
    assert len(client.search_calls) == 2
    now[0] = 61.0
    assert service.search({"query": "d"})["ok"] is True


def test_invalid_arguments_never_reach_the_client() -> None:
    client = StubClient()
    service = _service(client)
    payload = service.search({"query": ""})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert payload["data"] == {}
    assert client.search_calls == []

    payload = service.extract({"urls": ["http://127.0.0.1/x"]})
    assert payload["error"]["code"] == "invalid_argument"
    assert client.extract_calls == []


def test_missing_key_server_can_still_answer() -> None:
    service = TavilyService(None, redactor=Redactor(None))
    payload = service.search({"query": "q"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_key"
    assert "scripts/install-keys.py" in payload["error"]["message"]


def test_echoed_key_is_redacted_in_the_tool_output() -> None:
    key = "tvly-echo-key"
    client = StubClient(error=UpstreamError("unauthorized", f"invalid API key {key}"))
    service = TavilyService(client, redactor=Redactor(key))
    for payload in (service.search({"query": "BADKEY"}), service.extract({"urls": ["https://example.com/a"]})):
        rendered = json.dumps(payload, ensure_ascii=False)
        assert key not in rendered
        assert "***" in payload["error"]["message"]


def test_upstream_error_envelope_shape() -> None:
    client = StubClient(error=UpstreamError("plan_limit", "quota done"))
    payload = _service(client).search({"query": "PLAN"})
    assert payload["ok"] is False
    assert payload["source"] == "tavily"
    assert payload["status"] == "error"
    assert payload["data"] == {}
    assert payload["error"] == {"code": "plan_limit", "message": "quota done"}
