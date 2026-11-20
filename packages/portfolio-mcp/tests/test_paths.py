from __future__ import annotations

from pathlib import Path

from portfolio_mcp.paths import resolve_home_dir, resolve_portfolio_dir, resolve_portfolio_path


def test_profile_dir_wins(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "DSH_HOME": "/ignored", "DSH_FINANCE_PROFILE_DIR": str(tmp_path / "p")}
    assert resolve_portfolio_dir(env) == tmp_path / "p"


def test_home_fallback(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "DSH_HOME": str(tmp_path / "h")}
    assert resolve_portfolio_dir(env) == tmp_path / "h"
    assert resolve_home_dir(env) == tmp_path / "h"


def test_default_is_home_dot_dsh(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path)}
    assert resolve_portfolio_dir(env) == tmp_path / ".dsh"
    assert resolve_portfolio_path(env).name == "finance-portfolio.json"


def test_tilde_expands_against_given_home(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "DSH_FINANCE_PROFILE_DIR": "~/prof"}
    assert resolve_portfolio_dir(env) == tmp_path / "prof"


def test_no_env_reads_real_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DSH_HOME", raising=False)
    monkeypatch.delenv("DSH_FINANCE_PROFILE_DIR", raising=False)
    assert resolve_portfolio_dir() == tmp_path / ".dsh"
