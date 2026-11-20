from __future__ import annotations

from pathlib import Path

import pytest

from x_mcp.config import (
    DEFAULT_BASE_URL,
    DEFAULT_DAILY_BUDGET,
    DEFAULT_STATE_PATH,
    ConfigError,
    resolve_api_key,
    resolve_base_url,
    resolve_daily_budget,
    resolve_rate_limits,
    resolve_state_path,
)


def test_default_base_url() -> None:
    assert resolve_base_url({}) == DEFAULT_BASE_URL
    assert resolve_base_url({"X_BASE_URL": ""}) == DEFAULT_BASE_URL


def test_explicit_production_url_is_accepted() -> None:
    assert resolve_base_url({"X_BASE_URL": "https://api.x.com/"}) == DEFAULT_BASE_URL


def test_test_mode_loopback_is_allowed_and_normalized() -> None:
    env = {"X_TEST_MODE": "1", "X_BASE_URL": "http://127.0.0.1:8865/"}
    assert resolve_base_url(env) == "http://127.0.0.1:8865"
    alias = {"X_TEST_MODE": "1", "X_API_BASE_URL": "http://127.0.0.1:8866"}
    assert resolve_base_url(alias) == "http://127.0.0.1:8866"


@pytest.mark.parametrize(
    "env",
    [
        {"X_BASE_URL": "http://127.0.0.1:8865"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "http://10.1.2.3:80"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "http://localhost:8865"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "https://api.x.com.evil.com"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "https://127.0.0.1:8865"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "http://127.0.0.1"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "http://127.0.0.1:8865/path"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "http://user:pw@127.0.0.1:8865"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "http://127.0.0.1:99999"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "ftp://127.0.0.1:8865"},
        {"X_TEST_MODE": "1", "X_BASE_URL": "http://127.0.0.1:8865?x=1"},
    ],
)
def test_base_url_whitelist_rejects(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        resolve_base_url(env)


def test_daily_budget_default_and_override() -> None:
    assert resolve_daily_budget({}) == DEFAULT_DAILY_BUDGET
    assert resolve_daily_budget({"X_DAILY_POST_BUDGET": "0"}) == 0
    assert resolve_daily_budget({"X_DAILY_POST_BUDGET": "42"}) == 42


@pytest.mark.parametrize("raw", ["-1", "abc", "1.5", " 1 2 "])
def test_daily_budget_rejects_invalid(raw: str) -> None:
    with pytest.raises(ConfigError):
        resolve_daily_budget({"X_DAILY_POST_BUDGET": raw})


def test_state_path_defaults_inside_the_repo() -> None:
    assert resolve_state_path({}) == DEFAULT_STATE_PATH
    assert DEFAULT_STATE_PATH.is_absolute()


def test_state_path_explicit_forms(local_tmp: Path) -> None:
    explicit = local_tmp / "b.json"
    assert resolve_state_path({"X_BUDGET_STATE": str(explicit)}) == explicit
    assert resolve_state_path({"X_BUDGET_STATE_FILE": str(explicit)}) == explicit
    assert resolve_state_path({"X_STATE_FILE": str(explicit)}) == explicit
    assert resolve_state_path({"X_STATE_DIR": str(local_tmp)}) == local_tmp / "budget.json"


def test_state_path_relative_stays_in_repo() -> None:
    resolved = resolve_state_path({"X_BUDGET_STATE": "runtime/x/b.json"})
    assert resolved.is_absolute()
    assert resolved.name == "b.json"


def test_rate_limits_default_and_override() -> None:
    assert resolve_rate_limits({}) == (30, 30.0)
    assert resolve_rate_limits({"X_RATE_CAPACITY": "5", "X_RATE_REFILL_SECONDS": "2.5"}) == (5, 2.5)
    with pytest.raises(ConfigError):
        resolve_rate_limits({"X_RATE_CAPACITY": "0"})
    with pytest.raises(ConfigError):
        resolve_rate_limits({"X_RATE_REFILL_SECONDS": "-1"})


def _write_env(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_environment_key_wins_over_file(local_tmp: Path) -> None:
    env_file = _write_env(local_tmp / "s.env", "X_BEARER_TOKEN=file-key\n")
    env = {"X_BEARER_TOKEN": "env-key", "DSH_FINANCE_SECRETS": str(env_file)}
    assert resolve_api_key(env) == "env-key"


def test_dotenv_file_key(local_tmp: Path) -> None:
    env_file = _write_env(
        local_tmp / "s.env",
        "# comment\nexport X_BEARER_TOKEN='file-key'\nOTHER=ignored\n",
    )
    assert resolve_api_key({"DSH_FINANCE_SECRETS": str(env_file)}) == "file-key"


def test_default_file_used_only_without_secrets_override(local_tmp: Path) -> None:
    default_file = _write_env(local_tmp / "default.env", 'X_BEARER_TOKEN="default-key"\n')
    assert resolve_api_key({}, default_path=default_file) == "default-key"


def test_secrets_override_missing_does_not_fall_back(local_tmp: Path) -> None:
    default_file = _write_env(local_tmp / "default.env", "X_BEARER_TOKEN=default-key\n")
    env = {"DSH_FINANCE_SECRETS": str(local_tmp / "missing.env")}
    assert resolve_api_key(env, default_path=default_file) is None


def test_only_x_token_is_read(local_tmp: Path) -> None:
    env_file = _write_env(
        local_tmp / "s.env",
        "TAVILY_API_KEY=tavily-value\nX_BEARER_TOKEN=x-value\n",
    )
    assert resolve_api_key({"DSH_FINANCE_SECRETS": str(env_file)}) == "x-value"


def test_missing_key_is_none(local_tmp: Path) -> None:
    env_file = _write_env(local_tmp / "s.env", "OTHER=value\n")
    assert resolve_api_key({"DSH_FINANCE_SECRETS": str(env_file)}) is None


def test_inline_comment_is_stripped(local_tmp: Path) -> None:
    env_file = _write_env(local_tmp / "s.env", "X_BEARER_TOKEN=file-key # a comment\n")
    assert resolve_api_key({"DSH_FINANCE_SECRETS": str(env_file)}) == "file-key"


def test_state_path_follows_dsh_finance_home(local_tmp: Path) -> None:
    assert resolve_state_path({"DSH_FINANCE_HOME": str(local_tmp)}) == local_tmp / "x-mcp" / "budget.json"
