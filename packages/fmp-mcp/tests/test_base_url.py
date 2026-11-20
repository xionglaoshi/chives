from __future__ import annotations

import pytest

from fmp_mcp.config import ConfigError, PRODUCTION_BASE_URL, resolve_base_url


def test_default_is_production() -> None:
    assert resolve_base_url({}) == PRODUCTION_BASE_URL


def test_loopback_override_is_allowed_in_test_mode() -> None:
    assert resolve_base_url({"FMP_TEST_MODE": "1", "FMP_BASE_URL": "http://127.0.0.1:8123"}) == "http://127.0.0.1:8123"
    assert resolve_base_url({"FMP_TEST_MODE": "1", "FMP_BASE_URL": "http://localhost:8123/"}) == "http://127.0.0.1:8123"


@pytest.mark.parametrize(
    "env",
    [
        {"FMP_BASE_URL": "http://127.0.0.1:9"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "http://10.1.2.3:80"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "https://financialmodelingprep.com.evil.com"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "https://financialmodelingprep.com"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "http://127.0.0.1"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "http://127.0.0.1:9/stable"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "http://user:pass@127.0.0.1:9"},
        {"FMP_TEST_MODE": "0", "FMP_BASE_URL": "http://127.0.0.1:9"},
    ],
)
def test_disallowed_base_urls_raise(env: dict) -> None:
    with pytest.raises(ConfigError):
        resolve_base_url(env)
