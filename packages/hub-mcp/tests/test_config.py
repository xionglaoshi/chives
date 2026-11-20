from __future__ import annotations

import pytest

from hub_mcp.config import DEFAULT_HUB_URL, resolve_base_url, validate_base_url
from hub_mcp.errors import HubConfigError


def test_default_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHIVES_HUB_URL", raising=False)
    assert resolve_base_url() == DEFAULT_HUB_URL


def test_default_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIVES_HUB_URL", "   ")
    assert resolve_base_url() == DEFAULT_HUB_URL


def test_explicit_loopback() -> None:
    assert validate_base_url("http://127.0.0.1:8867") == "http://127.0.0.1:8867"


def test_localhost_and_trailing_slash() -> None:
    assert validate_base_url("http://localhost:8867/") == "http://localhost:8867"


def test_ipv6_loopback_is_normalized() -> None:
    assert validate_base_url("http://[::1]:8867") == "http://[::1]:8867"


def test_https_loopback_allowed() -> None:
    assert validate_base_url("https://127.0.0.1:8867") == "https://127.0.0.1:8867"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:8867",
        "http://192.168.1.2:8867",
        "http://127.0.0.1.evil.com:8867",
        "http://localhost.evil.com:8867",
        "http://0.0.0.0:8867",
    ],
)
def test_non_loopback_rejected(url: str) -> None:
    with pytest.raises(HubConfigError):
        validate_base_url(url)


def test_credentials_rejected() -> None:
    with pytest.raises(HubConfigError):
        validate_base_url("http://user:pass@127.0.0.1:8867")


def test_path_rejected() -> None:
    with pytest.raises(HubConfigError):
        validate_base_url("http://127.0.0.1:8867/api")


def test_query_and_fragment_rejected() -> None:
    with pytest.raises(HubConfigError):
        validate_base_url("http://127.0.0.1:8867?x=1")
    with pytest.raises(HubConfigError):
        validate_base_url("http://127.0.0.1:8867#x")


def test_bad_scheme_rejected() -> None:
    with pytest.raises(HubConfigError):
        validate_base_url("ftp://127.0.0.1:8867")


def test_bad_port_rejected() -> None:
    with pytest.raises(HubConfigError):
        validate_base_url("http://127.0.0.1:99999")


def test_empty_rejected() -> None:
    with pytest.raises(HubConfigError):
        validate_base_url("")


def test_malformed_ipv6_rejected() -> None:
    with pytest.raises(HubConfigError):
        validate_base_url("http://[::1:8867")
