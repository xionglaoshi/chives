"""Capability layer for the eight company/research tools (T142)."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import config
from .codes import INDEX_UNIVERSE, Code, InvalidCode, normalize_code
from .company_parse import (
    cash_flow_by_date,
    consensus_disagrees,
    normalize_all_a,
    normalize_baidu_valuation,
    normalize_consensus_em,
    normalize_consensus_ths,
    normalize_indicators,
    normalize_index_valuation,
    normalize_industry_valuation,
    normalize_names,
    normalize_ratings,
    normalize_reports,
    normalize_statement,
    normalize_stock_valuation,
    text,
)
from .company_parse_events import (
    normalize_concepts,
    normalize_earnings,
    normalize_funds,
    normalize_holder_count,
    normalize_index_constituents,
    normalize_lockup,
    normalize_lockup_market,
    normalize_org_info,
    normalize_schedule,
    normalize_segments,
    normalize_top10,
    summarize_lockup_days,
)
from .envelope import basis, envelope, missing, now_iso, unavailable

VALUATION_SCOPES = ("stock", "industry", "index", "market")
STATEMENTS = ("indicators", "income", "balance", "cashflow")
HOLDER_KINDS = ("top10", "funds", "count", "lockup")
LOCKUP_SORTS = ("market_cap_yuan", "date", "float_ratio_pct")
SEGMENT_BY = ("product", "region", "industry")
EARNINGS_KINDS = ("forecast", "express", "report", "schedule")

VALUATION_INDEX_NAMES = (
    "上证50",
    "沪深300",
    "中证500",
    "中证1000",
    "创业板50",
    "上证380",
    "上证180",
    "深证红利",
    "深证100",
    "上证红利",
    "中证100",
    "中证800",
)
VALUATION_INDEX_CODES = {
    "000016": "上证50",
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
    "399673": "创业板50",
    "000009": "上证380",
    "000010": "上证180",
    "399324": "深证红利",
    "399330": "深证100",
    "000015": "上证红利",
    "000903": "中证100",
    "000906": "中证800",
}
CONSTITUENTS_UNSUPPORTED = {
    "399001.SZ": "该指数没有公开的成分股名单",
    "399006.SZ": "该指数没有公开的成分股名单",
}
INDUSTRY_LOOKBACK_DAYS = 5
HOLDER_LOOKBACK = 5


class CompanyError(Exception):
    """A user-facing failure; the message is already a Chinese instruction."""


class CompanyTools:
    def __init__(self, service: Any, sources: Any) -> None:
        self.service = service
        self.sources = sources
        self._names_lock = threading.Lock()
        self._names_loading = False

    # ------------------------------------------------------------------ shared
    def _event(self, tool: str, source: str, *, ok: bool, error: str | None = None) -> None:
        try:
            self.service._event(tool, source, ok=ok, error=error)
        except Exception:
            pass

    def _cached(self, key: str, ttl: float, fallback: float, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        return self.service._cached(key, ttl, fallback, compute)

    def _now(self) -> datetime:
        return self.service.now()

    def _int(self, args: dict[str, Any], name: str, low: int, high: int, default: int) -> int:
        value = args.get(name)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise CompanyError(f"{name} 必须是 {low} 到 {high} 的整数")
        return value

    def _choice(
        self, args: dict[str, Any], name: str, choices: tuple[str, ...], default: str
    ) -> str:
        value = args.get(name)
        if value is None:
            return default
        if not isinstance(value, str) or value not in choices:
            raise CompanyError(f"{name} 必须是 {'、'.join(choices)} 之一")
        return value

    def _code(self, args: dict[str, Any], required: bool = True) -> Code | None:
        value = args.get("code")
        if value is None:
            if required:
                raise CompanyError("请提供 code，例如 600519 或 002553.SZ")
            return None
        try:
            code = normalize_code(value)
        except InvalidCode as exc:
            raise CompanyError(str(exc)) from None
        if code.is_index:
            raise CompanyError("该工具需要个股代码；指数请用 scope=index 或 index 参数")
        return code

    def _period(self, args: dict[str, Any]) -> str | None:
        value = args.get("period")
        if value is None:
            return None
        if not isinstance(value, str):
            raise CompanyError("period 必须是 YYYY-03-31、06-30、09-30 或 12-31 格式的日期")
        day = _parse_day(value)
        if day is None or day[5:] not in {"03-31", "06-30", "09-30", "12-31"}:
            raise CompanyError("period 必须是报告期：YYYY-03-31、06-30、09-30 或 12-31")
        return day

    def _day_arg(self, args: dict[str, Any], name: str, default: date) -> date:
        value = args.get(name)
        if value is None:
            return default
        day = _parse_day(value)
        if day is None:
            raise CompanyError(f"{name} 必须是 YYYY-MM-DD 格式的日期")
        return date.fromisoformat(day)

    def _default_period(self) -> str:
        today = self._now().date()
        for year in range(today.year, today.year - 3, -1):
            for month, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
                candidate = date(year, month, day)
                if candidate <= today:
                    return candidate.isoformat()
        return f"{today.year - 1}-12-31"

    def name_map(self, wait: float = 8.0) -> dict[str, str]:
        fresh = self.service.cache.get_fresh("company_names")
        if fresh is not None:
            return fresh
        with self._names_lock:
            if self._names_loading:
                start = False
            else:
                self._names_loading = True
                start = True
        box: dict[str, Any] = {}
        done = threading.Event()

        def work() -> None:
            try:
                rows = self.service.flight.run("company_names", self.sources.a_share_names)
                names = normalize_names(rows)
                if names:
                    self.service.cache.put(
                        "company_names", names, config.COMPANY_NAMES_TTL, config.COMPANY_NAMES_FALLBACK
                    )
                box["value"] = names
            except BaseException as exc:  # noqa: BLE001 - best-effort enrichment
                box["error"] = exc
            finally:
                with self._names_lock:
                    self._names_loading = False
                done.set()

        if start:
            threading.Thread(target=work, name="cn-market-names", daemon=True).start()
        done.wait(wait if start else min(wait, 0.5))
        value = box.get("value")
        return value if isinstance(value, dict) else {}

    def _name_of(self, code: Code, rows: list[dict[str, Any]] | None = None) -> str | None:
        for row in rows or []:
            name = text(row.get("SECURITY_NAME_ABBR")) or text(row.get("股票简称"))
            if name:
                return name
        return self.name_map(wait=3.0).get(code.canonical)

    # ------------------------------------------------------------------ search
    def company_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise CompanyError("query 必须是名称、简称、拼音首字母或 6 位代码")
        query = query.strip()
        limit = self._int(args, "limit", 1, config.MAX_SEARCH_LIMIT, config.DEFAULT_SEARCH_LIMIT)
        key = f"company_search|{query}|{limit}"
        return self._cached(
            key,
            config.COMPANY_SEARCH_TTL,
            config.COMPANY_SEARCH_FALLBACK,
            lambda: self._search_compute(query, limit),
        )

    def _search_compute(self, query: str, limit: int) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        failed = False
        direct: Code | None = None
        try:
            direct = normalize_code(query)
        except InvalidCode:
            direct = None
        search_query = direct.digits if direct is not None else query
        try:
            candidates = self.sources.search(search_query, max(limit * 3, limit))
            self._event("company_search", "searchapi.eastmoney.com", ok=True)
        except Exception as exc:  # noqa: BLE001 - local matching is the fallback
            failed = True
            self._event("company_search", "searchapi.eastmoney.com", ok=False, error=type(exc).__name__)
        if direct is not None:
            candidates = [item for item in candidates if item.get("code") == direct.canonical]
        basis_items = None
        if not candidates:
            names = self.name_map(wait=8.0)
            candidates = _search_local(names, query)
            if not candidates and direct is not None:
                candidates = _direct_candidate(direct, names)
            if candidates:
                note = (
                    "本次只匹配代码，指数名称来自内置清单"
                    if direct is not None and direct.is_index
                    else "本次只匹配 A 股简称与代码，未覆盖 ETF 与指数"
                )
                basis_items = [basis("candidates", note)]
        if not candidates:
            suffix = "，检索服务暂时不可用" if failed else ""
            return unavailable(now_iso(self._now()), f"没有找到匹配的代码或名称{suffix}；请换一个关键词")
        return envelope(
            "ok",
            data={
                "query": query,
                "count": len(candidates[:limit]),
                "total_matching": len(candidates),
                "candidates": candidates[:limit],
            },
            as_of=now_iso(self._now()),
            basis_items=basis_items,
        )

    # ------------------------------------------------------------------ financials
    def company_financials(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._code(args)
        assert code is not None
        statement = self._choice(args, "statement", STATEMENTS, "indicators")
        periods = self._int(
            args, "periods", 1, config.MAX_FINANCIAL_PERIODS, config.DEFAULT_FINANCIAL_PERIODS
        )
        key = f"company_financials|{code.canonical}|{statement}|{periods}"
        return self._cached(
            key,
            config.COMPANY_FINANCIALS_TTL,
            config.COMPANY_FINANCIALS_FALLBACK,
            lambda: self._financials_compute(code, statement, periods),
        )

    def _financials_compute(self, code: Code, statement: str, periods: int) -> dict[str, Any]:
        if statement == "indicators":
            try:
                rows = self.sources.financial_indicators(code.canonical)
            except Exception as exc:
                self._event("company_financials", "datacenter.eastmoney.com", ok=False, error=type(exc).__name__)
                return unavailable(now_iso(self._now()), "该代码的财务数据暂时取不到，请稍后再试")
            self._event("company_financials", "datacenter.eastmoney.com", ok=True)
            values = normalize_indicators(rows, periods)
            if not values:
                return unavailable(now_iso(self._now()), "该代码没有可用的财务数据")
            missing_items = []
            try:
                cash_rows = self.sources.financial_statement(code.exchange, code.digits, "cashflow")
                cash = cash_flow_by_date(cash_rows)
                self._event("company_financials", "quotes.sina.cn", ok=True)
            except Exception as exc:
                cash = {}
                self._event("company_financials", "quotes.sina.cn", ok=False, error=type(exc).__name__)
            if not cash:
                missing_items.append(missing("operating_cash_flow_yuan", "经营现金流数据暂时取不到"))
            for item in values:
                item["operating_cash_flow_yuan"] = cash.get(item["report_date"])
            status = "partial" if missing_items else "ok"
            return envelope(
                status,
                data={
                    "code": code.canonical,
                    "name": self._name_of(code, rows),
                    "statement": statement,
                    "count": len(values),
                    "periods": values,
                },
                as_of=now_iso(self._now()),
                missing_items=missing_items,
            )
        try:
            rows = self.sources.financial_statement(code.exchange, code.digits, statement)
            self._event("company_financials", "quotes.sina.cn", ok=True)
        except Exception as exc:
            self._event("company_financials", "quotes.sina.cn", ok=False, error=type(exc).__name__)
            return unavailable(now_iso(self._now()), "该代码的报表数据暂时取不到，请稍后再试")
        values = normalize_statement(rows, statement, periods)
        if not values:
            return unavailable(now_iso(self._now()), "该报告期的报表数据取不到")
        return envelope(
            "ok",
            data={
                "code": code.canonical,
                "name": self._name_of(code, rows),
                "statement": statement,
                "count": len(values),
                "periods": values,
            },
            as_of=now_iso(self._now()),
        )

    # ------------------------------------------------------------------ valuation
    def company_valuation(self, args: dict[str, Any]) -> dict[str, Any]:
        scope = self._choice(args, "scope", VALUATION_SCOPES, "stock")
        years = self._int(
            args, "years", 1, config.MAX_VALUATION_YEARS, config.DEFAULT_VALUATION_YEARS
        )
        if scope == "stock":
            code = self._code(args)
            assert code is not None
            key = f"company_valuation|stock|{code.canonical}|{years}"
            return self._cached(
                key,
                config.COMPANY_VALUATION_TTL,
                config.COMPANY_VALUATION_FALLBACK,
                lambda: self._stock_valuation(code, years),
            )
        if scope == "industry":
            limit = self._int(
                args, "limit", 1, config.MAX_INDUSTRY_LIMIT, config.DEFAULT_INDUSTRY_LIMIT
            )
            day = _parse_day(args.get("date")) if args.get("date") is not None else None
            if args.get("date") is not None and day is None:
                raise CompanyError("date 必须是 YYYY-MM-DD 格式的日期")
            key = f"company_valuation|industry|{day}|{limit}"
            return self._cached(
                key,
                config.COMPANY_CONSENSUS_TTL,
                config.COMPANY_CONSENSUS_FALLBACK,
                lambda: self._industry_valuation(day, limit),
            )
        if scope == "index":
            index_name = self._valuation_index(args.get("index"))
            key = f"company_valuation|index|{index_name}"
            return self._cached(
                key,
                config.COMPANY_CONSENSUS_TTL,
                config.COMPANY_CONSENSUS_FALLBACK,
                lambda: self._index_valuation(index_name),
            )
        key = "company_valuation|market"
        return self._cached(
            key,
            config.COMPANY_CONSENSUS_TTL,
            config.COMPANY_CONSENSUS_FALLBACK,
            self._market_valuation,
        )

    def _stock_valuation(self, code: Code, years: int) -> dict[str, Any]:
        try:
            rows = self.sources.stock_valuation(code.digits)
            self._event("company_valuation", "datacenter-web.eastmoney.com", ok=True)
            data = normalize_stock_valuation(rows, years)
        except Exception as exc:
            self._event("company_valuation", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
            data = None
        if data is not None:
            return envelope(
                "ok",
                data={"code": code.canonical, "name": self._name_of(code), **data},
                as_of=now_iso(self._now()),
            )
        period = "近一年" if years <= 1 else "近三年" if years <= 3 else "近五年" if years <= 5 else "近十年"
        try:
            pe_rows = self.sources.baidu_valuation(code.digits, "市盈率(TTM)", period)
            pb_rows = self.sources.baidu_valuation(code.digits, "市净率", period)
            self._event("company_valuation", "gushitong.baidu.com", ok=True)
            data = normalize_baidu_valuation(pe_rows, pb_rows, years)
        except Exception as exc:
            self._event("company_valuation", "gushitong.baidu.com", ok=False, error=type(exc).__name__)
            data = None
        if data is None:
            return unavailable(now_iso(self._now()), "该代码的估值数据暂时取不到，请稍后再试")
        missing_items = [
            missing("ps_ttm", "该估值口径不提供市销率"),
            missing("pe_static", "该估值口径不提供静态市盈率"),
        ]
        return envelope(
            "partial",
            data={"code": code.canonical, "name": self._name_of(code), **data},
            as_of=now_iso(self._now()),
            basis_items=[basis("valuation", "本次只有市盈率与市净率两列，分位仍按同一窗口计算")],
            missing_items=missing_items,
        )

    def _industry_valuation(self, day: str | None, limit: int) -> dict[str, Any]:
        if day is not None:
            candidates = [day]
        else:
            today = self._now().date()
            candidates = [(today - timedelta(days=offset)).isoformat() for offset in range(INDUSTRY_LOOKBACK_DAYS + 1)]
        data = None
        used = None
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                rows = self.sources.industry_valuation(candidate.replace("-", ""))
                self._event("company_valuation", "webapi.cninfo.com.cn", ok=True)
            except Exception as exc:
                last_error = exc
                self._event("company_valuation", "webapi.cninfo.com.cn", ok=False, error=type(exc).__name__)
                if day is not None:
                    break
                continue
            data = normalize_industry_valuation(rows, limit)
            if data is not None:
                used = candidate
                break
        if data is None:
            if last_error is not None and day is not None:
                return unavailable(now_iso(self._now()), "该日期的行业估值数据暂时取不到")
            return unavailable(now_iso(self._now()), "最近的行业估值数据暂时取不到，请稍后再试")
        data["requested_date"] = used
        return envelope(
            "ok",
            data=data,
            as_of=used or now_iso(self._now()),
            basis_items=[basis("pe_static_weighted", "行业估值为静态市盈率口径，没有滚动市盈率列")],
        )

    def _valuation_index(self, value: Any) -> str:
        if value is None:
            return "沪深300"
        if not isinstance(value, str) or not value.strip():
            raise CompanyError("index 必须是指数名称或代码，例如 沪深300、000300.SH")
        raw = value.strip().upper()
        if value.strip() in VALUATION_INDEX_NAMES:
            return value.strip()
        digits = raw.split(".")[0]
        if digits.startswith(("SH", "SZ")):
            digits = digits[2:]
        name = VALUATION_INDEX_CODES.get(digits)
        if name is None:
            raise CompanyError(
                "index 暂不支持该指数；可用 " + "、".join(VALUATION_INDEX_NAMES)
            )
        return name

    def _index_valuation(self, name: str) -> dict[str, Any]:
        try:
            rows = self.sources.index_valuation(name)
            self._event("company_valuation", "legulegu.com", ok=True)
        except Exception as exc:
            self._event("company_valuation", "legulegu.com", ok=False, error=type(exc).__name__)
            return unavailable(now_iso(self._now()), "该指数的估值数据暂时取不到，请稍后再试")
        data = normalize_index_valuation(rows, name)
        if data is None:
            return unavailable(now_iso(self._now()), "该指数没有可用的估值数据")
        return envelope("ok", data=data, as_of=now_iso(self._now()))

    def _market_valuation(self) -> dict[str, Any]:
        try:
            rows = self.sources.all_a_valuation()
            self._event("company_valuation", "legulegu.com", ok=True)
        except Exception as exc:
            self._event("company_valuation", "legulegu.com", ok=False, error=type(exc).__name__)
            return unavailable(now_iso(self._now()), "全 A 估值数据暂时取不到，请稍后再试")
        data = normalize_all_a(rows)
        if data is None:
            return unavailable(now_iso(self._now()), "全 A 估值数据暂时取不到")
        data["scope"] = "market"
        return envelope(
            "ok",
            data=data,
            as_of=now_iso(self._now()),
            basis_items=[basis("pe_ttm_median", "全 A 估值同时给出中位数与等权两套统计，未取平均")],
        )

    # ------------------------------------------------------------------ consensus
    def company_consensus(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._code(args)
        assert code is not None
        limit = self._int(args, "limit", 1, config.MAX_RATING_LIMIT, config.DEFAULT_RATING_LIMIT)
        key = f"company_consensus|{code.canonical}|{limit}"
        return self._cached(
            key,
            config.COMPANY_CONSENSUS_TTL,
            config.COMPANY_CONSENSUS_FALLBACK,
            lambda: self._consensus_compute(code, limit),
        )

    def _consensus_compute(self, code: Code, limit: int) -> dict[str, Any]:
        primary = None
        primary_error: Exception | None = None
        try:
            primary = normalize_consensus_em(self.sources.profit_forecast_em(), code.digits)
            self._event("company_consensus", "datacenter-web.eastmoney.com", ok=True)
        except Exception as exc:
            primary_error = exc
            self._event("company_consensus", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
        ths_eps: list[dict[str, Any]] = []
        ths_profit: list[dict[str, Any]] = []
        try:
            ths_eps = normalize_consensus_ths(
                self.sources.profit_forecast_ths(code.digits, "预测年报每股收益"), "eps"
            )
            self._event("company_consensus", "basic.10jqka.com.cn", ok=True)
        except Exception as exc:
            self._event("company_consensus", "basic.10jqka.com.cn", ok=False, error=type(exc).__name__)
        try:
            ths_profit = normalize_consensus_ths(
                self.sources.profit_forecast_ths(code.digits, "预测年报净利润"), "profit"
            )
        except Exception:
            ths_profit = []
        ratings_data = None
        try:
            ratings_data = normalize_ratings(self.sources.ratings(code.digits), limit)
            self._event("company_consensus", "stock.finance.sina.com.cn", ok=True)
        except Exception as exc:
            self._event("company_consensus", "stock.finance.sina.com.cn", ok=False, error=type(exc).__name__)
        if primary is None and not ths_eps and ratings_data is None:
            return unavailable(now_iso(self._now()), "该代码没有可用的机构预测或评级数据")
        basis_items = []
        missing_items = []
        if primary is None:
            if ths_eps:
                basis_items.append(basis("eps_forecast", "本次只有一套机构预测汇总，机构数与区间来自该套口径"))
            else:
                missing_items.append(missing("eps_forecast", "机构 EPS 预期暂时取不到"))
            eps_forecast = [
                {"year": item["year"], "eps_yuan": item["mean"]} for item in ths_eps if item["mean"] is not None
            ]
            cross_check = None
            name = self._name_of(code)
            report_count = None
            rating_counts = None
        else:
            eps_forecast = primary["eps_forecast"]
            cross_check = ths_eps or None
            name = primary["name"] or self._name_of(code)
            report_count = primary["report_count"]
            rating_counts = primary["rating_counts"]
            if cross_check and consensus_disagrees(eps_forecast, cross_check, config.CONSENSUS_DISAGREE):
                basis_items.append(
                    basis("eps_forecast", "两套统计口径的年度均值差异超过 5%，两者都列出，未取平均")
                )
        if not ths_profit:
            missing_items.append(missing("net_profit_forecast", "净利润预期暂时取不到"))
        if ratings_data is None:
            missing_items.append(missing("ratings", "评级明细暂时取不到"))
        cross_by_year = {item["year"]: item for item in (cross_check or [])}
        for item in eps_forecast:
            peer = cross_by_year.get(item["year"])
            if peer is not None:
                item.update(
                    {
                        "analysts": peer["analysts"],
                        "min_yuan": peer["min"],
                        "mean_yuan": peer["mean"],
                        "max_yuan": peer["max"],
                    }
                )
        for item in ths_profit:
            item["min_yuan"] = item["min"]
            item["mean_yuan"] = item["mean"]
            item["max_yuan"] = item["max"]
        for item in cross_check or []:
            item["min_yuan"] = item["min"]
            item["mean_yuan"] = item["mean"]
            item["max_yuan"] = item["max"]
        data: dict[str, Any] = {
            "code": code.canonical,
            "name": name,
            "kind": "sell_side_forecast",
            "report_count": report_count,
            "rating_counts": rating_counts,
            "eps_forecast": eps_forecast,
            "eps_cross_check": cross_check,
            "net_profit_forecast": ths_profit,
            "ratings": ratings_data,
        }
        status = "partial" if missing_items else "ok"
        return envelope(
            status,
            data=data,
            as_of=now_iso(self._now()),
            basis_items=basis_items or None,
            missing_items=missing_items or None,
        )

    # ------------------------------------------------------------------ reports
    def company_reports(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._code(args)
        assert code is not None
        limit = self._int(args, "limit", 1, config.MAX_RATING_LIMIT, config.DEFAULT_RATING_LIMIT)
        key = f"company_reports|{code.canonical}|{limit}"
        return self._cached(
            key,
            config.COMPANY_STOCK_TTL,
            config.COMPANY_STOCK_FALLBACK,
            lambda: self._reports_compute(code, limit),
        )

    def _reports_compute(self, code: Code, limit: int) -> dict[str, Any]:
        try:
            rows = self.sources.reports(code.digits)
            self._event("company_reports", "reportapi.eastmoney.com", ok=True)
        except Exception as exc:
            self._event("company_reports", "reportapi.eastmoney.com", ok=False, error=type(exc).__name__)
            return unavailable(now_iso(self._now()), "该代码的研报列表暂时取不到，请稍后再试")
        data = normalize_reports(rows, limit)
        if not data["reports"]:
            return unavailable(now_iso(self._now()), "该代码近期没有研报")
        return envelope(
            "ok",
            data={"code": code.canonical, "name": self._name_of(code), **data},
            as_of=now_iso(self._now()),
        )

    # ------------------------------------------------------------------ earnings
    def company_earnings(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = self._choice(args, "kind", EARNINGS_KINDS, "forecast")
        period = self._period(args) or self._default_period()
        code = self._code(args, required=False)
        limit = self._int(args, "limit", 1, config.MAX_EVENT_LIMIT, config.DEFAULT_EVENT_LIMIT)
        key = f"company_earnings|{kind}|{period}|{code.canonical if code else None}|{limit}"
        return self._cached(
            key,
            config.COMPANY_EARNINGS_TTL,
            config.COMPANY_EARNINGS_FALLBACK,
            lambda: self._earnings_compute(kind, period, code, limit),
        )

    def _earnings_compute(
        self, kind: str, period: str, code: Code | None, limit: int
    ) -> dict[str, Any]:
        try:
            if kind == "schedule":
                rows = self.sources.schedule(period.replace("-", ""))
            else:
                rows = self.sources.earnings(kind, period.replace("-", ""))
            self._event("company_earnings", "datacenter.eastmoney.com", ok=True)
        except Exception as exc:
            self._event("company_earnings", "datacenter.eastmoney.com", ok=False, error=type(exc).__name__)
            return unavailable(now_iso(self._now()), "该报告期的业绩数据暂时取不到，请稍后再试")
        if code is not None:
            rows = [
                row
                for row in rows
                if str(row.get("股票代码") or "").zfill(6) == code.digits
            ]
        if not rows:
            message = f"{period} 没有该公司的" if code is not None else f"{period} 没有"
            return unavailable(now_iso(self._now()), message + "业绩数据")
        if kind == "schedule":
            data = normalize_schedule(rows, limit)
        else:
            data = normalize_earnings(rows, kind, limit)
        data["period"] = period
        data["code"] = code.canonical if code is not None else None
        basis_items = None
        if kind == "forecast":
            basis_items = [basis("change_pct_mid", "业绩变动幅度为区间中值，原文区间同时给出")]
        return envelope(
            "ok",
            data=data,
            as_of=now_iso(self._now()),
            basis_items=basis_items,
        )

    # ------------------------------------------------------------------ holders
    def company_holders(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = self._choice(args, "kind", HOLDER_KINDS, "top10")
        code = self._code(args, required=kind != "lockup")
        if kind == "lockup" and code is None:
            if args.get("period") is not None:
                raise CompanyError("全市场解禁不接受 period；请用 start 与 end 指定日期区间")
            return self._lockup_market(args)
        assert code is not None
        period = self._period(args)
        if kind == "lockup":
            limit = self._int(args, "limit", 1, config.MAX_LOCKUP_LIMIT, config.DEFAULT_LOCKUP_LIMIT)
        elif kind == "count":
            limit = self._int(args, "limit", 1, config.MAX_HOLDER_PERIODS, config.MAX_HOLDER_PERIODS)
        else:
            limit = self._int(args, "limit", 1, config.MAX_HOLDER_LIMIT, config.DEFAULT_HOLDER_LIMIT)
        key = f"company_holders|{kind}|{code.canonical}|{period}|{limit}"
        return self._cached(
            key,
            config.COMPANY_STOCK_TTL,
            config.COMPANY_STOCK_FALLBACK,
            lambda: self._holders_compute(kind, code, period, limit),
        )

    def _holders_compute(
        self, kind: str, code: Code, period: str | None, limit: int
    ) -> dict[str, Any]:
        today = self._now().date()
        if kind == "top10":
            candidates = [period] if period else recent_report_periods(today, HOLDER_LOOKBACK)
            rows: list[dict[str, Any]] = []
            used = None
            last_error: Exception | None = None
            for candidate in candidates:
                try:
                    rows = self.sources.holders_top10(
                        code.exchange, code.digits, candidate.replace("-", "")
                    )
                    self._event("company_holders", "emweb.securities.eastmoney.com", ok=True)
                except Exception as exc:
                    last_error = exc
                    self._event("company_holders", "emweb.securities.eastmoney.com", ok=False, error=type(exc).__name__)
                    if period is not None:
                        break
                    continue
                if rows:
                    used = candidate
                    break
            if not rows:
                if period is not None:
                    return unavailable(now_iso(self._now()), "该报告期的十大流通股东数据取不到")
                if last_error is not None:
                    return unavailable(now_iso(self._now()), "最近报告期的十大流通股东数据暂时取不到")
                return unavailable(now_iso(self._now()), "最近报告期没有十大流通股东数据")
            data = normalize_top10(rows)
            data.update({"code": code.canonical, "view": "top10_float", "period": used})
            return envelope(
                "ok",
                data=data,
                as_of=now_iso(self._now()),
                basis_items=[basis("float_ratio_pct", "十大流通股东按流通股本口径统计，不是总股本")],
            )
        if kind == "funds":
            try:
                rows = self.sources.fund_holders(code.digits)
                self._event("company_holders", "vip.stock.finance.sina.com.cn", ok=True)
            except Exception as exc:
                self._event("company_holders", "vip.stock.finance.sina.com.cn", ok=False, error=type(exc).__name__)
                return unavailable(now_iso(self._now()), "基金持股数据暂时取不到，请稍后再试")
            data = normalize_funds(rows, period, limit, today)
            if not data["rows"]:
                return unavailable(now_iso(self._now()), "该报告期没有基金持股数据")
            data.update({"code": code.canonical, "view": "funds"})
            return envelope("ok", data=data, as_of=now_iso(self._now()))
        if kind == "count":
            try:
                rows = self.sources.holder_count(code.digits)
                self._event("company_holders", "datacenter-web.eastmoney.com", ok=True)
            except Exception as exc:
                self._event("company_holders", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
                return unavailable(now_iso(self._now()), "股东户数数据暂时取不到，请稍后再试")
            data = normalize_holder_count(rows, limit, today)
            if not data["rows"]:
                return unavailable(now_iso(self._now()), "该代码没有可用的股东户数数据")
            data.update({"code": code.canonical, "kind": "count"})
            return envelope(
                "ok",
                data=data,
                as_of=now_iso(self._now()),
                basis_items=[basis("avg_hold_shares", "户均持股与总市值只给最新一期，历史期留空")],
            )
        try:
            rows = self.sources.lockup(code.digits)
            self._event("company_holders", "datacenter-web.eastmoney.com", ok=True)
        except Exception as exc:
            self._event("company_holders", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
            return unavailable(now_iso(self._now()), "限售解禁数据暂时取不到，请稍后再试")
        data = normalize_lockup(rows, limit)
        if not data["rows"]:
            return unavailable(now_iso(self._now()), "该代码没有可用的限售解禁数据")
        data.update({"code": code.canonical, "kind": "lockup"})
        return envelope(
            "ok",
            data=data,
            as_of=now_iso(self._now()),
            basis_items=[basis("free_ratio_pct", "比例为占流通市值/总市值的百分数")],
        )

    def _lockup_market(self, args: dict[str, Any]) -> dict[str, Any]:
        today = self._now().date()
        start = self._day_arg(args, "start", today)
        end = self._day_arg(args, "end", start + timedelta(days=config.DEFAULT_LOCKUP_WINDOW_DAYS))
        if end < start:
            raise CompanyError("start 不能晚于 end")
        if (end - start).days > config.MAX_LOCKUP_WINDOW_DAYS:
            raise CompanyError(f"start 到 end 最多 {config.MAX_LOCKUP_WINDOW_DAYS} 天")
        sort = self._choice(args, "sort", LOCKUP_SORTS, "market_cap_yuan")
        limit = self._int(
            args, "limit", 1, config.MAX_LOCKUP_MARKET_LIMIT, config.DEFAULT_LOCKUP_MARKET_LIMIT
        )
        key = f"company_holders|lockup|market|{start.isoformat()}|{end.isoformat()}"
        payload = self._cached(
            key,
            config.LOCKUP_MARKET_TTL,
            config.LOCKUP_MARKET_FALLBACK,
            lambda: self._lockup_market_compute(start, end),
        )
        if payload.get("status") == "unavailable":
            return payload
        all_rows = list(payload["data"]["rows"])
        data = {
            "kind": "lockup",
            "view": "lockup_market",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "sort": sort,
            "limit": limit,
            "total_count": len(all_rows),
            "daily": payload["data"]["daily"],
            "rows": self._sort_lockup(all_rows, sort)[:limit],
        }
        return envelope(
            str(payload.get("status") or "ok"),
            data=data,
            as_of=payload["as_of"],
            stale=bool(payload.get("stale")),
            basis_items=payload.get("basis"),
            missing_items=payload.get("missing"),
        )

    def _lockup_market_compute(self, start: date, end: date) -> dict[str, Any]:
        try:
            rows = self.sources.lockup_market(start.isoformat(), end.isoformat())
            self._event("company_holders", "datacenter-web.eastmoney.com", ok=True)
        except Exception as exc:
            self._event(
                "company_holders", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__
            )
            raise CompanyError("全市场限售解禁数据暂时取不到，请稍后再试") from None
        events = normalize_lockup_market(rows, start.isoformat(), end.isoformat())
        missing_items = []
        for field_name, reason in (
            ("market_cap_yuan", "部分解禁事件没有可用的解禁市值"),
            ("float_ratio_pct", "部分解禁事件没有占流通市值比例"),
            ("total_ratio_pct", "部分解禁事件没有占总市值比例"),
            ("shares", "部分解禁事件没有可用的解禁数量"),
            ("holder_type", "部分解禁事件没有限售股类型"),
        ):
            if any(row.get(field_name) is None for row in events):
                missing_items.append(missing(field_name, reason))
        return envelope(
            "partial" if missing_items else "ok",
            data={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "total_count": len(events),
                "daily": summarize_lockup_days(events),
                "rows": events,
            },
            as_of=now_iso(self._now()),
            basis_items=[
                basis("shares", "解禁数量按实际解禁股数统计，单位为股"),
                basis("market_cap_yuan", "按解禁前一交易日收盘价估算的解禁市值，单位为元"),
                basis("float_ratio_pct", "解禁股数占解禁前流通股本的比例，单位为百分数；解禁前流通股本较小（如新股）时可超过 100%"),
                basis("total_ratio_pct", "占总市值比例，单位为百分数"),
                basis("daily", "按解禁日期汇总，只列出有解禁事件的日期"),
            ],
            missing_items=missing_items or None,
        )

    @staticmethod
    def _sort_lockup(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        if sort == "date":
            return sorted(rows, key=lambda row: (row["date"], -(row.get("market_cap_yuan") or -1.0)))
        if sort == "float_ratio_pct":
            return sorted(
                rows,
                key=lambda row: (-(row.get("float_ratio_pct") or -1e18), row["date"], row.get("code") or ""),
            )
        return sorted(
            rows,
            key=lambda row: (-(row.get("market_cap_yuan") or -1e18), row["date"], row.get("code") or ""),
        )

    # ------------------------------------------------------------------ profile
    def company_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._code(args, required=False)
        index_value = args.get("index")
        if code is None and index_value is None:
            raise CompanyError("请提供 code 或 index，至少一个")
        by = self._choice(args, "by", SEGMENT_BY, "product")
        period = self._period(args)
        limit = self._int(
            args, "limit", 1, config.MAX_INDEX_CONS_LIMIT, config.DEFAULT_INDEX_CONS_LIMIT
        )
        key = f"company_profile|{code.canonical if code else None}|{index_value}|{by}|{period}|{limit}"
        return self._cached(
            key,
            config.COMPANY_PROFILE_TTL,
            config.COMPANY_PROFILE_FALLBACK,
            lambda: self._profile_compute(code, index_value, by, period, limit),
        )

    def _profile_compute(
        self,
        code: Code | None,
        index_value: Any,
        by: str,
        period: str | None,
        limit: int,
    ) -> dict[str, Any]:
        output: dict[str, Any] = {}
        missing_items: list[dict[str, Any]] = []
        if code is not None:
            segments_data = None
            try:
                segments_data = normalize_segments(
                    self.sources.segments(code.exchange, code.digits), by, period, self._now().date()
                )
                self._event("company_profile", "emweb.securities.eastmoney.com", ok=True)
            except Exception as exc:
                self._event("company_profile", "emweb.securities.eastmoney.com", ok=False, error=type(exc).__name__)
                missing_items.append(missing("segments", "主营构成暂时取不到"))
            if segments_data is not None and not segments_data.get("rows"):
                missing_items.append(missing("segments", "该分类没有主营构成数据"))
            org_data = None
            try:
                org_data = normalize_org_info(self.sources.org_info(code.canonical))
                self._event("company_profile", "datacenter.eastmoney.com", ok=True)
            except Exception as exc:
                self._event("company_profile", "datacenter.eastmoney.com", ok=False, error=type(exc).__name__)
                missing_items.append(missing("industry", "所属行业与概念暂时取不到"))
            if org_data is not None and org_data.get("industry") is None:
                missing_items.append(missing("industry", "该代码没有可用的行业分类"))
            concepts = []
            if org_data is not None:
                try:
                    concepts = normalize_concepts(self.sources.concepts(code.canonical))
                except Exception as exc:
                    self._event("company_profile", "datacenter.eastmoney.com", ok=False, error=type(exc).__name__)
                    missing_items.append(missing("concepts", "概念板块暂时取不到"))
            if segments_data is None and org_data is None:
                return unavailable(now_iso(self._now()), "该公司的画像数据暂时取不到，请稍后再试")
            output.update(
                {
                    "code": code.canonical,
                    "name": (org_data or {}).get("name") or self._name_of(code),
                    "org_name": (org_data or {}).get("org_name"),
                    "former_name": (org_data or {}).get("former_name"),
                    "security_type": (org_data or {}).get("security_type"),
                    "industry": (org_data or {}).get("industry"),
                    "csrc_industry": (org_data or {}).get("csrc_industry"),
                    "concepts": concepts,
                    "segments": segments_data,
                    "untrusted_text": True,
                }
            )
        if index_value is not None:
            canonical, index_name, digits = self._index_arg(index_value)
            if canonical in CONSTITUENTS_UNSUPPORTED:
                missing_items.append(missing("index", CONSTITUENTS_UNSUPPORTED[canonical]))
            else:
                try:
                    rows = self.sources.index_constituents(digits)
                    self._event("company_profile", "oss-ch.csindex.com.cn", ok=True)
                    index_data = normalize_index_constituents(rows, limit)
                    index_data.update({"index": canonical, "index_name": index_name})
                    if not index_data["rows"]:
                        missing_items.append(missing("index", "该指数没有成分名单"))
                    else:
                        if code is not None:
                            index_data["in_index"] = any(
                                str(row.get("成分券代码") or "").zfill(6) == code.digits for row in rows
                            )
                        output["index"] = index_data
                except Exception as exc:
                    self._event("company_profile", "oss-ch.csindex.com.cn", ok=False, error=type(exc).__name__)
                    missing_items.append(missing("index", "指数成分名单暂时取不到"))
            if not output.get("index") and code is None:
                return unavailable(now_iso(self._now()), "该指数的成分名单暂时取不到")
        status = "partial" if missing_items else "ok"
        basis_items = []
        if output.get("industry") is not None:
            basis_items.append(basis("industry", "行业为三级分类的最后一级，概念按板块标签列出"))
        if output.get("index") is not None:
            basis_items.append(basis("index", "成分股为指数公司公布的最新一期名单"))
        return envelope(
            status,
            data=output,
            as_of=now_iso(self._now()),
            basis_items=basis_items,
            missing_items=missing_items or None,
        )

    def _index_arg(self, value: Any) -> tuple[str, str, str]:
        if not isinstance(value, str) or not value.strip():
            raise CompanyError("index 必须是指数名称或代码，例如 沪深300、000300.SH")
        raw = value.strip()
        by_name = {spec["name"]: canonical for canonical, spec in INDEX_UNIVERSE.items()}
        if raw in by_name:
            canonical = by_name[raw]
            return canonical, INDEX_UNIVERSE[canonical]["name"], canonical.split(".")[0]
        try:
            code = normalize_code(raw)
        except InvalidCode as exc:
            raise CompanyError(str(exc)) from None
        if code.canonical not in INDEX_UNIVERSE:
            raise CompanyError(
                "index 暂不支持该指数；可用 "
                + "、".join(f"{spec['name']}（{canonical}）" for canonical, spec in INDEX_UNIVERSE.items())
            )
        return code.canonical, INDEX_UNIVERSE[code.canonical]["name"], code.digits


# --------------------------------------------------------------------------- helpers
def _parse_day(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:10] if fmt == "%Y-%m-%d" else raw[:8], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _direct_candidate(code: Code, names: dict[str, str]) -> list[dict[str, Any]]:
    if code.is_index:
        name = INDEX_UNIVERSE.get(code.canonical, {}).get("name")
        kind = "指数"
    else:
        name = names.get(code.canonical)
        kind = "股票"
    if not name:
        return []
    return [
        {
            "code": code.canonical,
            "name": name,
            "market": {"SH": "沪", "SZ": "深", "BJ": "北"}[code.exchange],
            "type": kind,
            "pinyin": None,
        }
    ]


def _search_local(names: dict[str, str], query: str) -> list[dict[str, Any]]:
    needle = query.strip().upper()
    matches: list[tuple[int, str, str]] = []
    for code, name in names.items():
        digits = code.split(".")[0]
        rank = None
        if needle == digits or needle == code.upper():
            rank = 0
        elif needle and needle in name.upper():
            rank = 1
        elif needle and needle in digits:
            rank = 2
        if rank is not None:
            matches.append((rank, code, name))
    matches.sort(key=lambda item: (item[0], item[1]))
    output = []
    for _, code, name in matches:
        exchange = code.split(".")[1]
        output.append(
            {
                "code": code,
                "name": name,
                "market": {"SH": "沪", "SZ": "深", "BJ": "北"}[exchange],
                "type": "股票",
                "pinyin": None,
            }
        )
    return output


def recent_report_periods(today: date, count: int) -> list[str]:
    candidates = []
    year = today.year
    while len(candidates) < count:
        for month, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
            candidate = date(year, month, day)
            if candidate <= today:
                candidates.append(candidate.isoformat())
                if len(candidates) == count:
                    break
        year -= 1
    return candidates
