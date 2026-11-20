"""Capability layer: the four T140 tools, validation, caching and fallback."""

from __future__ import annotations

import threading
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import config
from .cache import TieredCache
from .codes import Code, InvalidCode, is_overseas_symbol, normalize_code, normalize_overseas_symbol
from .company_service import CompanyError, CompanyTools
from .company_sources import CompanySources
from .envelope import basis, envelope, missing, now_iso, unavailable
from .market_service import MarketError, MarketTools
from .market_sources import MarketSources
from .news_service import NewsError, NewsTools
from .news_sources import NewsSources
from .overseas_map import MapError, load_map
from .sources import Sources, rate_items, sina_item, tencent_item
from .transport import HostGovernor, SingleFlight, UpstreamError, UpstreamTimeout

logger = logging.getLogger(__name__)

MINUTE_INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
DAY_INTERVALS = {"1d", "1w", "1M"}
ALL_INTERVALS = set(MINUTE_INTERVALS) | DAY_INTERVALS
ADJUSTS = {"none", "qfq", "hfq"}
GLOBAL_GROUPS = ("us_index", "hk_index", "a50", "fx", "commodity", "rates", "leaders")
DATE_FORMAT = "%Y-%m-%d"

TENCENT_SPECS: dict[str, list[tuple[str, str, str]]] = {
    "us_index": [("dji", "usDJI", "道琼斯"), ("ixic", "usIXIC", "纳斯达克"), ("spx", "usINX", "标普500")],
    "hk_index": [("hsi", "hkHSI", "恒生指数"), ("hstech", "hkHSTECH", "恒生科技指数")],
}
SINA_SPECS: dict[str, list[tuple[str, str, str]]] = {
    "us_index": [("hxc", "gb_hxc", "纳斯达克中国金龙")],
    "a50": [("a50", "hf_CHA50CFD", "富时中国A50期货")],
    "fx": [("usdcnh", "fx_susdcnh", "离岸人民币"), ("dxy", "DINIW", "美元指数")],
    "commodity": [("crude_oil", "hf_CL", "纽约原油"), ("gold", "hf_GC", "纽约黄金"), ("copper", "hf_HG", "美铜")],
}
REASON_TEXT = {
    "not_found_upstream": "该品种暂时取不到行情",
    "no_price": "该品种暂时没有可用价格",
    "field_check_failed": "该品种的行情字段校验未通过，暂不提供",
    "change_pct_unavailable": "该品种的涨跌幅暂不可得",
    "quote_time_unavailable": "该品种没有可用的行情时间",
    "unsupported_symbol": "该代码暂不支持",
    "series_unavailable": "该序列暂时取不到",
    "upstream_failed": "该品种暂时取不到行情",
    "yield_change_in_bp": "利率变动以基点表示",
}


STOCK_ONLY_FIELDS = ("turnover_pct", "volume_ratio", "pe_ttm", "pb_mrq", "limit_up", "limit_down")

class ToolError(Exception):
    """A user-facing failure; the message is already a Chinese instruction."""


class GatewayService:
    """One process-wide service shared by the HTTP daemon and every MCP forwarder."""

    def __init__(
        self,
        *,
        governor: HostGovernor | None = None,
        include_bar_reference: bool = False,
        sources: Sources | Any | None = None,
        market_sources: MarketSources | Any | None = None,
        company_sources: CompanySources | Any | None = None,
        news_sources: NewsSources | Any | None = None,
        cache: TieredCache | None = None,
        clock: Callable[[], float] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.include_bar_reference = include_bar_reference
        self.clock = clock or time.monotonic
        self.now = now or (lambda: datetime.now(config.CN_TZ))
        self.governor = governor or HostGovernor(clock=self.clock)
        self.sources = sources or Sources(self.governor)
        self.market_sources = market_sources or MarketSources(self.governor)
        self.company_sources = company_sources or CompanySources(self.governor)
        self.news_sources = news_sources or NewsSources(self.governor, clock=self.clock)
        self.market = MarketTools(self, self.market_sources)
        self.company = CompanyTools(self, self.company_sources)
        self.news = NewsTools(self, self.news_sources)
        self.market.company = self.company
        self.cache = cache or TieredCache(self.clock)
        self.flight = SingleFlight()
        self.started_at = self.clock()

    # ------------------------------------------------------------------ entry
    def call(self, tool: str, args: dict[str, Any] | None) -> dict[str, Any]:
        handler = {
            "market_quote": self._market_quote,
            "market_bars": self._market_bars,
            "market_intraday": self._market_intraday,
            "market_global": self._market_global,
            "market_overview": self.market.market_overview,
            "market_movers": self.market.market_movers,
            "market_limit_pool": self.market.market_limit_pool,
            "market_sectors": self.market.market_sectors,
            "market_fund_flow": self.market.market_fund_flow,
            "market_trading_activity": self.market.market_trading_activity,
            "market_northbound": self.market.market_northbound,
            "company_search": self.company.company_search,
            "company_financials": self.company.company_financials,
            "company_valuation": self.company.company_valuation,
            "company_consensus": self.company.company_consensus,
            "company_reports": self.company.company_reports,
            "company_earnings": self.company.company_earnings,
            "company_holders": self.company.company_holders,
            "company_profile": self.company.company_profile,
            "news": self.news.news,
            "company_announcements": self.news.company_announcements,
            "convertible_bonds": self.news.convertible_bonds,
        }.get(tool)
        if handler is None:
            return unavailable(
                now_iso(self.now()),
                "未知工具；可选 market_quote、market_bars、market_intraday、market_global、"
                "market_overview、market_movers、market_limit_pool、market_sectors、"
                "market_fund_flow、market_trading_activity、market_northbound、"
                "company_search、company_financials、company_valuation、company_consensus、"
                "company_reports、company_earnings、company_holders、company_profile、news、"
                "company_announcements、convertible_bonds",
            )
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return unavailable(now_iso(self.now()), "参数必须是一个 JSON 对象，例如 {\"code\": \"600519\"}")
        try:
            return handler(args)
        except (ToolError, MarketError, CompanyError, NewsError) as exc:
            return unavailable(now_iso(self.now()), str(exc))
        except UpstreamTimeout:
            return unavailable(now_iso(self.now()), "这次要取的数据量较大，正在准备，请约 1 分钟后再试")
        except UpstreamError:
            return unavailable(now_iso(self.now()), "数据暂时取不到，请稍后再试")
        except Exception:  # defensive boundary: never leak a stack to the caller
            logger.exception("unexpected error in %s", tool)
            return unavailable(now_iso(self.now()), "数据服务处理请求时出错，请稍后再试")

    def health(self) -> dict[str, Any]:
        now = self.clock()
        return {
            "status": "ok",
            "uptime_s": round(max(0.0, now - self.started_at), 1),
            "upstreams": self.governor.health(now)["upstreams"],
            "recent": self.governor.health(now)["recent"],
            "cache": self.cache.stats(),
            "tools": [
                "market_quote",
                "market_bars",
                "market_intraday",
                "market_global",
                "market_overview",
                "market_movers",
                "market_limit_pool",
                "market_sectors",
                "market_fund_flow",
                "market_trading_activity",
                "market_northbound",
                "company_search",
                "company_financials",
                "company_valuation",
                "company_consensus",
                "company_reports",
                "company_earnings",
                "company_holders",
                "company_profile",
                "news",
                "company_announcements",
                "convertible_bonds",
            ],
        }

    # ------------------------------------------------------------------ shared
    def _event(self, tool: str, source: str, *, ok: bool, switched: bool = False, error: str | None = None) -> None:
        try:
            self.governor.record_event(tool, source, switched=switched, ok=ok, error=error)
        except Exception:  # health must never break a tool call
            logger.debug("could not record event", exc_info=True)

    def _cached(self, key: str, ttl: float, fallback: float, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        fresh = self.cache.get_fresh(key)
        if fresh is not None:
            return fresh
        # The computation runs on its own thread and always fills the cache when it
        # finishes; the caller waits at most CALL_BUDGET_SECONDS so a slow upstream
        # never pushes a tool call past dsh's 60-second MCP limit.
        box: dict[str, Any] = {}
        done = threading.Event()

        def work() -> None:
            try:
                payload = self.flight.run(key, compute)
                self.cache.put(key, payload, ttl, fallback)
                box["payload"] = payload
            except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
                box["error"] = exc
            finally:
                done.set()

        threading.Thread(target=work, name="cn-market-compute", daemon=True).start()
        if not done.wait(config.CALL_BUDGET_SECONDS):
            stale = self.cache.get_stale(key)
            if stale is not None:
                return stale
            raise ToolError("这次要取的数据量较大，正在准备，请约 1 分钟后再试")
        if "error" in box:
            stale = self.cache.get_stale(key)
            if stale is not None:
                return stale
            raise box["error"]
        return box["payload"]

    @staticmethod
    def _iso(value: datetime | date | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        return value.isoformat()

    @staticmethod
    def _round(value: float | None, digits: int = 4) -> float | None:
        return None if value is None else round(float(value), digits)

    def _parse_date(self, value: Any, field: str) -> date:
        if not isinstance(value, str):
            raise ToolError(f"{field} 必须是 YYYY-MM-DD 格式的日期，例如 2026-11-17")
        try:
            return datetime.strptime(value, DATE_FORMAT).date()
        except ValueError:
            raise ToolError(f"{field} 必须是 YYYY-MM-DD 格式的日期，例如 2026-11-17") from None

    def _parse_int(self, value: Any, field: str, low: int, high: int, default: int) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ToolError(f"{field} 必须是 {low} 到 {high} 的整数")
        return value

    # ------------------------------------------------------------------ quote
    def _market_quote(self, args: dict[str, Any]) -> dict[str, Any]:
        raw = args.get("codes")
        if not isinstance(raw, list) or isinstance(raw, (str, bytes)):
            raise ToolError('codes 必须是 1 到 20 个代码的列表，例如 ["600519", "000300.SH"]')
        if not raw or len(raw) > config.MAX_CODES:
            raise ToolError("codes 必须包含 1 到 20 个代码")
        codes: list[Code] = []
        seen: set[str] = set()
        for item in raw:
            try:
                code = normalize_code(item)
            except InvalidCode as exc:
                raise ToolError(str(exc)) from None
            if code.canonical not in seen:
                seen.add(code.canonical)
                codes.append(code)
        key = "market_quote|" + ",".join(code.canonical for code in codes)
        return self._cached(key, config.QUOTE_TTL, config.QUOTE_FALLBACK, lambda: self._quote_compute(codes))

    def _quote_compute(self, codes: list[Code]) -> dict[str, Any]:
        found: dict[str, tuple[str, dict[str, Any]]] = {}
        switched = False
        try:
            rows = self.sources.tencent_quotes([code.symbol for code in codes])
            self._event("market_quote", "qt.gtimg.cn", ok=True)
            for code in codes:
                row = rows.get(code.symbol)
                if row is not None:
                    found[code.canonical] = ("tencent", row)
        except Exception as exc:
            self._event("market_quote", "qt.gtimg.cn", ok=False, error=type(exc).__name__)
            switched = True
        rest = [code for code in codes if code.canonical not in found]
        if rest:
            switched = switched or bool(found)
            try:
                rows = self.sources.sina_quotes([code.symbol for code in rest])
                self._event("market_quote", "hq.sinajs.cn", ok=True, switched=True)
                for code in rest:
                    row = rows.get(code.symbol)
                    if row is not None:
                        found[code.canonical] = ("sina", row)
            except Exception as exc:
                self._event("market_quote", "hq.sinajs.cn", ok=False, error=type(exc).__name__)

        items: list[dict[str, Any]] = []
        missing_items: list[dict[str, Any]] = []
        stamps: list[datetime] = []
        for code in codes:
            hit = found.get(code.canonical)
            if hit is None:
                missing_items.append(missing("quote", "该代码暂时取不到行情", item=code.canonical))
                continue
            source, row = hit
            item, gaps, stamp = self._quote_item(code, row, source)
            if item is None:
                missing_items.append(missing("quote", "该代码暂时取不到行情", item=code.canonical))
                continue
            items.append(item)
            missing_items.extend(gaps)
            if stamp is not None:
                stamps.append(stamp)
        if not items:
            raise ToolError("行情服务暂时不可用，稍后再试")
        status = "ok" if not missing_items else "partial"
        as_of = max(stamps).isoformat(timespec="seconds") if stamps else now_iso(self.now())
        return envelope("ok" if status == "ok" else "partial", data={"quotes": items}, as_of=as_of, missing_items=missing_items)

    def _quote_item(
        self, code: Code, row: dict[str, Any], source: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], datetime | None]:
        price = row.get("price")
        if price is None or not isinstance(price, (int, float)) or price <= 0:
            return None, [], None
        gaps: list[dict[str, Any]] = []
        if source == "tencent":
            volume = row.get("volume_lots")
            amount = row.get("amount_wan")
            item: dict[str, Any] = {
                "code": code.canonical,
                "name": row.get("name"),
                "price": self._round(price),
                "prev_close": self._round(row.get("prev_close")),
                "change_pct": self._round(row.get("change_pct")),
                "open": self._round(row.get("open")),
                "high": self._round(row.get("high")),
                "low": self._round(row.get("low")),
                "volume_shares": None if volume is None else int(round(float(volume) * 100)),
                "amount_yuan": None if amount is None else round(float(amount) * 10000.0, 2),
                "turnover_pct": None if code.is_index else self._round(row.get("turnover_pct")),
                "volume_ratio": None if code.is_index else self._round(row.get("volume_ratio"), 2),
                "pe_ttm": None if code.is_index else self._positive(row.get("pe")),
                "pb_mrq": None if code.is_index else self._positive(row.get("pb")),
                "limit_up": None if code.is_index else self._round(row.get("limit_up")),
                "limit_down": None if code.is_index else self._round(row.get("limit_down")),
            }
            for field in STOCK_ONLY_FIELDS:
                if code.is_index:
                    item.pop(field)  # indices have no turnover rate, valuation or price limits
                elif item[field] is None:
                    gaps.append(missing(field, "该代码的这个字段暂时取不到", item=code.canonical))
        else:
            item = {
                "code": code.canonical,
                "name": row.get("name"),
                "price": self._round(price),
                "prev_close": self._round(row.get("prev_close")),
                "change_pct": self._round(row.get("change_pct")),
                "open": self._round(row.get("open")),
                "high": self._round(row.get("high")),
                "low": self._round(row.get("low")),
                "volume_shares": row.get("volume_shares"),
                "amount_yuan": None if row.get("amount_yuan") is None else round(float(row["amount_yuan"]), 2),
                "turnover_pct": None,
                "volume_ratio": None,
                "pe_ttm": None,
                "pb_mrq": None,
                "limit_up": None,
                "limit_down": None,
            }
            for field in STOCK_ONLY_FIELDS:
                if code.is_index:
                    item.pop(field)
                else:
                    gaps.append(missing(field, "该行情源不提供此字段", item=code.canonical))
        stamp = row.get("quote_time")
        item["quote_time"] = self._iso(stamp)
        if item["quote_time"] is None:
            gaps.append(missing("quote_time", "该代码没有可用的行情时间", item=code.canonical))
        return item, gaps, stamp if isinstance(stamp, datetime) else None

    @staticmethod
    def _positive(value: Any) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return round(number, 4) if number > 0 else None

    # ------------------------------------------------------------------ bars
    def _market_bars(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            code = normalize_code(args.get("code"))
        except InvalidCode as exc:
            raise ToolError(str(exc)) from None
        interval = args.get("interval", "1d")
        if not isinstance(interval, str) or interval not in ALL_INTERVALS:
            raise ToolError("interval 只能是 1m/5m/15m/30m/60m/1d/1w/1M")
        adjust = args.get("adjust", "none")
        if not isinstance(adjust, str) or adjust not in ADJUSTS:
            raise ToolError("adjust 只能是 none、qfq 或 hfq")
        limit = self._parse_int(args.get("limit"), "limit", 1, config.MAX_LIMIT, config.DEFAULT_LIMIT)
        end = self._parse_date(args["end"], "end") if args.get("end") is not None else self.now().date()
        if args.get("start") is not None:
            start = self._parse_date(args["start"], "start")
        else:
            span = self._default_span(interval, limit)
            start = end - timedelta(days=span)
        if start > end:
            raise ToolError("start 不能晚于 end")
        key = f"market_bars|{code.canonical}|{interval}|{start}|{end}|{adjust}|{limit}"
        if interval in MINUTE_INTERVALS:
            ttl, fallback = config.MINUTE_TTL, config.MINUTE_FALLBACK
        else:
            ttl, fallback = config.daily_ttl(self.now()), config.DAILY_FALLBACK
        return self._cached(
            key, ttl, fallback, lambda: self._bars_compute(code, interval, start, end, adjust, limit)
        )

    @staticmethod
    def _default_span(interval: str, limit: int) -> int:
        if interval == "1w":
            return max(limit * 8 + 30, 365)
        if interval == "1M":
            return max(limit * 32 + 60, 730)
        return max(limit * 2 + 30, 60)

    def _bars_compute(
        self, code: Code, interval: str, start: date, end: date, adjust: str, limit: int
    ) -> dict[str, Any]:
        if interval in MINUTE_INTERVALS:
            return self._minute_compute(code, interval, start, end, limit)
        return self._daily_compute(code, interval, start, end, adjust, limit)

    def _daily_compute(
        self, code: Code, interval: str, start: date, end: date, adjust: str, limit: int
    ) -> dict[str, Any]:
        fetch_limit = limit
        if interval == "1w":
            fetch_limit = min(5000, max(limit * 8, 300))
        elif interval == "1M":
            fetch_limit = min(5000, max(limit * 32, 400))
        bars: list[dict[str, Any]] = []
        missing_items: list[dict[str, Any]] = []
        bias: list[dict[str, Any]] = []
        used_tencent = False

        try:
            if code.is_index:
                raw = self.sources.sina_index_daily(code.symbol)
            else:
                raw = self.sources.sina_daily(code.symbol, start, end, adjust)
            self._event("market_bars", "finance.sina.com.cn", ok=True)
            bars = self._normalize_daily(raw, start, end)
        except Exception as exc:
            self._event("market_bars", "finance.sina.com.cn", ok=False, error=type(exc).__name__)
        if not bars:
            try:
                raw = self.sources.tencent_daily(code.symbol, start, end, adjust, fetch_limit)
                self._event("market_bars", "web.ifzq.gtimg.cn", ok=True, switched=True)
                bars = self._normalize_daily(raw, start, end)
                used_tencent = True
            except Exception as exc:
                self._event("market_bars", "web.ifzq.gtimg.cn", ok=False, switched=True, error=type(exc).__name__)
        if not bars:
            raise ToolError("该代码在该时段没有 K 线数据；请确认代码与日期范围")

        gaps_amount = any(bar.get("amount_yuan") is None for bar in bars)
        gaps_turnover = any(bar.get("turnover_pct") is None for bar in bars)
        if interval in {"1w", "1M"}:
            bars = self._aggregate_daily(bars, interval)
        if used_tencent:
            bias.append(basis("amount_yuan", "该日线来源不含成交额与换手率，对应字段为 null"))
        for field, absent, reason in (
            ("amount_yuan", gaps_amount, "该日线来源不含成交额"),
            ("turnover_pct", gaps_turnover, "该日线来源不含换手率"),
        ):
            if absent:
                missing_items.append(missing(field, reason, item=code.canonical))
        bars = bars[-limit:]
        as_of = bars[-1].get("time") or now_iso(self.now())
        payload = {
            "code": code.canonical,
            "interval": interval,
            "adjust": adjust,
            "count": len(bars),
            "bars": bars,
        }
        if self.include_bar_reference:
            payload["bar_source"] = "腾讯日线" if used_tencent else "新浪日线"
            payload["source_url"] = ("https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get" if used_tencent
                                     else f"https://finance.sina.com.cn/realstock/company/{code.symbol}/nc.shtml")
        return envelope(
            "partial" if missing_items else "ok",
            data=payload,
            as_of=str(as_of),
            basis_items=bias,
            missing_items=missing_items,
        )

    def _normalize_daily(self, rows: Any, start: date, end: date) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            raw_day = row.get("date") or row.get("time")
            try:
                day = datetime.fromisoformat(str(raw_day)[:10]).date()
            except (TypeError, ValueError):
                continue
            if day < start or day > end:
                continue
            prices = [row.get(key) for key in ("open", "high", "low", "close")]
            if any(value is None for value in prices):
                continue
            volume = row.get("volume_shares")
            amount = row.get("amount_yuan")
            if amount is None:
                amount = row.get("amount")
            if volume is None:
                volume = row.get("volume")
                if volume is not None:
                    volume = int(round(float(volume) * (100 if amount is not None else 1)))
            turnover = row.get("turnover_pct")
            result.append(
                {
                    "time": day.isoformat(),
                    "open": round(float(prices[0]), 4),
                    "high": round(float(prices[1]), 4),
                    "low": round(float(prices[2]), 4),
                    "close": round(float(prices[3]), 4),
                    "volume_shares": None if volume is None else int(round(float(volume))),
                    "amount_yuan": None if amount is None else round(float(amount), 2),
                    "turnover_pct": None if turnover is None else round(float(turnover), 4),
                }
            )
        result.sort(key=lambda item: item["time"])
        return result

    def _aggregate_daily(self, bars: list[dict[str, Any]], interval: str) -> list[dict[str, Any]]:
        groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for bar in bars:
            day = datetime.fromisoformat(bar["time"]).date()
            key = (day.isocalendar().year, day.isocalendar().week) if interval == "1w" else (day.year, day.month)
            groups.setdefault(key, []).append(bar)
        output: list[dict[str, Any]] = []
        for key in sorted(groups):
            chunk = sorted(groups[key], key=lambda item: item["time"])
            amounts = [item["amount_yuan"] for item in chunk]
            turnovers = [item["turnover_pct"] for item in chunk]
            output.append(
                {
                    "time": chunk[-1]["time"],
                    "open": chunk[0]["open"],
                    "high": max(item["high"] for item in chunk),
                    "low": min(item["low"] for item in chunk),
                    "close": chunk[-1]["close"],
                    "volume_shares": (
                        None if all(item["volume_shares"] is None for item in chunk)
                        else sum(int(item["volume_shares"] or 0) for item in chunk)
                    ),
                    "amount_yuan": None if all(value is None for value in amounts) else round(sum(amounts), 2),
                    "turnover_pct": (
                        None if all(value is None for value in turnovers) else round(sum(turnovers), 4)
                    ),
                }
            )
        return output

    def _minute_compute(
        self, code: Code, interval: str, start: date, end: date, limit: int
    ) -> dict[str, Any]:
        period = str(MINUTE_INTERVALS[interval])
        rows: list[dict[str, Any]] = []
        missing_items: list[dict[str, Any]] = []
        bias: list[dict[str, Any]] = []
        switched = False
        try:
            raw = self.sources.sina_minutes(code.symbol, period)
            self._event("market_bars", "quotes.sina.cn", ok=True)
            rows = self._filter_minutes(raw, start, end)
        except Exception as exc:
            self._event("market_bars", "quotes.sina.cn", ok=False, error=type(exc).__name__)
            switched = True
        if not rows:
            try:
                day, raw = self.sources.tencent_minutes(code.symbol)
                self._event("market_bars", "web.ifzq.gtimg.cn", ok=True, switched=True)
                if day is not None and start <= day <= end:
                    rows = self._aggregate_minutes(raw, MINUTE_INTERVALS[interval])
                    switched = True
                    if start < day or end > day:
                        missing_items.append(
                            missing("time", "分钟线只覆盖最近一个交易日，请求区间内的更早日期取不到", item=code.canonical)
                        )
                else:
                    missing_items.append(
                        missing("time", "分钟线只覆盖最近一个交易日，请求区间内的更早日期取不到", item=code.canonical)
                    )
            except Exception as exc:
                self._event("market_bars", "web.ifzq.gtimg.cn", ok=False, switched=True, error=type(exc).__name__)
        if not rows:
            raise ToolError("该代码在该时段没有分钟数据；请确认代码与日期")
        if switched:
            bias.append(basis("time", "分钟线只能提供最近一个交易日"))
        rows = rows[-limit:]
        as_of = rows[-1].get("time") or now_iso(self.now())
        return envelope(
            "partial" if missing_items else "ok",
            data={"code": code.canonical, "interval": interval, "adjust": "none", "count": len(rows), "bars": rows},
            as_of=str(as_of),
            basis_items=bias,
            missing_items=missing_items,
        )

    def _filter_minutes(self, rows: Any, start: date, end: date) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows or []:
            stamp = row.get("ts") if isinstance(row, dict) else None
            if stamp is None:
                continue
            if stamp.date() < start or stamp.date() > end:
                continue
            result.append(
                {
                    "time": stamp.isoformat(timespec="seconds"),
                    "open": self._round(row.get("open")),
                    "high": self._round(row.get("high")),
                    "low": self._round(row.get("low")),
                    "close": self._round(row.get("close")),
                    "volume_shares": None if row.get("volume_shares") is None else int(row["volume_shares"]),
                    "amount_yuan": self._round(row.get("amount_yuan"), 2),
                }
            )
        result.sort(key=lambda item: item["time"])
        return result

    def _aggregate_minutes(self, rows: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            stamp = row.get("ts")
            if not isinstance(stamp, datetime):
                continue
            bucket = stamp.replace(minute=(stamp.minute // minutes) * minutes, second=0, microsecond=0)
            groups.setdefault(bucket.isoformat(timespec="seconds"), []).append(row)
        output: list[dict[str, Any]] = []
        for key in sorted(groups):
            chunk = sorted(groups[key], key=lambda item: item["ts"])
            output.append(
                {
                    "time": key,
                    "open": self._round(chunk[0].get("open")),
                    "high": self._round(max(item.get("high") for item in chunk)),
                    "low": self._round(min(item.get("low") for item in chunk)),
                    "close": self._round(chunk[-1].get("close")),
                    "volume_shares": sum(int(item.get("volume_shares") or 0) for item in chunk),
                    "amount_yuan": round(sum(float(item.get("amount_yuan") or 0.0) for item in chunk), 2),
                }
            )
        return output

    # ------------------------------------------------------------------ intraday
    def _market_intraday(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            code = normalize_code(args.get("code"))
        except InvalidCode as exc:
            raise ToolError(str(exc)) from None
        if args.get("date") is None:
            raise ToolError("缺少 date；请给交易日 YYYY-MM-DD，例如 2026-11-17")
        day = self._parse_date(args.get("date"), "date")
        key = f"market_intraday|{code.canonical}|{day}"
        return self._cached(
            key, config.INTRADAY_TTL, config.INTRADAY_FALLBACK, lambda: self._intraday_compute(code, day)
        )

    def _intraday_compute(self, code: Code, day: date) -> dict[str, Any]:
        try:
            raw = self.sources.sina_minutes(code.symbol, "1")
            self._event("market_intraday", "quotes.sina.cn", ok=True)
        except Exception as exc:
            self._event("market_intraday", "quotes.sina.cn", ok=False, error=type(exc).__name__)
            raise ToolError("分钟数据暂时不可用，稍后再试") from None
        bars = [row for row in (raw or []) if isinstance(row.get("ts"), datetime) and row["ts"].date() == day]
        bars.sort(key=lambda row: row["ts"])
        if not bars:
            raise ToolError("该交易日没有分钟数据；请确认日期是否为交易日")
        times = [row["ts"].strftime("%H:%M") for row in bars]
        highs = [float(row["high"]) for row in bars]
        lows = [float(row["low"]) for row in bars]
        high = max(highs)
        low = min(lows)
        high_index = next(index for index, value in enumerate(highs) if value == high)
        low_index = next(index for index, value in enumerate(lows) if value == low)
        volume_total = sum(int(row.get("volume_shares") or 0) for row in bars)
        amount_total = round(sum(float(row.get("amount_yuan") or 0.0) for row in bars), 4)
        close = float(bars[-1]["close"])
        vwap: float | None = None
        close_vs_vwap: float | None = None
        first_share: float | None = None
        from_high_share: float | None = None
        if volume_total > 0:
            raw_vwap = amount_total / volume_total
            vwap = round(raw_vwap, 4)
            close_vs_vwap = round((raw_vwap - close) / raw_vwap * 100.0, 2)
            first_30 = sum(
                int(row.get("volume_shares") or 0)
                for stamp, row in zip(times, bars)
                if "09:31" <= stamp <= "10:00"
            )
            from_high = sum(int(row.get("volume_shares") or 0) for row in bars[high_index:])
            first_share = round(first_30 / volume_total * 100.0, 1)
            from_high_share = round(from_high / volume_total * 100.0, 1)
        data = {
            "code": code.canonical,
            "date": day.isoformat(),
            "bars": len(bars),
            "first_bar_time": times[0],
            "last_bar_time": times[-1],
            "complete": times[-1] >= "15:00",
            "open": float(bars[0]["open"]),
            "high": high,
            "low": low,
            "close": close,
            "high_time": times[high_index],
            "low_time": times[low_index],
            "volume_total_shares": volume_total,
            "amount_total_yuan": amount_total,
            "vwap": vwap,
            "close_vs_vwap_pct": close_vs_vwap,
            "first_30min_volume_share_pct": first_share,
            "volume_share_from_high_bar_pct": from_high_share,
        }
        return envelope("ok", data=data, as_of=bars[-1]["ts"].isoformat(timespec="seconds"))

    # ------------------------------------------------------------------ global
    def _market_global(self, args: dict[str, Any]) -> dict[str, Any]:
        groups = args.get("groups")
        symbols = args.get("symbols")
        if (groups is None) == (symbols is None):
            raise ToolError("groups 与 symbols 必须二选一：groups 给组名列表，symbols 给 1 到 10 个海外代码")
        if groups is not None:
            if isinstance(groups, (str, bytes)) or not isinstance(groups, list) or not groups:
                raise ToolError("groups 必须是 1 到 7 个组名的列表，例如 [\"a50\", \"fx\"]")
            selected: list[str] = []
            for group in groups:
                if not isinstance(group, str) or group not in GLOBAL_GROUPS:
                    raise ToolError("groups 只能取 us_index、hk_index、a50、fx、commodity、rates、leaders 中的值")
                if group not in selected:
                    selected.append(group)
            key = "market_global|groups|" + ",".join(selected)
            ttl = config.RATES_TTL if selected == ["rates"] else config.GLOBAL_TTL
            fallback = config.RATES_FALLBACK if selected == ["rates"] else config.GLOBAL_FALLBACK
            return self._cached(key, ttl, fallback, lambda: self._global_groups(selected))
        if isinstance(symbols, (str, bytes)) or not isinstance(symbols, list) or not symbols:
            raise ToolError('symbols 必须是 1 到 10 个海外代码的列表，例如 ["usNVDA", "hk00700"]')
        if len(symbols) > config.MAX_OVERSEAS_SYMBOLS:
            raise ToolError("symbols 最多 10 个")
        clean: list[str] = []
        for item in symbols:
            try:
                symbol = normalize_overseas_symbol(item)
            except InvalidCode as exc:
                raise ToolError(str(exc)) from None
            if symbol not in clean:
                clean.append(symbol)
        key = "market_global|symbols|" + ",".join(clean)
        return self._cached(
            key, config.GLOBAL_TTL, config.GLOBAL_FALLBACK, lambda: self._global_symbols(clean)
        )

    def _global_groups(self, groups: list[str]) -> dict[str, Any]:
        leaders: list[dict[str, Any]] | None = None
        leader_error = False
        if "leaders" in groups:
            try:
                leaders = load_map()
            except MapError:
                leader_error = True
        tencent_symbols: list[str] = []
        sina_symbols: list[str] = []
        for group in groups:
            tencent_symbols.extend(symbol for _, symbol, _ in TENCENT_SPECS.get(group, []))
            sina_symbols.extend(symbol for _, symbol, _ in SINA_SPECS.get(group, []))
        if leaders:
            tencent_symbols.extend(leader["symbol"] for leader in leaders)
        tencent_symbols = list(dict.fromkeys(tencent_symbols))
        sina_symbols = list(dict.fromkeys(sina_symbols))
        tencent_rows: dict[str, list[str]] = {}
        sina_rows: dict[str, list[str]] = {}
        tencent_failed = False
        sina_failed = False
        if tencent_symbols:
            try:
                tencent_rows = self.sources.global_tencent(tencent_symbols, now=self.now())
                self._event("market_global", "qt.gtimg.cn", ok=True)
            except Exception as exc:
                tencent_failed = True
                self._event("market_global", "qt.gtimg.cn", ok=False, error=type(exc).__name__)
        if sina_symbols:
            try:
                sina_rows = self.sources.global_sina(sina_symbols, now=self.now())
                self._event("market_global", "hq.sinajs.cn", ok=True)
            except Exception as exc:
                sina_failed = True
                self._event("market_global", "hq.sinajs.cn", ok=False, error=type(exc).__name__)

        result: dict[str, list[dict[str, Any]]] = {}
        missing_items: list[dict[str, Any]] = []
        stamps: list[str] = []
        has_stale = False
        has_settle = False
        for group in groups:
            items: list[dict[str, Any]] = []
            if group == "rates":
                items, rate_gaps = self._global_rates()
                missing_items.extend(rate_gaps)
                for item in items:
                    if item.get("quote_time") is not None:
                        stamps.append(str(item["quote_time"]))
            elif group == "leaders":
                if leader_error:
                    missing_items.append(missing("leaders", "海外龙头映射未配置或格式不正确", item="leaders"))
                elif leaders is None:
                    missing_items.append(missing("leaders", "海外龙头映射未配置", item="leaders"))
                else:
                    for leader in leaders:
                        symbol = leader["symbol"]
                        raw = None if tencent_failed else tencent_rows.get(symbol)
                        item = tencent_item(
                            symbol,
                            leader["name"],
                            symbol,
                            raw,
                            now=self.now(),
                            a_share_sectors=leader["a_share_sectors"],
                            note=leader["note"],
                        )
                        cleaned, gaps, stale, settle = self._clean_global(item)
                        if cleaned is not None:
                            items.append(cleaned)
                            if cleaned.get("quote_time") is not None:
                                stamps.append(str(cleaned["quote_time"]))
                        missing_items.extend(gaps)
                        has_stale = has_stale or stale
                        has_settle = has_settle or settle
            else:
                for key, symbol, name in TENCENT_SPECS.get(group, []):
                    raw = None if tencent_failed else tencent_rows.get(symbol)
                    item = tencent_item(key, name, symbol, raw, now=self.now())
                    cleaned, gaps, stale, settle = self._clean_global(item)
                    if cleaned is not None:
                        items.append(cleaned)
                        if cleaned.get("quote_time") is not None:
                            stamps.append(str(cleaned["quote_time"]))
                    missing_items.extend(gaps)
                    has_stale = has_stale or stale
                    has_settle = has_settle or settle
                for key, symbol, name in SINA_SPECS.get(group, []):
                    raw = None if sina_failed else sina_rows.get(symbol)
                    item = sina_item(key, name, symbol, raw, now=self.now())
                    cleaned, gaps, stale, settle = self._clean_global(item)
                    if cleaned is not None:
                        items.append(cleaned)
                        if cleaned.get("quote_time") is not None:
                            stamps.append(str(cleaned["quote_time"]))
                    missing_items.extend(gaps)
                    has_stale = has_stale or stale
                    has_settle = has_settle or settle
            result[group] = items
            if not items and group not in {"rates", "leaders"}:
                missing_items.append(missing(group, "该组暂时取不到数据", item=group))
        if not any(result.values()):
            raise ToolError("外盘数据暂时不可用，稍后再试")
        bias: list[dict[str, Any]] = []
        if has_settle:
            bias.append(basis("change_pct", "期货涨跌幅相对昨结算价"))
        if "rates" in groups and result.get("rates"):
            bias.append(basis("price", "利率为百分数，另给 change_bp（基点）"))
        as_of = max(stamps) if stamps and all(stamps) else now_iso(self.now())
        return envelope(
            "partial" if missing_items else "ok",
            data={"groups": result},
            as_of=as_of,
            stale=has_stale,
            basis_items=bias,
            missing_items=missing_items,
        )

    def _global_symbols(self, symbols: list[str]) -> dict[str, Any]:
        try:
            rows = self.sources.global_tencent(symbols, now=self.now())
            self._event("market_global", "qt.gtimg.cn", ok=True)
        except Exception as exc:
            self._event("market_global", "qt.gtimg.cn", ok=False, error=type(exc).__name__)
            raise ToolError("外盘数据暂时不可用，稍后再试") from None
        items: list[dict[str, Any]] = []
        missing_items: list[dict[str, Any]] = []
        stamps: list[str] = []
        has_stale = False
        for symbol in symbols:
            item = tencent_item(symbol, None, symbol, rows.get(symbol), now=self.now())
            cleaned, gaps, stale, _ = self._clean_global(item)
            if cleaned is not None:
                items.append(cleaned)
                if cleaned.get("quote_time") is not None:
                    stamps.append(str(cleaned["quote_time"]))
            missing_items.extend(gaps)
            has_stale = has_stale or stale
        if not items:
            raise ToolError("外盘数据暂时不可用，稍后再试")
        return envelope(
            "partial" if missing_items else "ok",
            data={"items": items},
            as_of=max(stamps) if stamps else now_iso(self.now()),
            stale=has_stale,
            missing_items=missing_items,
        )

    def _global_rates(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        start = self.now().date() - timedelta(days=30)
        try:
            series = self.sources.bond_rates(start)
            items = rate_items(series, now=self.now())
            self._event("market_global", "datacenter.eastmoney.com", ok=True)
        except Exception as exc:
            self._event("market_global", "datacenter.eastmoney.com", ok=False, error=type(exc).__name__)
            return [], [missing("rates", "利率序列暂时取不到", item="rates")]
        cleaned: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        for item in items:
            entry, item_gaps, _, _ = self._clean_global(item)
            gaps.extend(item_gaps)
            if entry is not None:
                cleaned.append(entry)
        return cleaned, gaps

    def _clean_global(
        self, item: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool, bool]:
        key = str(item.get("key") or item.get("name") or "")
        stale = bool(item.get("stale"))
        settle = item.get("prev_close_kind") == "settle"
        price = item.get("price")
        reason = item.get("reason")
        gaps: list[dict[str, Any]] = []
        if price is None:
            gaps.append(missing("price", REASON_TEXT.get(str(reason), "该品种暂时取不到行情"), item=key))
            return None, gaps, stale, settle
        allow = (
            "key", "name", "price", "prev_close", "change_pct", "quote_time", "quote_tz",
            "prev_close_kind", "change_bp", "unit", "a_share_sectors", "note",
        )
        cleaned = {name: item[name] for name in allow if name in item}
        if item.get("change_pct") is None and item.get("unit") not in {"pct", "pct_points"}:
            gaps.append(missing("change_pct", REASON_TEXT.get(str(reason), "该品种的涨跌幅暂不可得"), item=key))
        if item.get("quote_time") is None:
            gaps.append(missing("quote_time", "该品种没有可用的行情时间", item=key))
        return cleaned, gaps, stale, settle
