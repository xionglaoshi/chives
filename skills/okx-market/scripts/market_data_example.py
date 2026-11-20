#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX 公开行情示例（可选脚本，需要本机安装 Python 3 与 requests）。

本文件只读取公开行情接口，不需要 API Key，也不包含任何下单/转账逻辑。
默认用法下优先使用 skill 正文里的 web_fetch；脚本适合本地批量拉取。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

BASE_URL = "https://www.okx.com/api/v5"
YEAR_MS = 365 * 24 * 60 * 60 * 1000


def _get(path: str, params: dict[str, str]) -> Any:
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX error {payload.get('code')}: {payload.get('msg')}")
    return payload["data"]


def settlement_interval_ms(funding: dict[str, str]) -> int:
    """由 fundingTime 与 prevFundingTime 推导结算间隔，不写死 8 小时。"""
    prev = funding.get("prevFundingTime")
    if prev:
        return int(funding["fundingTime"]) - int(prev)
    nxt = funding.get("nextFundingTime")
    if nxt:
        return int(nxt) - int(funding["fundingTime"])
    raise ValueError(f"{funding.get('instId')}: 无法从接口字段推导结算间隔")


def get_ticker(inst_id: str) -> dict[str, str]:
    return _get("/market/ticker", {"instId": inst_id})[0]


def get_top_tickers(inst_type: str = "SPOT", top_n: int = 10) -> list[dict[str, str]]:
    rows = _get("/market/tickers", {"instType": inst_type})
    rows.sort(key=lambda r: float(r.get("volCcy24h") or 0), reverse=True)
    return rows[:top_n]


def get_funding_rates(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    if symbols is None:
        symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"]

    out: list[dict[str, Any]] = []
    for symbol in symbols:
        funding = _get("/public/funding-rate", {"instId": symbol})[0]
        interval = settlement_interval_ms(funding)
        rate = float(funding["fundingRate"])
        out.append({
            "instId": symbol,
            "fundingRate": rate,
            "intervalHours": interval / 3_600_000,
            "annualized": rate * (YEAR_MS / interval),
            "interestRate": float(funding.get("interestRate") or 0),
            "fundingTime": int(funding["fundingTime"]),
        })
    return out


def main() -> None:
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    print(f"===== OKX 公开行情示例（as_of={as_of}） =====\n")

    for symbol in ["BTC-USDT", "ETH-USDT", "SOL-USDT"]:
        ticker = get_ticker(symbol)
        last = float(ticker["last"])
        open24h = float(ticker["open24h"])
        change = (last / open24h - 1) * 100 if open24h else float("nan")
        print(f"{symbol}  最新价: {last:.6g}  24h涨跌: {change:+.2f}%  24h量: {ticker['vol24h']}")

    print("\nSPOT 成交额 TOP 10:")
    for row in get_top_tickers("SPOT", 10):
        print(f"  {row['instId']:<16} last={row['last']:<12} volCcy24h={row['volCcy24h']}")

    print("\n永续资金费率（年化按接口结算间隔计算）:")
    for row in get_funding_rates():
        print(
            f"  {row['instId']:<16} rate={row['fundingRate']:.8f} "
            f"interval={row['intervalHours']:g}h annualized={row['annualized'] * 100:.2f}%"
        )


if __name__ == "__main__":
    main()
