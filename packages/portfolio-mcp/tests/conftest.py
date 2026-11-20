from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from portfolio_mcp.service import PortfolioService
from portfolio_mcp.store import PortfolioStore

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
    for name in (
        "DSH_HOME",
        "DSH_FINANCE_PROFILE_DIR",
        "PORTFOLIO_GATEWAY_URL",
    ):
        monkeypatch.delenv(name, raising=False)
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
def store(home: Path) -> PortfolioStore:
    return PortfolioStore(profile_dir=home)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(store: PortfolioStore, clock: FakeClock) -> PortfolioService:
    # quotes=None keeps every unit test offline; valuation tests inject a fake client.
    return PortfolioService(store, quotes=None, clock=clock)
