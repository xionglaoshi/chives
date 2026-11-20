from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from math import isfinite
from pydantic import BaseModel, Field
from .market import daily, gateway, symbol
from . import models
from .storage import snapshot, stamp


def financial_ratio(numerator: float, denominator: float) -> dict:
    """Calculate a financial ratio with original values; a zero denominator returns missing."""
    if not all(map(isfinite, (numerator, denominator))):
        raise ValueError("数值须有限")
    return models.ratio(numerator, denominator)


def valuation_scenarios(annual_eps: float, multiples: list[float]) -> dict:
    """Calculate explicit annual EPS × PE price scenarios in the EPS currency per share."""
    if not 1 <= len(multiples) <= 20 or not all(
        map(isfinite, [annual_eps, *multiples])
    ):
        raise ValueError("估值假设无效")
    return {
        "method": "年度 EPS × 假设 PE",
        "scenarios": models.valuation(annual_eps, multiples),
    }


def discounted_cashflow(
    fcf: float,
    growth: float,
    years: int,
    rate: float,
    terminal: float,
    net_debt: float,
    shares: float,
) -> dict:
    """Discount FCFF, subtract net debt and return explicit annual flows and equity value per share. Rates are decimals."""
    if (
        not all(map(isfinite, [fcf, growth, rate, terminal, net_debt, shares]))
        or shares <= 0
        or not 1 <= years <= 40
        or min(rate, growth, terminal) <= -1
    ):
        raise ValueError("股本、年数或增长率/折现率无效")
    return models.discounted_cashflow(
        fcf, growth, years, rate, terminal, net_debt, shares
    )


def ma_backtest(
    code: str,
    fast: int = 5,
    slow: int = 20,
    capital: float = 100000,
    fee: float = 0.001,
) -> dict:
    """Replay the legacy next-open moving-average strategy; returns actual trade list and equity path."""
    from .replay import replay

    if (
        not 1 <= fast < slow < 250
        or not isfinite(capital)
        or capital <= 0
        or not 0 <= fee < 1
    ):
        raise ValueError("均线、资金或费率不合规")
    return replay(symbol(code), fast, slow, capital, fee)


def price_history(
    code: str,
    days: int = 120,
    adjust: Literal["none", "qfq", "hfq"] = "qfq",
    as_of: str = "",
) -> dict:
    """Retrieve dated market bars, source and adjustment basis."""
    return daily(code, days, adjust, as_of)


class Condition(BaseModel):
    field: Literal[
        "price",
        "change_pct",
        "pb_mrq",
        "turnover_pct",
        "volume_ratio",
        "pe_dynamic",
        "pe_ttm",
    ]
    op: Literal["gt", "lt"]
    value: float = Field(allow_inf_nan=False)


def screen_stocks(
    conditions: list[Condition], codes: list[str] | None = None, limit: int = 30
) -> dict:
    """Filter a watchlist or the current A-share universe; distinguish excluded, matched and missing observations."""
    if (
        not 1 <= len(conditions) <= 12
        or not 1 <= limit <= 100
        or (codes is not None and not 1 <= len(codes) <= 20)
    ):
        raise ValueError("条件、样本或分页超限")
    if codes is None:
        from .universe import universe

        return universe(conditions, limit)
    codes = list(dict.fromkeys(symbol(c) for c in codes))
    result = gateway.call("market_quote", {"codes": codes})
    quotes = {r["code"]: r for r in (result.get("data") or {}).get("quotes", [])}
    rows = []
    if any(t.field == "pe_dynamic" for t in conditions):
        from .earnings import annualized_eps

        for quote in quotes.values():
            day = str(quote.get("quote_time", ""))[:10]
            try:
                eps = annualized_eps(day)["values"].get(quote["code"][:6])
                quote["pe_dynamic"] = (
                    quote["price"] / eps if eps and quote.get("price") else None
                )
            except (ValueError, KeyError, OSError, TypeError):
                quote["pe_dynamic"] = None
    for c in codes:
        r = quotes.get(c, {})
        checks = []
        for t in conditions:
            v = r.get(t.field)
            checks.append(
                None
                if v is None or result.get("stale")
                else v > t.value
                if t.op == "gt"
                else v < t.value
            )
        rows.append(
            dict(
                code=c,
                values={t.field: r.get(t.field) for t in conditions},
                checks=checks,
                status="excluded"
                if False in checks
                else "unknown"
                if None in checks
                else "match",
                quote_time=r.get("quote_time"),
            )
        )
    return dict(
        source="Chives market_quote",
        rows=rows,
        unknown_count=sum(r["status"] == "unknown" for r in rows),
    )


def equity_review(code: str) -> dict:
    """Freeze multi-source research inputs, calculate same-period revenue growth/cash conversion, and six evaluation checks."""
    from .evaluate import evaluate
    from .filing_index import announcements

    code = symbol(code)
    calls = {
        "quote": ("market_quote", {"codes": [code]}),
        "financial": (
            "company_financials",
            {"code": code, "statement": "indicators", "periods": 5},
        ),
        "income": (
            "company_financials",
            {"code": code, "statement": "income", "periods": 5},
        ),
        "reports": ("company_reports", {"code": code, "limit": 5}),
        "consensus": ("company_consensus", {"code": code}),
    }
    evidence = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            k: pool.submit(gateway.call, tool, args)
            for k, (tool, args) in calls.items()
        }
        futures.update(
            announcements=pool.submit(announcements, code),
            daily=pool.submit(daily, code, 90, "qfq"),
        )
        for k, f in futures.items():
            try:
                evidence[k] = f.result()
            except Exception as exc:
                evidence[k] = dict(status="unavailable", reason=type(exc).__name__)
    first = lambda k: (evidence[k].get("data") or {}).get("periods") or []
    indicators = first("financial")
    income = first("income")
    f = indicators[0] if indicators else {}
    cur = income[0] if income else {}
    period = cur.get("report_date", "")
    prior = next(
        (
            r
            for r in income[1:]
            if period and r.get("report_date") == str(int(period[:4]) - 1) + period[4:]
        ),
        {},
    )
    base = prior.get("operating_revenue_yuan")
    rev = cur.get("operating_revenue_yuan")
    cash = f.get("operating_cash_flow_yuan")
    profit = cur.get("net_profit_yuan")
    facts = dict(
        period=f.get("report_date"),
        reported=f.get("announce_date"),
        revenue_inputs=[cur.get("report_date"), rev, prior.get("report_date"), base],
        revenue_yoy_pct=(rev / base - 1) * 100
        if rev is not None and base and base > 0
        else None,
        cash_to_profit=financial_ratio(cash, profit)
        if cash is not None and profit is not None and period == f.get("report_date")
        else None,
    )
    key = snapshot(dict(code=code, observed=stamp(), result=evidence))
    return dict(
        code=code,
        snapshot_id=key,
        facts=facts,
        checks=evaluate(evidence),
        coverage={k: v.get("status") for k, v in evidence.items()},
    )
