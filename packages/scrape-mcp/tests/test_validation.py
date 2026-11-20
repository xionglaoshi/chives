from __future__ import annotations

import pytest

from scrape_mcp.validation import ValidationError, validate_page_args, validate_pages_args


def test_defaults() -> None:
    params = validate_page_args({"url": "https://example.com/"})
    assert params == {
        "url": "https://example.com/",
        "mode": "fast",
        "extraction": "markdown",
        "timeout": 30.0,
    }


def test_explicit_values() -> None:
    params = validate_page_args(
        {
            "url": "https://example.com/",
            "mode": "BROWSER",
            "extraction": "TEXT",
            "timeout": 5,
        }
    )
    assert params["mode"] == "browser"
    assert params["extraction"] == "text"
    assert params["timeout"] == 5.0


@pytest.mark.parametrize("mode", ["stealth", "solve_cloudflare"])
def test_stealth_modes_are_rejected(mode: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_page_args({"url": "https://example.com/", "mode": mode})
    assert excinfo.value.code == "invalid_argument"
    assert "not supported" in str(excinfo.value)


@pytest.mark.parametrize("key", ["stealth", "solve_cloudflare"])
def test_stealth_flags_are_rejected(key: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_page_args({"url": "https://example.com/", key: True})
    assert excinfo.value.code == "invalid_argument"
    with pytest.raises(ValidationError):
        validate_pages_args({"urls": ["https://example.com/"], key: True})


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"url": ""},
        {"url": 42},
        {"url": "https://example.com/", "mode": "headless"},
        {"url": "https://example.com/", "extraction": "pdf"},
        {"url": "https://example.com/", "timeout": 0},
        {"url": "https://example.com/", "timeout": 61},
        {"url": "https://example.com/", "timeout": True},
        {"url": "https://example.com/", "timeout": "30"},
        [],
    ],
)
def test_invalid_page_arguments(args: object) -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_page_args(args)
    assert excinfo.value.code == "invalid_argument"


def test_pages_arguments() -> None:
    params = validate_pages_args({"urls": ["https://a.example/", "https://b.example/"]})
    assert params["urls"] == ["https://a.example/", "https://b.example/"]
    assert params["mode"] == "fast"


@pytest.mark.parametrize(
    "urls",
    [[], "https://example.com/", [""], [1], ["u"] * 11],
)
def test_invalid_pages_arguments(urls: object) -> None:
    with pytest.raises(ValidationError):
        validate_pages_args({"urls": urls})
