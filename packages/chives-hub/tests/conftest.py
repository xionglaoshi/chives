from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a test resolve the real ~/.dsh or touch the public network."""
    guard = Path(tempfile.mkdtemp(prefix="chives-hub-env-"))
    monkeypatch.setenv("HOME", str(guard))
    for name in (
        "DSH_HOME",
        "DSH_FINANCE_PROFILE_DIR",
        "CHIVES_HUB_TEST_MODE",
        "CHIVES_HUB_CN_WATCH_BASE",
        "CHIVES_HUB_MARKET_WATCH_BASE",
        "CHIVES_HUB_TENCENT_BASE",
        "CHIVES_HUB_IFZQ_BASE",
        "CHIVES_HUB_IFZQ_FALLBACK_BASE",
        "PORTFOLIO_TEST_MODE",
        "PORTFOLIO_QUOTE_BASE",
        "PORTFOLIO_KLINE_BASE",
    ):
        monkeypatch.delenv(name, raising=False)
    try:
        yield
    finally:
        shutil.rmtree(guard, ignore_errors=True)


@pytest.fixture
def tmpdir_path(tmp_path: Path) -> Path:
    return tmp_path
