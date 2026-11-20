def ratio(numerator, denominator):
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "missing": "分母为零" if not denominator else None,
    }


def valuation(eps, multiples):
    if eps <= 0 or any(m <= 0 for m in multiples):
        raise ValueError("正盈利估值需要正的年度 EPS 和 PE 假设")
    return [
        {"annual_eps": eps, "assumed_pe": m, "price": round(eps * m, 2)}
        for m in multiples
    ]


def discounted_cashflow(fcf, growth, years, rate, terminal, net_debt, shares):
    if rate <= terminal:
        raise ValueError("折现率须高于永续增长率")
    cashflows = [fcf * (1 + growth) ** i for i in range(1, years + 1)]
    discounted = [v / (1 + rate) ** i for i, v in enumerate(cashflows, 1)]
    continuing = (
        cashflows[-1] * (1 + terminal) / (rate - terminal) / (1 + rate) ** years
    )
    equity = sum(discounted) + continuing - net_debt
    return {
        "annual_cashflows": cashflows,
        "present_values": discounted,
        "terminal_present_value": continuing,
        "equity_value": equity,
        "per_share": equity / shares,
    }
