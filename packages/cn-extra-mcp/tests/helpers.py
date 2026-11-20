"""Shared offline fixtures: tiny frames shaped exactly like the real source."""

from __future__ import annotations

import pandas as pd


def minute_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["day", "open", "high", "low", "close", "volume", "amount"])


TWO_DAY_ROWS = [
    {
        "day": "2026-10-29 09:31:00",
        "open": "10.0",
        "high": "10.1",
        "low": "9.9",
        "close": "10.0",
        "volume": "1000",
        "amount": "10000.0",
    },
    {
        "day": "2026-10-29 15:00:00",
        "open": "10.0",
        "high": "10.2",
        "low": "9.8",
        "close": "10.1",
        "volume": "2000",
        "amount": "20100.0",
    },
    {
        "day": "2026-10-30 09:31:00",
        "open": "11.0",
        "high": "11.5",
        "low": "10.9",
        "close": "11.2",
        "volume": "3000",
        "amount": "33900.0",
    },
    {
        "day": "2026-10-30 15:00:00",
        "open": "11.2",
        "high": "11.3",
        "low": "11.0",
        "close": "11.1",
        "volume": "4000",
        "amount": "44600.0",
    },
]


# Six bars whose summary can be checked by hand:
# volume 2100 shares, amount 21190 CNY, VWAP 10.090476..., close 9.9.
HAND_ROWS = [
    {"day": "2026-01-05 09:31:00", "open": "10.0", "high": "10.2", "low": "9.9", "close": "10.1", "volume": "100", "amount": "1005.0"},
    {"day": "2026-01-05 09:45:00", "open": "10.1", "high": "10.5", "low": "10.0", "close": "10.4", "volume": "200", "amount": "2070.0"},
    {"day": "2026-01-05 10:00:00", "open": "10.4", "high": "10.4", "low": "10.1", "close": "10.2", "volume": "300", "amount": "3075.0"},
    {"day": "2026-01-05 10:01:00", "open": "10.2", "high": "10.3", "low": "10.0", "close": "10.1", "volume": "400", "amount": "4060.0"},
    {"day": "2026-01-05 14:59:00", "open": "10.1", "high": "10.2", "low": "9.9", "close": "10.0", "volume": "500", "amount": "5025.0"},
    {"day": "2026-01-05 15:00:00", "open": "10.0", "high": "10.1", "low": "9.8", "close": "9.9", "volume": "600", "amount": "5955.0"},
]


EMPTY_FRAME = minute_frame([])
