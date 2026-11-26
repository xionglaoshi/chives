"""Offline fakes shared by the gateway tests."""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from chives_data.service import GatewayService
from chives_data.sources import parse_sina_index_daily, parse_tencent_quotes
from chives_data.transport import HostGovernor, UpstreamError

CN = timezone(timedelta(hours=8))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeSources:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.quote_tencent: dict[str, dict[str, Any]] = {}
        self.quote_sina: dict[str, dict[str, Any]] = {}
        self.quote_tencent_error: BaseException | None = None
        self.quote_sina_error: BaseException | None = None
        self.daily_sina: list[dict[str, Any]] = []
        self.daily_tencent: list[dict[str, Any]] = []
        self.index_sina: list[dict[str, Any]] = []
        self.sina_daily_error: BaseException | None = None
        self.tencent_daily_error: BaseException | None = None
        self.minutes_sina: list[dict[str, Any]] = []
        self.minutes_tencent: tuple[Any, list[dict[str, Any]]] = (None, [])
        self.sina_minutes_error: BaseException | None = None
        self.tencent_minutes_error: BaseException | None = None
        self.global_tencent_rows: dict[str, list[str]] = {}
        self.global_sina_rows: dict[str, list[str]] = {}
        self.global_tencent_error: BaseException | None = None
        self.global_sina_error: BaseException | None = None
        self.rates: dict[str, dict[Any, float]] = {}
        self.rates_error: BaseException | None = None
        self.quote_delay = 0.0

    def _call(self, name: str) -> None:
        self.calls.append(name)

    @staticmethod
    def fail() -> None:
        raise UpstreamError("upstream_network", circuit=True)

    def tencent_quotes(self, symbols):
        self._call("tencent_quotes")
        if self.quote_delay:
            time.sleep(self.quote_delay)
        if self.quote_tencent_error:
            raise self.quote_tencent_error
        return {symbol: copy.deepcopy(self.quote_tencent[symbol]) for symbol in symbols if symbol in self.quote_tencent}

    def sina_quotes(self, symbols):
        self._call("sina_quotes")
        if self.quote_sina_error:
            raise self.quote_sina_error
        return {symbol: copy.deepcopy(self.quote_sina[symbol]) for symbol in symbols if symbol in self.quote_sina}

    def sina_daily(self, symbol, start, end, adjust):
        self._call("sina_daily")
        if self.sina_daily_error:
            raise self.sina_daily_error
        return copy.deepcopy(self.daily_sina)

    def sina_index_daily(self, symbol):
        self._call("sina_index_daily")
        if self.sina_daily_error:
            raise self.sina_daily_error
        return copy.deepcopy(self.index_sina)

    def tencent_daily(self, symbol, start, end, adjust, limit):
        self._call("tencent_daily")
        if self.tencent_daily_error:
            raise self.tencent_daily_error
        return copy.deepcopy(self.daily_tencent)

    def sina_minutes(self, symbol, period):
        self._call("sina_minutes")
        if self.sina_minutes_error:
            raise self.sina_minutes_error
        return copy.deepcopy(self.minutes_sina)

    def tencent_minutes(self, symbol):
        self._call("tencent_minutes")
        if self.tencent_minutes_error:
            raise self.tencent_minutes_error
        return copy.deepcopy(self.minutes_tencent)

    def global_tencent(self, symbols, *, now):
        self._call("global_tencent")
        if self.global_tencent_error:
            raise self.global_tencent_error
        return {symbol: copy.deepcopy(self.global_tencent_rows[symbol]) for symbol in symbols if symbol in self.global_tencent_rows}

    def global_sina(self, symbols, *, now):
        self._call("global_sina")
        if self.global_sina_error:
            raise self.global_sina_error
        return {symbol: copy.deepcopy(self.global_sina_rows[symbol]) for symbol in symbols if symbol in self.global_sina_rows}

    def bond_rates(self, start):
        self._call("bond_rates")
        if self.rates_error:
            raise self.rates_error
        return copy.deepcopy(self.rates)


def make_service(
    sources: FakeSources | None = None,
    *,
    market_sources: FakeMarketSources | None = None,
    company_sources: FakeCompanySources | None = None,
    news_sources: FakeNewsSources | None = None,
    clock: FakeClock | None = None,
    now: datetime | None = None,
) -> GatewayService:
    clock = clock or FakeClock()
    fixed_now = now or datetime(2026, 11, 17, 16, 0, tzinfo=CN)
    governor = HostGovernor(clock=clock, sleep=lambda seconds: None)
    return GatewayService(
        governor=governor,
        sources=sources or FakeSources(),
        market_sources=market_sources or FakeMarketSources(),
        company_sources=company_sources or FakeCompanySources(),
        news_sources=news_sources or FakeNewsSources(),
        clock=clock,
        now=lambda: fixed_now,
    )


def tencent_fixture_rows() -> dict[str, dict[str, Any]]:
    text = (FIXTURES / "tencent_quotes.txt").read_text(encoding="utf-8")
    text += "\n" + (FIXTURES / "tencent_quotes_bj.txt").read_text(encoding="utf-8")
    return parse_tencent_quotes(text)


def minute_rows(rows: list[tuple[str, float, float, float, float, int, float]]) -> list[dict[str, Any]]:
    result = []
    for stamp, open_, high, low, close, volume, amount in rows:
        result.append(
            {
                "ts": datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume_shares": volume,
                "amount_yuan": amount,
            }
        )
    return result


def load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def index_fixture_bars() -> list[dict[str, Any]]:
    return parse_sina_index_daily(load_json("index_bars.json"))


class FakeEngine:
    def __init__(self) -> None:
        self.requests = 0
        self.failures = 0
        self.last_error = None
        self.last_ok = None

    def snapshot(self) -> dict[str, Any]:
        return {"requests": self.requests, "failures": self.failures, "last_error": self.last_error, "last_ok": self.last_ok}


class FakeMarketSources:
    def __init__(self) -> None:
        self.engine = FakeEngine()
        self.engine_payloads: dict[str, Any] = {}
        self.engine_error: BaseException | None = None
        self.engine_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.legu = None
        self.legu_error: BaseException | None = None
        self.movers: dict[str, list[dict[str, Any]]] = {}
        self.movers_error: BaseException | None = None
        self.boards: dict[str, list[dict[str, Any]]] = {}
        self.boards_error: BaseException | None = None
        self.ths_industry_rows: list[dict[str, Any]] = []
        self.ths_industry_error: BaseException | None = None
        self.nodes: dict[str, list[dict[str, Any]]] = {}
        self.nodes_error: BaseException | None = None
        self.sector_flows: dict[str, list[dict[str, Any]]] = {}
        self.stock_flows: dict[str, list[dict[str, Any]]] = {}
        self.flows_error: BaseException | None = None
        self.stock_history: list[dict[str, Any]] = []
        self.stock_history_error: BaseException | None = None
        self.ths_pools: dict[str, tuple[int, list[dict[str, Any]]]] = {}
        self.ths_ladder: dict[str, Any] = {"max_streak": 0, "tiers": []}
        self.ths_error: BaseException | None = None
        self.datacenter_rows: dict[str, list[dict[str, Any]]] = {}
        self.datacenter_error: BaseException | None = None
        self.hkex: dict[str, dict[str, Any]] = {}
        self.holdings: dict[str, dict[str, Any]] = {}
        self.hkex_error: BaseException | None = None
        self.eastmoney_open_value = False

    def engine_get(self, path, params=None):
        self.engine_calls.append((path, dict(params or {})))
        self.engine.requests += 1
        if self.engine_error is not None:
            self.engine.failures += 1
            raise self.engine_error
        if path not in self.engine_payloads:
            self.engine.failures += 1
            raise UpstreamError("engine_unavailable", circuit=False)
        return copy.deepcopy(self.engine_payloads[path])

    def sync_engine_health(self, clock):
        return None

    def eastmoney_open(self, clock):
        return self.eastmoney_open_value

    def legu_activity(self):
        if self.legu_error is not None:
            raise self.legu_error
        return self.legu

    def sina_movers(self, kind, *, include_bj, limit):
        if self.movers_error is not None:
            raise self.movers_error
        return copy.deepcopy(self.movers.get(kind, []))[:limit]

    def sina_boards(self, kind):
        if self.boards_error is not None:
            raise self.boards_error
        return copy.deepcopy(self.boards.get(kind, []))

    def ths_industry_summary(self):
        if self.ths_industry_error is not None:
            raise self.ths_industry_error
        return copy.deepcopy(self.ths_industry_rows)

    def sina_node(self, node, *, limit):
        if self.nodes_error is not None:
            raise self.nodes_error
        return copy.deepcopy(self.nodes.get(node, []))[:limit]

    def sina_sector_flows(self, kind):
        if self.flows_error is not None:
            raise self.flows_error
        return copy.deepcopy(self.sector_flows.get(kind, []))

    def sina_stock_flows(self, kind, *, include_bj, limit):
        if self.flows_error is not None:
            raise self.flows_error
        return copy.deepcopy(self.stock_flows.get(kind, []))[:limit]

    def sina_stock_history(self, code, *, days):
        if self.stock_history_error is not None:
            raise self.stock_history_error
        return copy.deepcopy(self.stock_history)[:days]

    def ths_pool(self, kind, *, day, limit):
        if self.ths_error is not None:
            raise self.ths_error
        total, rows = self.ths_pools.get(kind, (0, []))
        return total, copy.deepcopy(rows)[:limit]

    def ths_ladder(self, *, day):
        if self.ths_error is not None:
            raise self.ths_error
        return copy.deepcopy(self.ths_ladder)

    def datacenter(self, report, params):
        if self.datacenter_error is not None:
            raise self.datacenter_error
        return copy.deepcopy(self.datacenter_rows.get(report, []))

    def hkex_daily(self, day):
        if self.hkex_error is not None:
            raise self.hkex_error
        key = day.isoformat()
        if key not in self.hkex:
            raise UpstreamError("not_found", circuit=False)
        return copy.deepcopy(self.hkex[key])

    def hkex_holdings(self, channel, *, day=None):
        if self.hkex_error is not None:
            raise self.hkex_error
        key = f"{channel}|{day.isoformat() if day else 'latest'}"
        if key not in self.holdings:
            raise UpstreamError("not_found", circuit=False)
        return copy.deepcopy(self.holdings[key])


class FakeCompanySources:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.search_rows: list[dict[str, Any]] = []
        self.search_error: BaseException | None = None
        self.names: list[dict[str, Any]] = []
        self.names_error: BaseException | None = None
        self.indicators: dict[str, list[dict[str, Any]]] = {}
        self.statements: dict[str, list[dict[str, Any]]] = {}
        self.financial_error: BaseException | None = None
        self.stock_values: dict[str, list[dict[str, Any]]] = {}
        self.stock_value_error: BaseException | None = None
        self.baidu: dict[str, list[dict[str, Any]]] = {}
        self.baidu_error: BaseException | None = None
        self.industry_rows: list[dict[str, Any]] = []
        self.industry_error: BaseException | None = None
        self.index_values: dict[str, list[dict[str, Any]]] = {}
        self.index_value_error: BaseException | None = None
        self.all_a: list[dict[str, Any]] = []
        self.all_a_error: BaseException | None = None
        self.forecast_em: list[dict[str, Any]] = []
        self.forecast_em_error: BaseException | None = None
        self.forecast_ths: dict[str, list[dict[str, Any]]] = {}
        self.forecast_ths_error: BaseException | None = None
        self.rating_rows: list[dict[str, Any]] = []
        self.rating_error: BaseException | None = None
        self.report_rows: list[dict[str, Any]] = []
        self.report_error: BaseException | None = None
        self.earnings_rows: dict[str, list[dict[str, Any]]] = {}
        self.earnings_error: BaseException | None = None
        self.schedule_rows: list[dict[str, Any]] = []
        self.schedule_error: BaseException | None = None
        self.top10: dict[str, list[dict[str, Any]]] = {}
        self.fund_rows: list[dict[str, Any]] = []
        self.holder_rows: list[dict[str, Any]] = []
        self.lockup_rows: list[dict[str, Any]] = []
        self.lockup_market_rows: list[dict[str, Any]] = []
        self.lockup_market_error: BaseException | None = None
        self.holder_error: BaseException | None = None
        self.segment_rows: list[dict[str, Any]] = []
        self.segment_error: BaseException | None = None
        self.org_rows: list[dict[str, Any]] = []
        self.org_error: BaseException | None = None
        self.concept_rows: list[dict[str, Any]] = []
        self.concept_error: BaseException | None = None
        self.index_cons: dict[str, list[dict[str, Any]]] = {}
        self.index_cons_error: BaseException | None = None

    def _call(self, name: str) -> None:
        self.calls.append(name)

    def search(self, query, limit):
        self._call("search")
        if self.search_error is not None:
            raise self.search_error
        return copy.deepcopy(self.search_rows)[:limit]

    def a_share_names(self):
        self._call("a_share_names")
        if self.names_error is not None:
            raise self.names_error
        return copy.deepcopy(self.names)

    def financial_indicators(self, code):
        self._call("financial_indicators")
        if self.financial_error is not None:
            raise self.financial_error
        return copy.deepcopy(self.indicators.get(code, []))

    def financial_statement(self, exchange, digits, statement):
        self._call("financial_statement")
        if self.financial_error is not None:
            raise self.financial_error
        return copy.deepcopy(self.statements.get(statement, []))

    def stock_valuation(self, digits):
        self._call("stock_valuation")
        if self.stock_value_error is not None:
            raise self.stock_value_error
        return copy.deepcopy(self.stock_values.get(digits, []))

    def baidu_valuation(self, digits, indicator, period):
        self._call("baidu_valuation")
        if self.baidu_error is not None:
            raise self.baidu_error
        return copy.deepcopy(self.baidu.get(indicator, []))

    def industry_valuation(self, date_yyyymmdd):
        self._call("industry_valuation")
        if self.industry_error is not None:
            raise self.industry_error
        return copy.deepcopy(self.industry_rows)

    def index_valuation(self, name):
        self._call("index_valuation")
        if self.index_value_error is not None:
            raise self.index_value_error
        return copy.deepcopy(self.index_values.get(name, []))

    def all_a_valuation(self):
        self._call("all_a_valuation")
        if self.all_a_error is not None:
            raise self.all_a_error
        return copy.deepcopy(self.all_a)

    def profit_forecast_em(self):
        self._call("profit_forecast_em")
        if self.forecast_em_error is not None:
            raise self.forecast_em_error
        return copy.deepcopy(self.forecast_em)

    def profit_forecast_ths(self, digits, indicator):
        self._call("profit_forecast_ths")
        if self.forecast_ths_error is not None:
            raise self.forecast_ths_error
        return copy.deepcopy(self.forecast_ths.get(indicator, []))

    def ratings(self, digits):
        self._call("ratings")
        if self.rating_error is not None:
            raise self.rating_error
        return copy.deepcopy(self.rating_rows)

    def reports(self, digits):
        self._call("reports")
        if self.report_error is not None:
            raise self.report_error
        return copy.deepcopy(self.report_rows)

    def earnings(self, kind, date_yyyymmdd):
        self._call("earnings")
        if self.earnings_error is not None:
            raise self.earnings_error
        return copy.deepcopy(self.earnings_rows.get(kind, []))

    def schedule(self, date_yyyymmdd):
        self._call("schedule")
        if self.schedule_error is not None:
            raise self.schedule_error
        return copy.deepcopy(self.schedule_rows)

    def holders_top10(self, exchange, digits, date_yyyymmdd):
        self._call("holders_top10")
        if self.holder_error is not None:
            raise self.holder_error
        return copy.deepcopy(self.top10.get(date_yyyymmdd, self.top10.get("*", [])))

    def fund_holders(self, digits):
        self._call("fund_holders")
        if self.holder_error is not None:
            raise self.holder_error
        return copy.deepcopy(self.fund_rows)

    def holder_count(self, digits):
        self._call("holder_count")
        if self.holder_error is not None:
            raise self.holder_error
        return copy.deepcopy(self.holder_rows)

    def lockup(self, digits):
        self._call("lockup")
        if self.holder_error is not None:
            raise self.holder_error
        return copy.deepcopy(self.lockup_rows)

    def lockup_market(self, start, end):
        self._call("lockup_market")
        if self.lockup_market_error is not None:
            raise self.lockup_market_error
        return copy.deepcopy(self.lockup_market_rows)

    def segments(self, exchange, digits):
        self._call("segments")
        if self.segment_error is not None:
            raise self.segment_error
        return copy.deepcopy(self.segment_rows)

    def org_info(self, code):
        self._call("org_info")
        if self.org_error is not None:
            raise self.org_error
        return copy.deepcopy(self.org_rows)

    def concepts(self, code):
        self._call("concepts")
        if self.concept_error is not None:
            raise self.concept_error
        return copy.deepcopy(self.concept_rows)

    def index_constituents(self, digits):
        self._call("index_constituents")
        if self.index_cons_error is not None:
            raise self.index_cons_error
        return copy.deepcopy(self.index_cons.get(digits, []))


COMPANY_FIXTURES = FIXTURES / "company"


def company_fixture(name: str) -> Any:
    return json.loads((COMPANY_FIXTURES / name).read_text(encoding="utf-8"))


NEWS_FIXTURES = FIXTURES / "news"


def news_fixture(name: str) -> Any:
    return json.loads((NEWS_FIXTURES / name).read_text(encoding="utf-8"))


def news_fixture_bytes(name: str) -> bytes:
    return (NEWS_FIXTURES / name).read_bytes()


class FakeNewsSources:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.stock_rows: list[dict[str, Any]] = []
        self.flash_cls_rows: list[dict[str, Any]] = []
        self.flash_em_rows: list[dict[str, Any]] = []
        self.calendar_rows: list[dict[str, Any]] = []
        self.suspension_rows: list[dict[str, Any]] = []
        self.irm_rows: list[dict[str, Any]] = []
        self.spot_rows: list[dict[str, Any]] = []
        self.term_rows: list[dict[str, Any]] = []
        self.remaining: dict[str, dict[str, Any]] = {}
        self.announcement_name: str | None = "柳工"
        self.announcement_rows: list[dict[str, Any]] = []
        self.announcement_total = 0
        self.pdf_bytes = b""
        self.error: BaseException | None = None
        self.errors: dict[str, BaseException] = {}

    def _call(self, name: str) -> None:
        self.calls.append(name)
        error = self.errors.get(name) or self.error
        if error is not None:
            raise error

    def stock_news(self, digits):
        self._call("stock_news")
        return copy.deepcopy(self.stock_rows)

    def flash_cls(self):
        self._call("flash_cls")
        return copy.deepcopy(self.flash_cls_rows)

    def flash_em(self):
        self._call("flash_em")
        return copy.deepcopy(self.flash_em_rows)

    def calendar(self, date_yyyymmdd):
        self._call("calendar")
        return copy.deepcopy(self.calendar_rows)

    def suspensions(self, date_yyyymmdd):
        self._call("suspensions")
        return copy.deepcopy(self.suspension_rows)

    def irm(self, digits):
        self._call("irm")
        return copy.deepcopy(self.irm_rows)

    def cb_spot(self):
        self._call("cb_spot")
        return copy.deepcopy(self.spot_rows)

    def cb_terms(self):
        self._call("cb_terms")
        return copy.deepcopy(self.term_rows)

    def cb_terms_by_codes(self, codes):
        self._call("cb_terms_by_codes")
        return {row["SECURITY_CODE"]: copy.deepcopy(row) for row in self.term_rows if row.get("SECURITY_CODE") in codes}

    def cb_remaining(self, codes):
        self._call("cb_remaining")
        return {code: copy.deepcopy(self.remaining[code]) for code in codes if code in self.remaining}

    def announcements(self, digits, *, category, start, end, limit, offset=0):
        self._call("announcements")
        rows = copy.deepcopy(self.announcement_rows[offset : offset + limit])
        return self.announcement_name, rows, self.announcement_total

    def download_pdf(self, pdf_url):
        self._call("download_pdf")
        return self.pdf_bytes
