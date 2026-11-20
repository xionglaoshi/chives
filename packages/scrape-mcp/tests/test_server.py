from __future__ import annotations

import asyncio
import json

import mcp.types as types
import pytest

from scrape_mcp.config import ConfigError, Settings, load_settings
from scrape_mcp.server import TOOLS, build_service, create_server, load_server_settings


def test_exactly_two_tools() -> None:
    assert [tool.name for tool in TOOLS] == ["scrape_page", "scrape_pages"]


def test_tool_schemas() -> None:
    page = next(tool for tool in TOOLS if tool.name == "scrape_page")
    pages = next(tool for tool in TOOLS if tool.name == "scrape_pages")
    assert page.inputSchema["required"] == ["url"]
    assert pages.inputSchema["required"] == ["urls"]
    assert pages.inputSchema["properties"]["urls"]["items"] == {"type": "string"}
    assert "mode" in page.inputSchema["properties"]
    assert "extraction" in page.inputSchema["properties"]
    assert "timeout" in page.inputSchema["properties"]


def test_settings_from_environment() -> None:
    settings = load_server_settings(
        {
            "SCRAPE_CHROME_PATH": "/opt/chrome",
            "SCRAPE_ALLOW_HOSTS": "example.com, api.example.org",
            "SCRAPE_TEST_ALLOW_LOOPBACK": "1",
            "SCRAPE_MIN_INTERVAL_SECONDS": "0",
            "SCRAPE_MAX_REQUESTS_PER_MINUTE": "30",
        }
    ).scrape
    assert not hasattr(settings, "chrome_path")
    assert settings.allow_hosts == ("example.com", "api.example.org")
    assert settings.allow_loopback is True
    assert settings.min_interval_seconds == 0.0
    assert settings.requests_per_minute == 30
    assert settings.user_agent.startswith("dsh-finance-scrape/")


def test_settings_reject_bad_values() -> None:
    for env in (
        {"SCRAPE_ALLOW_HOSTS": "http://example.com"},
        {"SCRAPE_MIN_INTERVAL_SECONDS": "soon"},
        {"SCRAPE_MIN_INTERVAL_SECONDS": "-1"},
        {"SCRAPE_MAX_REQUESTS_PER_MINUTE": "0"},
        {"SCRAPE_MAX_REQUESTS_PER_MINUTE": "many"},
    ):
        with pytest.raises(ConfigError):
            load_settings(env)


def test_unknown_values_fall_back_to_defaults() -> None:
    settings = load_settings({})
    assert settings.allow_hosts == ()
    assert settings.allow_loopback is False
    assert settings.min_interval_seconds == 1.0


def _call(server, name: str, arguments: dict) -> dict:
    handler = server.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=arguments),
    )
    result = asyncio.run(handler(request))
    content = result.root.content
    assert len(content) == 1
    return json.loads(content[0].text)


def test_server_returns_json_envelope(settings: Settings, site) -> None:
    server = create_server(build_service(settings))
    payload = _call(server, "scrape_page", {"url": site.url("/article")})
    assert payload["ok"] is True
    assert payload["source"] == "scrape"
    assert payload["status"] == "ready"


def test_server_rejects_stealth_mode(settings: Settings, site) -> None:
    server = create_server(build_service(settings))
    payload = _call(server, "scrape_page", {"url": site.url("/article"), "mode": "stealth"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"


def test_server_unknown_tool_is_an_error_envelope(settings: Settings) -> None:
    server = create_server(build_service(settings))
    payload = _call(server, "scrape_everything", {})
    assert payload["ok"] is False
    assert payload["status"] == "error"
