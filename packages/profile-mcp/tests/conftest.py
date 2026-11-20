from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from profile_mcp.service import ProfileService
from profile_mcp.store import ProfileStore

TESTS_DIR = Path(__file__).resolve().parent


def _temp_dir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=TESTS_DIR))


@pytest.fixture
def local_tmp() -> Path:
    """A temporary directory inside the package (never the real home or another repo)."""
    path = _temp_dir("_tmp_")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee no test can resolve to the real ~/.dsh, even by accident."""
    guard = _temp_dir("_env_")
    monkeypatch.setenv("HOME", str(guard))
    monkeypatch.delenv("DSH_HOME", raising=False)
    monkeypatch.delenv("DSH_FINANCE_PROFILE_DIR", raising=False)
    try:
        yield
    finally:
        shutil.rmtree(guard, ignore_errors=True)


@pytest.fixture
def home(local_tmp: Path) -> Path:
    path = local_tmp / "home"
    path.mkdir()
    return path


@pytest.fixture
def store(home: Path) -> ProfileStore:
    return ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md")


@pytest.fixture
def service(store: ProfileStore) -> ProfileService:
    return ProfileService(store)
