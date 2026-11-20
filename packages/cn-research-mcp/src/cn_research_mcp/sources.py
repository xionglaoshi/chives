"""The only module that calls AKShare. Every fetcher is a method, so tests inject a fake object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from cn_research_mcp.infra import ALLOWED_FUNCTIONS, LEGACY_FUNCTIONS, UpstreamError
from cn_research_mcp.symbols import Symbol

WHOLE_MARKET = "全A"  # served by stock_a_ttm_lyr, not by the stock_index_pe_lg symbol map
SYMBOL_STYLES = ("digits", "lower_prefix", "upper_prefix")


def akshare_symbol(symbol: Symbol, style: str) -> str:
    """Render a canonical symbol in the form a given AKShare function expects."""
    if style == "digits":
        return symbol.digits
    if style == "lower_prefix":
        return f"{symbol.exchange.lower()}{symbol.digits}"
    if style == "upper_prefix":
        return f"{symbol.exchange}{symbol.digits}"
    raise ValueError(f"unknown symbol style: {style}")


@dataclass(frozen=True)
class Endpoint:
    function: str
    source: str
    host: str
    symbol_style: str | None = None


# method name on Sources -> upstream description (host is the rate-limit bucket)
ENDPOINTS: dict[str, Endpoint] = {
    "profit_forecast_em": Endpoint("stock_profit_forecast_em", "eastmoney", "datacenter-web.eastmoney.com"),
    "profit_forecast_ths": Endpoint("stock_profit_forecast_ths", "ths", "basic.10jqka.com.cn", "digits"),
    "institute_recommend": Endpoint(
        "stock_institute_recommend_detail", "sina", "stock.finance.sina.com.cn", "digits"
    ),
    "research_report": Endpoint("stock_research_report_em", "eastmoney", "reportapi.eastmoney.com", "digits"),
    "stock_value": Endpoint("stock_value_em", "eastmoney", "datacenter-web.eastmoney.com", "digits"),
    "industry_pe": Endpoint("stock_industry_pe_ratio_cninfo", "cninfo", "webapi.cninfo.com.cn"),
    "index_pe": Endpoint("stock_index_pe_lg", "legulegu", "legulegu.com"),
    "a_ttm_lyr": Endpoint("stock_a_ttm_lyr", "legulegu", "legulegu.com"),
    "yjyg": Endpoint("stock_yjyg_em", "eastmoney", "datacenter.eastmoney.com"),
    "yjkb": Endpoint("stock_yjkb_em", "eastmoney", "datacenter.eastmoney.com"),
    "yjbb": Endpoint("stock_yjbb_em", "eastmoney", "datacenter-web.eastmoney.com"),
    "yysj": Endpoint("stock_yysj_em", "eastmoney", "datacenter-web.eastmoney.com"),
    "stock_news": Endpoint("stock_news_em", "eastmoney", "search-api-web.eastmoney.com", "digits"),
    "flash_cls": Endpoint("stock_news_global_cls", "cls", "www.cls.cn"),
    "flash_em": Endpoint("stock_news_global_em", "eastmoney", "np-weblist.eastmoney.com"),
    "econ_calendar": Endpoint("macro_calendar_baidu", "baidu", "finance.baidu.com"),
    "suspensions": Endpoint("stock_tfp_em", "eastmoney", "datacenter-web.eastmoney.com"),
    "irm_qa": Endpoint("stock_irm_cninfo", "cninfo", "irm.cninfo.com.cn", "digits"),
    # T119: convertible bonds, index bars/constituents, holders and business segments.
    "cb_list": Endpoint("bond_cb_list_em", "eastmoney", "datacenter-web.eastmoney.com"),
    "cb_spot": Endpoint("bond_cb_realtime_sina", "sina", "vip.stock.finance.sina.com.cn"),
    "index_bars": Endpoint("index_zh_daily_em", "eastmoney", "eastmoney-history"),
    "index_constituents": Endpoint("index_stock_cons_csindex", "csindex", "oss-ch.csindex.com.cn"),
    "holders_top10": Endpoint(
        "stock_gdfx_free_top_10_em", "eastmoney", "emweb.securities.eastmoney.com", "lower_prefix"
    ),
    "fund_holders": Endpoint("stock_fund_stock_holder", "sina", "vip.stock.finance.sina.com.cn", "digits"),
    "business_segments": Endpoint(
        "stock_zygc_em", "eastmoney", "emweb.securities.eastmoney.com", "upper_prefix"
    ),
}


def _ak(name: str, *args: Any, **kwargs: Any) -> pd.DataFrame:
    if name not in ALLOWED_FUNCTIONS and name not in LEGACY_FUNCTIONS:
        raise UpstreamError("upstream_error", f"akshare function not allowed: {name}")
    import akshare

    return getattr(akshare, name)(*args, **kwargs)


class Sources:
    def profit_forecast_em(self) -> pd.DataFrame:
        return _ak("stock_profit_forecast_em")

    def profit_forecast_ths(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["profit_forecast_ths"].symbol_style or "digits"
        return _ak(
            "stock_profit_forecast_ths",
            symbol=akshare_symbol(symbol, style),
            indicator="预测年报每股收益",
        )

    def institute_recommend(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["institute_recommend"].symbol_style or "digits"
        return _ak("stock_institute_recommend_detail", symbol=akshare_symbol(symbol, style))

    def research_report(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["research_report"].symbol_style or "digits"
        return _ak("stock_research_report_em", symbol=akshare_symbol(symbol, style))

    def stock_value(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["stock_value"].symbol_style or "digits"
        return _ak("stock_value_em", symbol=akshare_symbol(symbol, style))

    def industry_pe(self, date_yyyymmdd: str) -> pd.DataFrame:
        return _ak("stock_industry_pe_ratio_cninfo", symbol="证监会行业分类", date=date_yyyymmdd)

    def index_pe(self, index_name: str) -> pd.DataFrame:
        return _ak("stock_index_pe_lg", symbol=index_name)

    def a_ttm_lyr(self) -> pd.DataFrame:
        return _ak("stock_a_ttm_lyr")

    def yjyg(self, date_yyyymmdd: str) -> pd.DataFrame:
        return _ak("stock_yjyg_em", date=date_yyyymmdd)

    def yjkb(self, date_yyyymmdd: str) -> pd.DataFrame:
        return _ak("stock_yjkb_em", date=date_yyyymmdd)

    def yjbb(self, date_yyyymmdd: str) -> pd.DataFrame:
        return _ak("stock_yjbb_em", date=date_yyyymmdd)

    def yysj(self, date_yyyymmdd: str) -> pd.DataFrame:
        return _ak("stock_yysj_em", symbol="沪深A股", date=date_yyyymmdd)

    def stock_news(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["stock_news"].symbol_style or "digits"
        return _ak("stock_news_em", symbol=akshare_symbol(symbol, style))

    def flash_cls(self) -> pd.DataFrame:
        try:
            return _ak("stock_news_global_cls", symbol="全部")
        except AttributeError:
            return _ak("stock_info_global_cls", symbol="全部")

    def flash_em(self) -> pd.DataFrame:
        try:
            return _ak("stock_news_global_em")
        except AttributeError:
            return _ak("stock_info_global_em")

    def econ_calendar(self, date_yyyymmdd: str) -> pd.DataFrame:
        try:
            return _ak("macro_calendar_baidu", date=date_yyyymmdd)
        except AttributeError:
            return _ak("news_economic_baidu", date=date_yyyymmdd)

    def suspensions(self, date_yyyymmdd: str) -> pd.DataFrame:
        return _ak("stock_tfp_em", date=date_yyyymmdd)

    def irm_qa(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["irm_qa"].symbol_style or "digits"
        return _ak("stock_irm_cninfo", symbol=akshare_symbol(symbol, style))

    # T119 -----------------------------------------------------------------
    def cb_list(self) -> pd.DataFrame:
        """Eastmoney convertible-bond terms table. AKShare 1.20.65 renamed bond_zh_cov."""
        try:
            return _ak("bond_cb_list_em")
        except AttributeError:
            return _ak("bond_zh_cov")

    def cb_spot(self) -> pd.DataFrame:
        """Sina convertible-bond realtime snapshot. AKShare 1.20.65 renamed bond_zh_hs_cov_spot."""
        try:
            return _ak("bond_cb_realtime_sina")
        except AttributeError:
            return _ak("bond_zh_hs_cov_spot")

    def index_bars(self, index_symbol: str, start_yyyymmdd: str, end_yyyymmdd: str) -> pd.DataFrame:
        """Eastmoney daily index bars. AKShare 1.20.65 renamed stock_zh_index_daily_em."""
        try:
            return _ak(
                "index_zh_daily_em", symbol=index_symbol, start_date=start_yyyymmdd, end_date=end_yyyymmdd
            )
        except AttributeError:
            return _ak(
                "stock_zh_index_daily_em",
                symbol=index_symbol,
                start_date=start_yyyymmdd,
                end_date=end_yyyymmdd,
            )

    def index_constituents(self, index_digits: str) -> pd.DataFrame:
        return _ak("index_stock_cons_csindex", symbol=index_digits)

    def holders_top10(self, symbol: Symbol, date_yyyymmdd: str) -> pd.DataFrame:
        style = ENDPOINTS["holders_top10"].symbol_style or "lower_prefix"
        return _ak(
            "stock_gdfx_free_top_10_em", symbol=akshare_symbol(symbol, style), date=date_yyyymmdd
        )

    def fund_holders(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["fund_holders"].symbol_style or "digits"
        return _ak("stock_fund_stock_holder", symbol=akshare_symbol(symbol, style))

    def business_segments(self, symbol: Symbol) -> pd.DataFrame:
        style = ENDPOINTS["business_segments"].symbol_style or "upper_prefix"
        return _ak("stock_zygc_em", symbol=akshare_symbol(symbol, style))


def supported_index_names(candidates: tuple[str, ...]) -> tuple[str, ...]:
    """Keep only index names that stock_index_pe_lg's own symbol map knows (offline check); 全A always stays."""
    try:
        import inspect

        import akshare

        text = inspect.getsource(akshare.stock_index_pe_lg)
    except Exception:  # noqa: BLE001 - if the source is unavailable keep the full list
        return candidates
    return tuple(name for name in candidates if name == WHOLE_MARKET or f'"{name}"' in text)
