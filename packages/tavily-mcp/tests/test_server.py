from __future__ import annotations

from pathlib import Path

from tavily_mcp.server import TOOLS, Settings, build_service, load_settings


def test_exactly_two_read_only_tools() -> None:
    names = [tool.name for tool in TOOLS]
    assert names == ["tavily_search", "tavily_extract"]
    search = next(tool for tool in TOOLS if tool.name == "tavily_search")
    extract = next(tool for tool in TOOLS if tool.name == "tavily_extract")
    assert search.inputSchema["required"] == ["query"]
    assert extract.inputSchema["required"] == ["urls"]
    assert extract.inputSchema["properties"]["urls"]["maxItems"] == 5


def test_missing_key_still_builds_a_working_server(local_tmp: Path) -> None:
    settings = load_settings({"DSH_FINANCE_SECRETS": str(local_tmp / "none.env")})
    assert settings.api_key is None
    assert settings.base_url == "https://api.tavily.com"
    service = build_service(settings)
    payload = service.search({"query": "q"})
    assert payload["error"]["code"] == "missing_key"


def test_key_from_explicit_dotenv_is_used(local_tmp: Path) -> None:
    env_file = local_tmp / "s.env"
    env_file.write_text("TAVILY_API_KEY=file-key\n", encoding="utf-8")
    settings = load_settings({"DSH_FINANCE_SECRETS": str(env_file)})
    assert settings.api_key == "file-key"
    assert settings.base_url == "https://api.tavily.com"


def test_settings_are_immutable() -> None:
    settings = Settings("https://api.tavily.com", None)
    try:
        settings.api_key = "changed"  # type: ignore[misc]
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("Settings should be frozen")
