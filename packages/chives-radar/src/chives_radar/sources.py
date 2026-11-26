"""Quote sources: the local market-data gateway and JSONL replay."""

from __future__ import annotations

import bisect
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import DEFAULT_GATEWAY_URL, parse_gateway_url
from .engine import SourceError
from .models import Quote, parse_exch_time, parse_iso

GATEWAY_CALL_PATH = "/v1/call"
MAX_CODES_PER_REQUEST = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> Optional[float]:
    number = _number(value)
    return number if number is not None and number > 0 else None


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise SourceError(f"网关跳转被拒绝（HTTP {code}）")


def _call_gateway(url: str, tool: str, args: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps({"tool": tool, "args": args}).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "chives-radar/0.1",
        },
    )
    opener = build_opener(_RefuseRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except SourceError:
        raise
    except HTTPError as exc:
        raise SourceError(f"网关返回 HTTP {exc.code}") from exc
    except (URLError, OSError, ValueError) as exc:
        raise SourceError(f"请求网关失败: {type(exc).__name__}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SourceError("网关响应过大")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError("网关返回了无法解析的 JSON") from exc
    if not isinstance(payload, dict):
        raise SourceError("网关返回的外壳不是对象")
    return payload


def _quote_from_gateway(code: str, item: dict[str, Any]) -> Optional[Quote]:
    price = _positive(item.get("price"))
    prev_close = _number(item.get("prev_close"))
    if price is None or prev_close is None:
        return None
    try:
        exch_time = parse_exch_time(item.get("quote_time"))
    except ValueError:
        return None
    volume_shares = _to_int(item.get("volume_shares"))
    return Quote(
        code=code,
        name=str(item.get("name") or ""),
        price=price,
        prev_close=prev_close,
        open=_positive(item.get("open")) or price,
        high=_positive(item.get("high")) or price,
        low=_positive(item.get("low")) or price,
        volume_lots=int(round(volume_shares / 100.0)),
        amount_yuan=_number(item.get("amount_yuan")),
        exch_time=exch_time,
        limit_up=_positive(item.get("limit_up")) or 0.0,
        limit_down=_positive(item.get("limit_down")) or 0.0,
        volume_ratio=_positive(item.get("volume_ratio")),
    )


class GatewaySource:
    """Batch snapshot source backed by the local market-data gateway."""

    def __init__(self, gateway_url: str = DEFAULT_GATEWAY_URL, timeout: float = 3.0) -> None:
        self.base_url = parse_gateway_url(gateway_url)
        self.url = self.base_url + GATEWAY_CALL_PATH
        self.timeout = timeout

    def fetch(self, codes: list[str], now: datetime) -> dict[str, Quote]:
        if not codes:
            return {}  # nothing to watch (empty watchlist and no reminder plans)
        collected: dict[str, Quote] = {}
        for start in range(0, len(codes), MAX_CODES_PER_REQUEST):
            chunk = codes[start : start + MAX_CODES_PER_REQUEST]
            payload = _call_gateway(
                self.url, "market_quote", {"codes": chunk}, self.timeout
            )
            status = payload.get("status")
            if status not in {"ok", "partial"}:
                raise SourceError(
                    str(payload.get("message") or "网关没有返回可用行情")
                )
            data = payload.get("data")
            rows = data.get("quotes") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise SourceError("网关返回的行情列表格式不对")
            requested = set(chunk)
            for item in rows:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code") or "")
                if code not in requested or code in collected:
                    continue
                quote = _quote_from_gateway(code, item)
                if quote is not None:
                    collected[code] = quote
        result = {code: collected[code] for code in codes if code in collected}
        if not result:
            raise SourceError("网关未返回任何请求的代码")
        return result


class ReplayRow:
    __slots__ = ("t", "quotes", "error", "index")

    def __init__(
        self,
        t: datetime,
        quotes: dict[str, Quote],
        error: Optional[str],
        index: int,
    ) -> None:
        self.t = t
        self.quotes = quotes
        self.error = error
        self.index = index


def _quote_from_mapping(code: str, payload: Any) -> Quote:
    if not isinstance(payload, dict):
        raise ValueError("quote must be an object")
    return Quote(
        code=code,
        name=str(payload.get("name", "")),
        price=float(payload["price"]),
        prev_close=float(payload["prev_close"]),
        open=float(payload.get("open", payload["price"])),
        high=float(payload.get("high", payload["price"])),
        low=float(payload.get("low", payload["price"])),
        volume_lots=int(payload.get("volume_lots") or 0),
        amount_yuan=(
            float(payload["amount_yuan"]) if payload.get("amount_yuan") is not None else None
        ),
        exch_time=parse_exch_time(payload["exch_time"]),
        limit_up=float(payload.get("limit_up") or 0.0),
        limit_down=float(payload.get("limit_down") or 0.0),
        volume_ratio=(
            float(payload["volume_ratio"])
            if payload.get("volume_ratio") is not None
            and float(payload["volume_ratio"]) > 0
            else None
        ),
    )


class ReplaySource:
    """Replay a recorded JSONL stream against a simulated clock."""

    def __init__(self, path: str | Path) -> None:
        target = Path(path)
        self.path = target
        rows: list[ReplayRow] = []
        with target.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                moment = parse_iso(record.get("t"))
                quotes: dict[str, Quote] = {}
                for code, payload in (record.get("quotes") or {}).items():
                    try:
                        quotes[str(code)] = _quote_from_mapping(str(code), payload)
                    except (KeyError, TypeError, ValueError):
                        continue
                error = record.get("error")
                rows.append(
                    ReplayRow(
                        t=moment,
                        quotes=quotes,
                        error=str(error) if error else None,
                        index=index,
                    )
                )
        if not rows:
            raise ValueError(f"回放文件为空: {target}")
        rows.sort(key=lambda row: (row.t, row.index))
        self.rows = rows
        self._times = [row.t for row in rows]
        self.start_time = rows[0].t
        self.last_time = rows[-1].t

    def fetch(self, codes: list[str], now: datetime) -> dict[str, Quote]:
        position = bisect.bisect_right(self._times, now) - 1
        if position < 0:
            raise SourceError("回放尚未开始（now 早于第一行）")
        row = self.rows[position]
        if row.error:
            raise SourceError(row.error)
        return {code: row.quotes[code] for code in codes if code in row.quotes}
