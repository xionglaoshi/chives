"""Runtime configuration: pinned upstream URL, test-mode whitelist and key lookup."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://api.tavily.com"
KEY_NAME = "TAVILY_API_KEY"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SECRETS_PATH = REPO_ROOT / "config" / "secrets.env"


class ConfigError(RuntimeError):
    """Raised before the server starts when the environment is unsafe or malformed."""


def resolve_base_url(env: dict[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    raw = (values.get("TAVILY_BASE_URL") or "").strip()
    if not raw:
        return DEFAULT_BASE_URL
    if values.get("TAVILY_TEST_MODE") != "1":
        raise ConfigError("TAVILY_BASE_URL is only allowed when TAVILY_TEST_MODE=1")
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("TAVILY_BASE_URL has an invalid port") from exc
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ConfigError("TAVILY_BASE_URL in test mode must be http://127.0.0.1:<port>")
    if port is None or port <= 0:
        raise ConfigError("TAVILY_BASE_URL in test mode must include a port")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigError("TAVILY_BASE_URL must not carry credentials, query or fragment")
    if parsed.path not in ("", "/"):
        raise ConfigError("TAVILY_BASE_URL must not carry a path")
    return f"http://127.0.0.1:{port}"


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
