"""Opt-in live test. Ran only with ``pytest -m network``; one gateway round."""

from __future__ import annotations

from datetime import datetime

import pytest

from chives_radar.models import CN_TZ
from chives_radar.sources import GatewaySource


@pytest.mark.network
def test_live_gateway_snapshot():
    source = GatewaySource("http://127.0.0.1:8868", timeout=8.0)
    quotes = source.fetch(
        ["600519.SH", "000001.SZ", "300750.SZ", "601318.SH", "512880.SH"],
        datetime.now(CN_TZ),
    )
    assert quotes
    for quote in quotes.values():
        assert quote.price > 0
        assert quote.prev_close > 0
        assert quote.exch_time.tzinfo is not None
