from __future__ import annotations

from pathlib import Path

import pytest

from tavily_mcp.config import (
    DEFAULT_BASE_URL,
    ConfigError,
    resolve_api_key,
    resolve_base_url,
)


def test_default_base_url() -> None:
    assert resolve_base_url({}) == DEFAULT_BASE_URL
    assert resolve_base_url({"TAVILY_BASE_URL": ""}) == DEFAULT_BASE_URL


def test_test_mode_loopback_is_allowed_and_normalized() -> None:
    env = {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "http://127.0.0.1:8865/"}
    assert resolve_base_url(env) == "http://127.0.0.1:8865"


@pytest.mark.parametrize(
    "env",
    [
        {"TAVILY_BASE_URL": "http://127.0.0.1:8865"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "http://10.1.2.3:80"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "http://localhost:8865"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "https://api.tavily.com.evil.com"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "https://127.0.0.1:8865"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "http://127.0.0.1"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "http://127.0.0.1:8865/path"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "http://user:pw@127.0.0.1:8865"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "http://127.0.0.1:99999"},
        {"TAVILY_TEST_MODE": "1", "TAVILY_BASE_URL": "ftp://127.0.0.1:8865"},
    ],
)
def test_base_url_whitelist_rejects(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        resolve_base_url(env)


def _write_env(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_environment_key_wins_over_file(local_tmp: Path) -> None:
    env_file = _write_env(local_tmp / "s.env", "TAVILY_API_KEY=file-key\n")
    env = {"TAVILY_API_KEY": "env-key", "DSH_FINANCE_SECRETS": str(env_file)}
    assert resolve_api_key(env) == "env-key"


def test_dotenv_file_key(local_tmp: Path) -> None:
    env_file = _write_env(
        local_tmp / "s.env",
        "# comment\nexport TAVILY_API_KEY='file-key'\nOTHER=ignored\n",
    )
    env = {"DSH_FINANCE_SECRETS": str(env_file)}
    assert resolve_api_key(env) == "file-key"


def test_default_file_used_only_without_secrets_override(local_tmp: Path) -> None:
    default_file = _write_env(local_tmp / "default.env", 'TAVILY_API_KEY="default-key"\n')
    assert resolve_api_key({}, default_path=default_file) == "default-key"


def test_secrets_override_missing_does_not_fall_back(local_tmp: Path) -> None:
    default_file = _write_env(local_tmp / "default.env", "TAVILY_API_KEY=default-key\n")
    env = {"DSH_FINANCE_SECRETS": str(local_tmp / "missing.env")}
    assert resolve_api_key(env, default_path=default_file) is None


def test_only_tavily_key_is_read(local_tmp: Path) -> None:
    env_file = _write_env(
        local_tmp / "s.env",
        "OTHER_API_KEY=other-value\nTAVILY_API_KEY=tavily-value\n",
    )
    assert resolve_api_key({"DSH_FINANCE_SECRETS": str(env_file)}) == "tavily-value"


def test_missing_key_is_none(local_tmp: Path) -> None:
    env_file = _write_env(local_tmp / "s.env", "OTHER=value\n")
    assert resolve_api_key({"DSH_FINANCE_SECRETS": str(env_file)}) is None


def test_inline_comment_is_stripped(local_tmp: Path) -> None:
    env_file = _write_env(local_tmp / "s.env", "TAVILY_API_KEY=file-key # a comment\n")
    assert resolve_api_key({"DSH_FINANCE_SECRETS": str(env_file)}) == "file-key"
