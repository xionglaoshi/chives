"""Quote snapshots from the local market-data gateway (`market_quote`).

The gateway is reached at `PORTFOLIO_GATEWAY_URL` (loopback only, default
http://127.0.0.1:8868). One request carries at most 20 codes; longer lists are
split into serial batches. There is no direct upstream fallback.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from portfolio_mcp.gateway import (
    GatewayError,
    call,
    normalize_gateway_url,
    resolve_gateway_url,
)
from portfolio_mcp.symbols import normalize_symbol

MAX_CODES = 20
DEFAULT_TIMEOUT = 8.0
_LINE_RE = re.compile(r'^v_([a-z]{2}\d{6})="(.*)";?$')


class QuoteError(Exception):
    """Quote fetch failure carrying a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Quote:
    code: str
    name: str
    price: float | None
    prev_close: float | None
    change_pct: float | None
    time: str | None
    limit_up: float | None
    limit_down: float | None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _num(value)
    return number if number is not None and number > 0 else None


def _quote_time(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if len(text) == 14 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return text
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def parse_quote_item(code: str, item: Mapping[str, Any]) -> Quote:
    """Map one gateway quote object; missing fields stay None."""
    return Quote(
        code=code,
        name=str(item.get("name") or "").strip(),
        price=_num(item.get("price")),
        prev_close=_num(item.get("prev_close")),
        change_pct=_num(item.get("change_pct")),
        time=_quote_time(item.get("quote_time")),
        limit_up=_positive(item.get("limit_up")),
        limit_down=_positive(item.get("limit_down")),
    )


class GatewayQuoteClient:
    """Batched `market_quote` client; missing rows are simply absent."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._env = env
        self._base_url = base_url
        self._timeout = timeout

    def _base(self) -> str:
        if self._base_url is not None:
            return normalize_gateway_url(self._base_url)
        return resolve_gateway_url(self._env)

    def fetch(self, codes: Sequence[str]) -> dict[str, Quote]:
        symbols: list[str] = []
        seen: set[str] = set()
        for code in codes:
            symbol = normalize_symbol(code)
            if symbol.canonical not in seen:
                seen.add(symbol.canonical)
                symbols.append(symbol.canonical)
        if not symbols:
            return {}

        base = self._base()
        quotes: dict[str, Quote] = {}
        for start in range(0, len(symbols), MAX_CODES):
            chunk = symbols[start : start + MAX_CODES]
            try:
                payload = call(base, "market_quote", {"codes": chunk}, timeout=self._timeout)
            except GatewayError as exc:
                raise QuoteError(exc.code, f"行情取不到（{exc.message}）") from exc
            status = payload.get("status")
            if status not in ("ok", "partial"):
                message = str(payload.get("message") or "数据服务没有返回可用行情")
                raise QuoteError("upstream_error", f"行情取不到（{message}）")
            data = payload.get("data")
            rows = data.get("quotes") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise QuoteError("upstream_error", "行情取不到（返回格式不对）")
            requested = set(chunk)
            for item in rows:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code") or "")
                if code not in requested or code in quotes:
                    continue
                quotes[code] = parse_quote_item(code, item)
        return quotes


def build_url(base: str, symbols: Sequence[str]) -> str:
    """Compatibility helper for callers that still build a vendor quote URL."""
    joined = ",".join(symbols)
    if base.endswith("="):
        return base + joined
    return base + "/q=" + joined


def _field_num(fields: list[str], index: int) -> float | None:
    if index >= len(fields):
        return None
    return _num(fields[index])


def parse_quote_text(text: str) -> dict[str, Quote]:
    """Parse a vendor ``v_szXXXXXX="..."`` snapshot body (compatibility only)."""
    quotes: dict[str, Quote] = {}
    for line in text.splitlines():
        match = _LINE_RE.match(line.strip())
        if match is None:
            continue
        key, body = match.group(1), match.group(2)
        fields = body.split("~")
        if len(fields) < 38:
            continue
        exchange = key[:2].upper()
        digits = key[2:]
        quotes[f"{digits}.{exchange}"] = Quote(
            code=f"{digits}.{exchange}",
            name=fields[1].strip(),
            price=_field_num(fields, 3),
            prev_close=_field_num(fields, 4),
            change_pct=_field_num(fields, 32),
            time=_quote_time(fields[30]),
            limit_up=_positive(fields[47]) if len(fields) > 47 else None,
            limit_down=_positive(fields[48]) if len(fields) > 48 else None,
        )
    return quotes


# Deprecated name kept for chives-hub's portfolio view; it now talks to the gateway.
TencentQuoteClient = GatewayQuoteClient
