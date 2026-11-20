from __future__ import annotations

import pytest

from tavily_mcp.validation import ValidationError, validate_extract, validate_search

BAD_URLS = [
    "http://127.0.0.1/x",
    "http://localhost/x",
    "http://10.0.0.5/a",
    "http://192.168.1.1/a",
    "http://172.16.0.1/a",
    "http://172.31.255.1/a",
    "http://169.254.169.254/latest",
    "http://[::1]/x",
    "ftp://example.com/a",
    "file:///etc/passwd",
    "http://user:pw@example.com/a",
    "javascript:alert(1)",
    "example.com/no-scheme",
    "http:///nohost",
    "",
    "http://127.1/x",
    "http://0.0.0.0/x",
    "http://[fe80::1]/x",
    "http://example.com/a b",
]


@pytest.mark.parametrize("url", BAD_URLS)
def test_hostile_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_extract({"urls": [url]})


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a",
        "http://sub.domain.co.uk:8080/x?y=1",
        "https://www.cninfo.com.cn/b",
        "http://8.8.8.8/a",
    ],
)
def test_public_urls_are_accepted(url: str) -> None:
    assert validate_extract({"urls": [url]}) == {"urls": [url]}


def test_extract_url_count_boundaries() -> None:
    assert len(validate_extract({"urls": [f"https://example.com/{i}" for i in range(5)]})["urls"]) == 5
    with pytest.raises(ValidationError):
        validate_extract({"urls": []})
    with pytest.raises(ValidationError):
        validate_extract({"urls": [f"https://example.com/{i}" for i in range(6)]})
    with pytest.raises(ValidationError):
        validate_extract({"urls": "https://example.com/a"})
    with pytest.raises(ValidationError):
        validate_extract({})


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": 1},
        {"query": "x" * 401},
        {"query": "a", "max_results": 0},
        {"query": "a", "max_results": 11},
        {"query": "a", "max_results": True},
        {"query": "a", "max_results": "5"},
        {"query": "a", "search_depth": "deep"},
        {"query": "a", "topic": "weather"},
        {"query": "a", "time_range": "decade"},
        {"query": "a", "include_domains": "example.com"},
        {"query": "a", "include_domains": ["not a domain"]},
        {"query": "a", "include_domains": [f"a{i}.com" for i in range(11)]},
        {"query": "a", "exclude_domains": ["bad"]},
        {"query": "a", "exclude_domains": [f"a{i}.com" for i in range(11)]},
    ],
)
def test_invalid_search_arguments(args: dict) -> None:
    with pytest.raises(ValidationError):
        validate_search(args)


def test_search_defaults_and_boundaries() -> None:
    assert validate_search({"query": "a"}) == {
        "query": "a",
        "max_results": 5,
        "search_depth": "basic",
        "topic": "general",
        "time_range": None,
    }
    full = validate_search(
        {
            "query": "x" * 400,
            "max_results": 10,
            "search_depth": "advanced",
            "topic": "finance",
            "time_range": "month",
            "include_domains": ["cninfo.com.cn"],
            "exclude_domains": [f"a{i}.com" for i in range(10)],
        }
    )
    assert full["query"] == "x" * 400
    assert full["include_domains"] == ["cninfo.com.cn"]
    assert len(full["exclude_domains"]) == 10


def test_search_rejects_unknown_shapes() -> None:
    with pytest.raises(ValidationError):
        validate_search("query")
    with pytest.raises(ValidationError):
        validate_search(None)
