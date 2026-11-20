"""Directory resolution for the local portfolio JSON.

Priority matches profile-mcp: $DSH_FINANCE_PROFILE_DIR, then $DSH_HOME, then ~/.dsh.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

DEFAULT_HOME_DIRNAME = ".dsh"
PORTFOLIO_FILENAME = "finance-portfolio.json"


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _expand(raw: str, env: Mapping[str, str]) -> Path:
    """Expand a leading ~ against the given env, so tests never read the real home."""
    if raw == "~":
        return Path(env.get("HOME") or Path.home())
    if raw.startswith("~/"):
        return Path(env.get("HOME") or Path.home()) / raw[2:]
    return Path(raw)


def resolve_home_dir(env: Mapping[str, str] | None = None) -> Path:
    """Directory that holds the portfolio when no profile dir is configured."""
    source = _env(env)
    raw = _clean(source.get("DSH_HOME"))
    if raw:
        return _expand(raw, source)
    home = _clean(source.get("HOME"))
    return (Path(home) if home else Path.home()) / DEFAULT_HOME_DIRNAME


def resolve_portfolio_dir(env: Mapping[str, str] | None = None) -> Path:
    """Directory that holds finance-portfolio.json: $DSH_FINANCE_PROFILE_DIR, else the home dir."""
    source = _env(env)
    raw = _clean(source.get("DSH_FINANCE_PROFILE_DIR"))
    if raw:
        return _expand(raw, source)
    home = resolve_home_dir(source)
    profile = home.parent / "profile"
    if home.name == "dsh" and (profile / "investor.json").is_file():
        return profile
    return home


def resolve_portfolio_path(env: Mapping[str, str] | None = None) -> Path:
    return resolve_portfolio_dir(env) / PORTFOLIO_FILENAME
