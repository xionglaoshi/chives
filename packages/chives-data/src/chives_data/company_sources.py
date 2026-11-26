"""Upstream fetchers for the company/research tools (T142).

Every AKShare call is wrapped by the shared host governor (thread pool + hard
timeout + per-host rate limit + circuit breaker).  Direct HTTP calls use the
same governor.  No module below this one talks to an upstream host.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from . import config
from .company_parse import normalize_suggest
from .transport import HostGovernor

EASTMONEY_DATA = "datacenter.eastmoney.com"
EASTMONEY_DC_WEB = "datacenter-web.eastmoney.com"
EASTMONEY_EMWEB = "emweb.securities.eastmoney.com"
EASTMONEY_REPORT = "reportapi.eastmoney.com"
EASTMONEY_SEARCH = "searchapi.eastmoney.com"
SINA_QUOTE = "quotes.sina.cn"
SINA_RATING = "stock.finance.sina.com.cn"
SINA_FUND_HOLDER = "vip.stock.finance.sina.com.cn"
THS = "basic.10jqka.com.cn"
CNINFO = "webapi.cninfo.com.cn"
LEGU = "legulegu.com"
CSINDEX = "oss-ch.csindex.com.cn"
BAIDU = "gushitong.baidu.com"

LOCKUP_MARKET_COLUMNS = (
    "SECURITY_CODE,SECURITY_NAME_ABBR,FREE_DATE,CURRENT_FREE_SHARES,ABLE_FREE_SHARES,"
    "LIFT_MARKET_CAP,FREE_RATIO,NEW,FREE_SHARES_TYPE,TOTAL_RATIO,NON_FREE_SHARES,BATCH_HOLDER_NUM"
)
LOCKUP_MARKET_PAGE_SIZE = 500
LOCKUP_MARKET_MAX_PAGES = 20


def records(frame: Any) -> list[dict[str, Any]]:
    """DataFrame -> plain records; an empty/non-frame value becomes an empty list."""
    if frame is None:
        return []
    to_dict = getattr(frame, "to_dict", None)
    if to_dict is None:
        return list(frame) if isinstance(frame, list) else []
    if getattr(frame, "empty", False):
        return []
    return list(to_dict(orient="records"))


class AkShareCompanyAdapter:
    """All AKShare entry points used by the company tools, one method per endpoint."""

    def __init__(self, governor: HostGovernor) -> None:
        self.governor = governor

    def _call(self, host: str, name: str, **kwargs: Any) -> list[dict[str, Any]]:
        import akshare as ak

        fn: Callable[..., Any] = getattr(ak, name)

        def call() -> Any:
            return fn(**kwargs)

        return records(self.governor.run_external(host, call, timeout=config.AKSHARE_TIMEOUT))

    def a_share_names(self) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_DC_WEB, "stock_zh_a_gdhs", symbol="最新")

    def financial_indicators(self, code: str) -> list[dict[str, Any]]:
        return self._call(
            EASTMONEY_DATA,
            "stock_financial_analysis_indicator_em",
            symbol=code,
            indicator="按报告期",
        )

    def financial_statement(self, symbol: str, indicator: str) -> list[dict[str, Any]]:
        return self._call(SINA_QUOTE, "stock_financial_report_sina", symbol=symbol, indicator=indicator)

    def stock_valuation(self, digits: str) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_DC_WEB, "stock_value_em", symbol=digits)

    def baidu_valuation(self, digits: str, indicator: str, period: str) -> list[dict[str, Any]]:
        return self._call(
            BAIDU,
            "stock_zh_valuation_baidu",
            symbol=digits,
            indicator=indicator,
            period=period,
        )

    def industry_valuation(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self._call(
            CNINFO,
            "stock_industry_pe_ratio_cninfo",
            symbol="证监会行业分类",
            date=date_yyyymmdd,
        )

    def index_valuation(self, name: str) -> list[dict[str, Any]]:
        return self._call(LEGU, "stock_index_pe_lg", symbol=name)

    def all_a_valuation(self) -> list[dict[str, Any]]:
        return self._call(LEGU, "stock_a_ttm_lyr")

    def profit_forecast_em(self) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_DC_WEB, "stock_profit_forecast_em")

    def profit_forecast_ths(self, digits: str, indicator: str) -> list[dict[str, Any]]:
        return self._call(
            THS,
            "stock_profit_forecast_ths",
            symbol=digits,
            indicator=indicator,
        )

    def ratings(self, digits: str) -> list[dict[str, Any]]:
        return self._call(SINA_RATING, "stock_institute_recommend_detail", symbol=digits)

    def reports(self, digits: str) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_REPORT, "stock_research_report_em", symbol=digits)

    def earnings(self, kind: str, date_yyyymmdd: str) -> list[dict[str, Any]]:
        name = {"forecast": "stock_yjyg_em", "express": "stock_yjkb_em", "report": "stock_yjbb_em"}[kind]
        host = EASTMONEY_DATA if kind in {"forecast", "express"} else EASTMONEY_DC_WEB
        return self._call(host, name, date=date_yyyymmdd)

    def schedule(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self._call(
            EASTMONEY_DC_WEB,
            "stock_yysj_em",
            symbol="沪深A股",
            date=date_yyyymmdd,
        )

    def holders_top10(self, symbol: str, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self._call(
            EASTMONEY_EMWEB,
            "stock_gdfx_free_top_10_em",
            symbol=symbol,
            date=date_yyyymmdd,
        )

    def fund_holders(self, digits: str) -> list[dict[str, Any]]:
        return self._call(SINA_FUND_HOLDER, "stock_fund_stock_holder", symbol=digits)

    def holder_count(self, digits: str) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_DC_WEB, "stock_zh_a_gdhs_detail_em", symbol=digits)

    def lockup(self, digits: str) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_DC_WEB, "stock_restricted_release_queue_em", symbol=digits)

    def segments(self, symbol: str) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_EMWEB, "stock_zygc_em", symbol=symbol)

    def index_constituents(self, digits: str) -> list[dict[str, Any]]:
        return self._call(CSINDEX, "index_stock_cons_csindex", symbol=digits)


class CompanySources:
    """Facade used by CompanyTools; tests inject a fake with the same methods."""

    def __init__(self, governor: HostGovernor, akshare: AkShareCompanyAdapter | None = None) -> None:
        self.governor = governor
        self.akshare = akshare or AkShareCompanyAdapter(governor)

    # -- search and the shared code -> name table -------------------------
    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        text = self.governor.request(
            EASTMONEY_SEARCH,
            "/api/suggest/get",
            params={"input": query, "type": "14", "count": str(limit)},
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        return normalize_suggest(payload)

    def a_share_names(self) -> list[dict[str, Any]]:
        return self.akshare.a_share_names()

    # -- financials -------------------------------------------------------
    def financial_indicators(self, code: str) -> list[dict[str, Any]]:
        return self.akshare.financial_indicators(code)

    def financial_statement(self, exchange: str, digits: str, statement: str) -> list[dict[str, Any]]:
        indicator = {"income": "利润表", "balance": "资产负债表", "cashflow": "现金流量表"}[statement]
        return self.akshare.financial_statement(f"{exchange.lower()}{digits}", indicator)

    # -- valuation --------------------------------------------------------
    def stock_valuation(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.stock_valuation(digits)

    def baidu_valuation(self, digits: str, indicator: str, period: str) -> list[dict[str, Any]]:
        return self.akshare.baidu_valuation(digits, indicator, period)

    def industry_valuation(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self.akshare.industry_valuation(date_yyyymmdd)

    def index_valuation(self, name: str) -> list[dict[str, Any]]:
        return self.akshare.index_valuation(name)

    def all_a_valuation(self) -> list[dict[str, Any]]:
        return self.akshare.all_a_valuation()

    # -- consensus, reports ----------------------------------------------
    def profit_forecast_em(self) -> list[dict[str, Any]]:
        return self.akshare.profit_forecast_em()

    def profit_forecast_ths(self, digits: str, indicator: str) -> list[dict[str, Any]]:
        return self.akshare.profit_forecast_ths(digits, indicator)

    def ratings(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.ratings(digits)

    def reports(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.reports(digits)

    # -- earnings ---------------------------------------------------------
    def earnings(self, kind: str, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self.akshare.earnings(kind, date_yyyymmdd)

    def schedule(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self.akshare.schedule(date_yyyymmdd)

    # -- holders ----------------------------------------------------------
    def holders_top10(self, exchange: str, digits: str, date_yyyymmdd: str) -> list[dict[str, Any]]:
        symbol = f"{exchange.lower()}{digits}"
        return self.akshare.holders_top10(symbol, date_yyyymmdd)

    def fund_holders(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.fund_holders(digits)

    def holder_count(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.holder_count(digits)

    def lockup(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.lockup(digits)

    def lockup_market(self, start: str, end: str) -> list[dict[str, Any]]:
        """Whole-market release events for a date range, one upstream page at a time."""
        rows: list[dict[str, Any]] = []
        page = 1
        pages = 1
        while page <= pages and page <= LOCKUP_MARKET_MAX_PAGES:
            text = self.governor.request(
                EASTMONEY_DC_WEB,
                "/api/data/v1/get",
                params={
                    "sortColumns": "FREE_DATE,SECURITY_CODE",
                    "sortTypes": "1,1",
                    "pageSize": str(LOCKUP_MARKET_PAGE_SIZE),
                    "pageNumber": str(page),
                    "reportName": "RPT_LIFT_STAGE",
                    "columns": LOCKUP_MARKET_COLUMNS,
                    "source": "WEB",
                    "client": "WEB",
                    "filter": f"(FREE_DATE>='{start}')(FREE_DATE<='{end}')",
                },
                headers={"Referer": "https://data.eastmoney.com/dxf/detail.html"},
            )
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                break
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict):
                break
            pages = int(result.get("pages") or 1)
            data = result.get("data")
            if isinstance(data, list):
                rows.extend(item for item in data if isinstance(item, dict))
            page += 1
        return rows

    # -- profile ----------------------------------------------------------
    def segments(self, exchange: str, digits: str) -> list[dict[str, Any]]:
        return self.akshare.segments(f"{exchange.upper()}{digits}")

    def index_constituents(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.index_constituents(digits)

    def org_info(self, code: str) -> list[dict[str, Any]]:
        return self._datacenter("RPT_F10_BASIC_ORGINFO", f'(SECUCODE="{code}")')

    def concepts(self, code: str) -> list[dict[str, Any]]:
        return self._datacenter("RPT_F10_CORETHEME_BOARDTYPE", f'(SECUCODE="{code}")')

    def _datacenter(self, report: str, filter_expr: str) -> list[dict[str, Any]]:
        text = self.governor.request(
            EASTMONEY_DATA,
            "/securities/api/data/v1/get",
            params={
                "reportName": report,
                "columns": "ALL",
                "filter": filter_expr,
                "pageNumber": "1",
                "pageSize": "100",
                "source": "F10",
                "client": "PC",
            },
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        result = payload.get("result") if isinstance(payload, dict) else None
        data = result.get("data") if isinstance(result, dict) else None
        return list(data) if isinstance(data, list) else []
