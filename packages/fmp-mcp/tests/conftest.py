from __future__ import annotations

import pytest

from fmp_mcp.client import FmpClient
from fmp_mcp.config import Settings
from fake_upstream import FakeFmp

TEST_KEY = "TESTKEY_123456"


@pytest.fixture
def fake() -> FakeFmp:
    server = FakeFmp()
    yield server
    server.stop()


@pytest.fixture
def settings(fake: FakeFmp) -> Settings:
    return Settings(base_url=f"http://127.0.0.1:{fake.port}", api_key=TEST_KEY, key_source="test")


@pytest.fixture
def client(settings: Settings) -> FmpClient:
    return FmpClient(settings, timeout=2.0)
