"""Runtime configuration: pinned upstream URL, test-mode whitelist, key lookup and budget settings."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://api.x.com"
KEY_NAME = "X_BEARER_TOKEN"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SECRETS_PATH = REPO_ROOT / "config" / "secrets.env"
DEFAULT_STATE_PATH = REPO_ROOT / "runtime" / "x-mcp" / "budget.json"
DEFAULT_DAILY_BUDGET = 500
DEFAULT_RATE_CAPACITY = 30
DEFAULT_RATE_REFILL_SECONDS = 30.0


class ConfigError(RuntimeError):
    """Raised before the server starts when the environment is unsafe or malformed."""


def _first(values: dict[str, str], *names: str) -> str:
    for name in names:
        raw = (values.get(name) or "").strip()
        if raw:
            return raw
    return ""


def resolve_base_url(env: dict[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    raw = _first(values, "X_BASE_URL", "X_API_BASE_URL")
    if not raw or raw.rstrip("/") == DEFAULT_BASE_URL:
        return DEFAULT_BASE_URL
    if values.get("X_TEST_MODE") != "1":
        raise ConfigError("X_BASE_URL is only allowed when X_TEST_MODE=1")
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("X_BASE_URL has an invalid port") from exc
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ConfigError("X_BASE_URL in test mode must be http://127.0.0.1:<port>")
    if port is None or port <= 0:
        raise ConfigError("X_BASE_URL in test mode must include a port")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigError("X_BASE_URL must not carry credentials, query or fragment")
    if parsed.path not in ("", "/"):
        raise ConfigError("X_BASE_URL must not carry a path")
    return f"http://127.0.0.1:{port}"


def resolve_daily_budget(env: dict[str, str] | None = None) -> int:
    values = os.environ if env is None else env
    raw = (values.get("X_DAILY_POST_BUDGET") or "").strip()
    if not raw:
        return DEFAULT_DAILY_BUDGET
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise ConfigError("X_DAILY_POST_BUDGET must be a non-negative integer") from exc
    if value < 0:
        raise ConfigError("X_DAILY_POST_BUDGET must be a non-negative integer")
    return value


def resolve_state_path(env: dict[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    explicit = _first(values, "X_BUDGET_STATE", "X_BUDGET_STATE_FILE", "X_STATE_FILE")
    if explicit:
        path = Path(explicit).expanduser()
    else:
        state_dir = _first(values, "X_STATE_DIR")
        home = _first(values, "DSH_FINANCE_HOME")
        if state_dir:
            path = Path(state_dir).expanduser() / "budget.json"
        elif home:
            path = Path(home).expanduser() / "x-mcp" / "budget.json"
        else:
            path = DEFAULT_STATE_PATH
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _positive_float(values: dict[str, str], name: str, default: float) -> float:
    raw = (values.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be a positive number")
    return value


def resolve_rate_limits(env: dict[str, str] | None = None) -> tuple[int, float]:
    values = os.environ if env is None else env
    raw = (values.get("X_RATE_CAPACITY") or "").strip()
    if raw:
        try:
            capacity = int(raw, 10)
        except ValueError as exc:
            raise ConfigError("X_RATE_CAPACITY must be a positive integer") from exc
        if capacity <= 0:
            raise ConfigError("X_RATE_CAPACITY must be a positive integer")
    else:
        capacity = DEFAULT_RATE_CAPACITY
    return capacity, _positive_float(values, "X_RATE_REFILL_SECONDS", DEFAULT_RATE_REFILL_SECONDS)


def _parse_dotenv(path: Path, name: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[len("export ") :].strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        return value or None
    return None


def resolve_api_key(
    env: dict[str, str] | None = None,
    *,
    default_path: Path | None = None,
) -> str | None:
    values = os.environ if env is None else env
    direct = (values.get(KEY_NAME) or "").strip()
    if direct:
        return direct
    secrets_file = values.get("DSH_FINANCE_SECRETS")
    if secrets_file:
        return _parse_dotenv(Path(secrets_file), KEY_NAME)
    return _parse_dotenv(default_path or DEFAULT_SECRETS_PATH, KEY_NAME)
