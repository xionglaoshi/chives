"""Quote sources for the simulated broker: a test file or the Tencent snapshot."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import requests

from paper_broker_mcp.envelope import to_cn
from paper_broker_mcp.rules import decimal_of, tencent_symbol

logger = logging.getLogger(__name__)

TENCENT_ENDPOINT = "https://qt.gtimg.cn/q="
TENCENT_TIMEOUT_SECONDS = 5.0
_FIELD_RE = re.compile(r'v_[a-z]{2}\d{6}="([^"]*)"')


@dataclass(frozen=True)
class Quote:
    code: str
    price: Decimal
    prev_close: Decimal | None = None
    limit_up: Decimal | None = None
    limit_down: Decimal | None = None
    time: str | None = None

    def usable(self) -> bool:
        return self.price > 0


class QuoteSource:
    """Read the configured quote file in test mode, else fetch a Tencent snapshot."""

    def __init__(self, *, test_mode: bool = False, quote_file: Path | None = None) -> None:
        self.test_mode = test_mode
        self.quote_file = quote_file

    def get(self, code: str) -> Quote | None:
        if self.test_mode and self.quote_file is not None:
            return self._from_file(code)
        return self._from_tencent(code)

    def _from_file(self, code: str) -> Quote | None:
        path = self.quote_file
        if path is None:
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("quote file unreadable: %s", type(exc).__name__)
            return None
        if not isinstance(raw, dict):
            return None
        item = raw.get(code)
        if item is None:
            item = raw.get(code.split(".")[0])
        if not isinstance(item, dict):
            return None
        price = decimal_of(item.get("price"))
        if price is None:
            return None
        return Quote(
            code=code,
            price=price,
            prev_close=decimal_of(item.get("prev_close")),
            limit_up=decimal_of(item.get("limit_up")),
            limit_down=decimal_of(item.get("limit_down")),
            time=str(item["time"]) if item.get("time") is not None else None,
        )

    def _from_tencent(self, code: str) -> Quote | None:
        symbol = tencent_symbol(code)
        try:
            response = requests.get(
                f"{TENCENT_ENDPOINT}{symbol}",
                timeout=TENCENT_TIMEOUT_SECONDS,
                headers={"User-Agent": "paper-broker-mcp/0.1"},
                allow_redirects=False,
            )
            response.raise_for_status()
            text = response.content.decode("gbk", errors="replace")
        except requests.RequestException as exc:
            logger.warning("quote fetch failed for %s: %s", code, type(exc).__name__)
            return None
        match = _FIELD_RE.search(text)
        if match is None:
            return None
        fields = match.group(1).split("~")
        if len(fields) <= 48:
            return None
        price = decimal_of(fields[3])
        if price is None:
            return None
        return Quote(
            code=code,
            price=price,
            prev_close=decimal_of(fields[4]),
            limit_up=decimal_of(fields[47]),
            limit_down=decimal_of(fields[48]),
            time=fields[30] or None,
        )


def latest_quote_time(source: QuoteSource, codes: list[str]) -> datetime | None:
    """Return the newest parseable quote timestamp for test-mode reference dates."""
    stamps: list[datetime] = []
    for code in codes:
        quote = source.get(code)
        if quote is None or not quote.time:
            continue
        try:
            stamps.append(to_cn(datetime.fromisoformat(quote.time.replace("Z", "+00:00"))))
        except ValueError:
            continue
    return max(stamps) if stamps else None
