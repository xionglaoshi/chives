from __future__ import annotations

from pathlib import Path

import pytest

from profile_mcp.paths import (
    resolve_agents_home,
    resolve_agents_path,
    resolve_profile_dir,
    resolve_profile_path,
)


def test_default_is_dot_dsh_under_home(monkeypatch: pytest.MonkeyPatch, local_tmp: Path) -> None:
    monkeypatch.setenv("HOME", str(local_tmp))
    env = {"HOME": str(local_tmp)}
    assert resolve_agents_home(env) == local_tmp / ".dsh"
    assert resolve_profile_dir(env) == local_tmp / ".dsh"
    assert resolve_profile_path(env) == local_tmp / ".dsh" / "finance-profile.json"
    assert resolve_agents_path(env) == local_tmp / ".dsh" / "AGENTS.md"


def test_dsh_home_wins_over_default(local_tmp: Path) -> None:
    env = {"DSH_HOME": str(local_tmp / "dsh")}
    assert resolve_profile_dir(env) == local_tmp / "dsh"
    assert resolve_agents_home(env) == local_tmp / "dsh"


def test_profile_dir_wins_for_profile_but_not_for_agents(local_tmp: Path) -> None:
    env = {
        "DSH_HOME": str(local_tmp / "dsh"),
        "DSH_FINANCE_PROFILE_DIR": str(local_tmp / "profile"),
    }
    assert resolve_profile_dir(env) == local_tmp / "profile"
    assert resolve_agents_path(env) == local_tmp / "dsh" / "AGENTS.md"


def test_profile_dir_alone_keeps_agents_file_with_the_profile(local_tmp: Path) -> None:
    env = {"DSH_FINANCE_PROFILE_DIR": str(local_tmp / "profile"), "HOME": str(local_tmp / "home")}
    assert resolve_profile_dir(env) == local_tmp / "profile"
    assert resolve_agents_home(env) == local_tmp / "profile"


def test_blank_values_are_ignored(local_tmp: Path) -> None:
    env = {"DSH_HOME": "  ", "DSH_FINANCE_PROFILE_DIR": "", "HOME": str(local_tmp)}
    assert resolve_profile_dir(env) == local_tmp / ".dsh"


def test_home_expansion(local_tmp: Path) -> None:
    env = {"DSH_HOME": "~/custom-dsh", "HOME": str(local_tmp)}
    assert resolve_agents_home(env) == local_tmp / "custom-dsh"


def test_reads_process_environment(monkeypatch: pytest.MonkeyPatch, local_tmp: Path) -> None:
    monkeypatch.setenv("DSH_HOME", str(local_tmp / "env-home"))
    assert resolve_agents_path() == local_tmp / "env-home" / "AGENTS.md"
