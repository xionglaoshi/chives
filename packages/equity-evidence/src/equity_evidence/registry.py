"""MCP capabilities are installed in bot_assets only when the expert selects them."""

from .factors import factor_catalog, factor_values
from .evidence import filing_evidence, evidence_page, cash_quality, research_snapshot
from .research import (
    financial_ratio,
    valuation_scenarios,
    discounted_cashflow,
    price_history,
    screen_stocks,
    equity_review,
    ma_backtest,
)
from .institutional import research_report_lookup, special_financials
from .fund_tools import (
    fund_ranking,
    fund_holdings,
    fund_holdings_changes,
    fund_study_job,
)

TOOLS = (
    factor_catalog,
    factor_values,
    filing_evidence,
    evidence_page,
    cash_quality,
    research_snapshot,
    financial_ratio,
    valuation_scenarios,
    discounted_cashflow,
    price_history,
    screen_stocks,
    equity_review,
    ma_backtest,
    research_report_lookup,
    special_financials,
    fund_ranking,
    fund_holdings,
    fund_holdings_changes,
    fund_study_job,
)
