from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from cn_research_mcp.infra import RateLimiter, TTLCache, UpstreamClient
from cn_research_mcp.service import ResearchService
from cn_research_mcp.sources import ENDPOINTS

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 16)


def load(name: str) -> pd.DataFrame:
    payload = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return pd.DataFrame(payload["records"], columns=payload["columns"])


class FakeSources:
    """Stands in for sources.Sources. A response is a DataFrame, an exception, or a callable."""

    def __init__(self, **responses: Any) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, tuple]] = []

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    def __getattr__(self, name: str):
        if name not in ENDPOINTS:
            raise AttributeError(name)

        def fetch(*args: Any) -> pd.DataFrame:
            self.calls.append((name, args))
            response = self.responses.get(name)
            if response is None:
                raise RuntimeError(f"no fake response for {name}")
            if isinstance(response, BaseException):
                raise response
            if callable(response):
                return response(*args)
            return response

        return fetch


def make_service(
    clock=None, index_names=None, today=None, now=None, index_units_confirmed=True, **responses: Any
) -> tuple[ResearchService, FakeSources]:
    fake = FakeSources(**responses)
    cache = TTLCache(clock=clock) if clock else TTLCache()
    client = UpstreamClient(RateLimiter(min_interval=0, sleep=lambda _s: None))
    service = ResearchService(
        sources=fake,
        client=client,
        cache=cache,
        today=today or (lambda: TODAY),
        now=now,
        index_names=index_names
        or ("全A", "上证50", "沪深300", "中证500", "中证1000", "创业板50"),
        index_units_confirmed=index_units_confirmed,
    )
    return service, fake


def value_frame(dates: list[str], pe: list[float], pb: list[float] | None = None) -> pd.DataFrame:
    pb = pb or [2.0] * len(dates)
    return pd.DataFrame(
        {
            "数据日期": dates,
            "当日收盘价": [10.0] * len(dates),
            "PE(TTM)": pe,
            "PE(静)": pe,
            "市净率": pb,
            "总市值": [1.0e10] * len(dates),
            "流通市值": [8.0e9] * len(dates),
        }
    )


def business_days(end: str, count: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=end, periods=count)]
