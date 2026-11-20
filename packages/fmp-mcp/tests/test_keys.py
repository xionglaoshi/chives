from __future__ import annotations

from pathlib import Path

import pytest

from fmp_mcp import config
from fmp_mcp.client import FmpClient
from fmp_mcp.config import Settings, read_key_file, resolve_api_key, resolve_base_url
from fmp_mcp.tools import TOOLS, dispatch


def test_environment_key_wins_over_file(tmp_path: Path) -> None:
    secrets = tmp_path / "s.env"
    secrets.write_text("FMP_API_KEY=FILEKEY_456\n", encoding="utf-8")
    value, source = resolve_api_key({"FMP_API_KEY": "ENVKEY_789", "DSH_FINANCE_SECRETS": str(secrets)})
    assert (value, source) == ("ENVKEY_789", "environment")


def test_secrets_file_is_parsed(tmp_path: Path) -> None:
    secrets = tmp_path / "s.env"
    secrets.write_text(
        "# comment\nOTHER=1\nexport FMP_API_KEY='FILEKEY_456'\nFMP_API_KEY=IGNORED\n",
        encoding="utf-8",
    )
    assert read_key_file(secrets) == "FILEKEY_456"
    value, source = resolve_api_key({"DSH_FINANCE_SECRETS": str(secrets)})
    assert (value, source) == ("FILEKEY_456", "secrets_file")


def test_explicit_missing_secrets_file_does_not_fall_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    default = tmp_path / "default.env"
    default.write_text("FMP_API_KEY=DEFAULTKEY_000\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_SECRETS_PATH", default)
    value, source = resolve_api_key({"DSH_FINANCE_SECRETS": str(tmp_path / "nope.env")})
    assert value is None and source is None


def test_default_secrets_path_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    default = tmp_path / "default.env"
    default.write_text("FMP_API_KEY=DEFAULTKEY_000\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_SECRETS_PATH", default)
    value, source = resolve_api_key({})
    assert (value, source) == ("DEFAULTKEY_000", "default_secrets_file")


def test_missing_key_still_lists_tools_and_returns_missing_key() -> None:
    from fmp_mcp.server import TOOL_OBJECTS, create_server

    client = FmpClient(Settings(base_url="http://127.0.0.1:9", api_key=None, key_source=None))
    assert len(TOOL_OBJECTS) == 17
    assert create_server(client) is not None
    payload = dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_key"
    assert "FMP_API_KEY" in payload["error"]["message"]


def test_tool_names_are_unique() -> None:
    names = [tool.name for tool in TOOLS]
    assert len(names) == len(set(names)) == 17
