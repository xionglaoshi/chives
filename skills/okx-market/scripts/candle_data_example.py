#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX K 线示例（可选脚本，需要本机安装 Python 3 与 requests）。

本文件只读取公开行情接口，不需要 API Key，也不包含任何下单/转账逻辑。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

BASE_URL = "https://www.okx.com/api/v5"

CANDLE_COLUMNS = ("ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm")
INDEX_CANDLE_COLUMNS = ("ts", "open", "high", "low", "close", "confirm")


def _get(path: str, params: dict[str, str]) -> list[list[str]]:
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX error {payload.get('code')}: {payload.get('msg')}")
    return payload["data"]


def get_candles(inst_id: str, bar: str = "1D", limit: int = 100) -> list[dict[str, Any]]:
    """返回按时间升序排列的 K 线；limit 最大 300。"""
    rows = _get("/market/candles", {"instId": inst_id, "bar": bar, "limit": str(min(limit, 300))})
    candles = [dict(zip(CANDLE_COLUMNS, row)) for row in rows]
    for candle in candles:
        candle["ts"] = datetime.fromtimestamp(int(candle["ts"]) / 1000, tz=timezone.utc)
        for key in ("open", "high", "low", "close", "vol"):
            candle[key] = float(candle[key])
    candles.sort(key=lambda c: c["ts"])
    return candles


def get_index_candles(inst_id: str, bar: str = "1D", limit: int = 100) -> list[dict[str, Any]]:
    """返回按时间升序排列的指数 K 线；limit 最大 100。"""
    rows = _get("/market/index-candles", {"instId": inst_id, "bar": bar, "limit": str(min(limit, 100))})
    candles = [dict(zip(INDEX_CANDLE_COLUMNS, row)) for row in rows]
    for candle in candles:
        candle["ts"] = datetime.fromtimestamp(int(candle["ts"]) / 1000, tz=timezone.utc)
        for key in ("open", "high", "low", "close"):
            candle[key] = float(candle[key])
    candles.sort(key=lambda c: c["ts"])
    return candles


def main() -> None:
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    print(f"===== OKX K 线示例（as_of={as_of}） =====\n")

    print("--- BTC-USDT 日线（最近 10 根） ---")
    for candle in get_candles("BTC-USDT", "1D", 10):
        print(f"  {candle['ts']:%Y-%m-%d}  close={candle['close']:<12g} vol={candle['vol']:.4f}")

    print("\n--- ETH-USDT 4 小时线（最近 10 根） ---")
    for candle in get_candles("ETH-USDT", "4H", 10):
        print(f"  {candle['ts']:%Y-%m-%dT%H:%MZ}  close={candle['close']:<12g} vol={candle['vol']:.4f}")

    print("\n--- BTC-USD 指数日线（最近 10 根） ---")
    for candle in get_index_candles("BTC-USD", "1D", 10):
        print(f"  {candle['ts']:%Y-%m-%d}  close={candle['close']:<12g} confirm={candle['confirm']}")


if __name__ == "__main__":
    main()
