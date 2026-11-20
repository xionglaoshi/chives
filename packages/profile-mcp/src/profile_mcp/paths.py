"""Directory resolution for the profile JSON and the user-global AGENTS.md."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

DEFAULT_HOME_DIRNAME = ".dsh"
PROFILE_FILENAME = "finance-profile.json"
AGENTS_FILENAME = "AGENTS.md"


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


def resolve_agents_home(env: Mapping[str, str] | None = None) -> Path:
    """Directory that holds the user-global AGENTS.md.

    Priority: $DSH_HOME, then $DSH_FINANCE_PROFILE_DIR (so a relocated profile
    never leaks writes into the real home), then ~/.dsh.
    """
    source = _env(env)
    raw = _clean(source.get("DSH_HOME"))
    if raw:
        return _expand(raw, source)
    raw = _clean(source.get("DSH_FINANCE_PROFILE_DIR"))
    if raw:
        return _expand(raw, source)
    home = _clean(source.get("HOME"))
    return (Path(home) if home else Path.home()) / DEFAULT_HOME_DIRNAME


def resolve_profile_dir(env: Mapping[str, str] | None = None) -> Path:
    """Directory that holds finance-profile.json: $DSH_FINANCE_PROFILE_DIR, else the agents home."""
    source = _env(env)
    raw = _clean(source.get("DSH_FINANCE_PROFILE_DIR"))
    if raw:
        return _expand(raw, source)
    home = resolve_agents_home(source)
    profile = home.parent / "profile"
    if home.name == "dsh" and (profile / "investor.json").is_file():
        return profile
    return home


def resolve_agents_path(env: Mapping[str, str] | None = None) -> Path:
    home = resolve_agents_home(env)
    if home.name == "dsh" and (home.parent / "profile/investor.json").is_file():
        return resolve_profile_dir(env) / "finance-profile.md"
    return home / AGENTS_FILENAME


def resolve_profile_path(env: Mapping[str, str] | None = None) -> Path:
    return resolve_profile_dir(env) / PROFILE_FILENAME
