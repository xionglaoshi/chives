---
name: dividend-analysis
description: 分红与高股息分析：股息率、分红可持续性、除权除息、A 股红利税与预案/实施阶段、高股息陷阱。 Dividend stock analysis for income, dividend-growth, and shareholder-return strategies, including yield quality, payout sustainability, ex-dividend mechanics, A-share dividend tax and 预案/实施 stages, and yield-trap checks. Research only; not investment advice.
---

# Dividend Analysis

## Purpose

Use this skill when the user asks about dividend stocks, income portfolios, dividend
growth, high-yield screening, payout safety, ex-dividend dates, or whether a
dividend is sustainable. The goal is to separate durable shareholder returns from
yield traps.

Dividend analysis should never stop at headline yield. A good answer explains how
the dividend is funded, how stable the underlying business is, whether management
has room to keep paying, and how valuation and tax change the expected total
return.

## Core Questions

1. What is the current cash yield, and is it normal for this company or sector?
2. Is the payout covered by earnings, operating cash flow, and free cash flow?
3. Is the balance sheet strong enough to absorb a down cycle?
4. Has management grown, held, cut, or suspended the dividend across cycles?
5. Does the valuation still leave room for total return after taxes and reinvestment assumptions?

## Key Metrics

| Metric | Formula | Healthy Signal | Warning Signal |
|--------|---------|----------------|----------------|
| Dividend yield | annual DPS / current price | Above peer median with stable coverage | Extremely high vs history or peers |
| Earnings payout ratio | dividends / net income, or DPS / EPS | Roughly 30–70% for mature non-financials is a common rule of thumb, not a validated cutoff | Above 90%, negative earnings |
| Free-cash-flow payout | dividends / FCF | Below 70% through a cycle | Dividend exceeds FCF for 2+ years |
| CFO coverage | operating cash flow / dividends paid | Above 1.5x | Below 1.0x |
| Dividend CAGR | DPS growth over 3/5/10 years | Positive and below EPS/FCF growth | Growth funded by leverage |
| Net debt / EBITDA | net debt / EBITDA | Sector-appropriate leverage | Leverage rising while payout rises |
| Buyback plus dividend yield | (dividends + net buybacks) / market cap | Balanced capital return | Buybacks funded by debt at high valuation |

The thresholds in this table are screening heuristics, not statistically validated
cut-offs; state them as parameters and check them against the company's own history
and peers. For REITs, utilities, banks, MLPs, and insurers, adapt the payout metric to the
sector. For example, use AFFO payout for REITs, distributable cash flow for MLPs,
and regulatory capital ratios for banks and insurers.

## A-share specifics

**预案 vs 实施.** A dividend plan (分红预案/利润分配预案) is a board proposal and
can still change before the shareholders' meeting. Only the implemented
distribution (实施公告) is a fact. Label every figure as 预案, 股东大会通过, or
已实施, and give the announcement date.

**Unit conversion.** A-share plans usually state "每 10 股派 X 元（含税）". DPS =
X / 10. Do not compare the "每 10 股" number with a per-share price without
converting. The same announcement may also contain 送股/转增, which changes the
share count and the ex-price but is not cash.

**Dates.** Keep four dates separate: 预案公告日, 股权登记日 (record date),
除权除息日 (ex-date), and 派息日 (pay date). The ex-date price is adjusted
mechanically; a price drop on the ex-date is not a loss caused by the dividend.

**Tax (mainland individual, A-shares).** Dividend income is taxed by holding
period: holding more than 1 year is temporarily exempt; 1 month to 1 year is
counted at 50% of the dividend in taxable income (effective 10%); 1 month or less
is fully taxable (effective 20%). The tax is settled when the shares are sold, so
the holding period that matters is the one at sale. Source: 财税〔2015〕101 号
(effective 2015-09-08). Verify with the broker's current withholding practice.

**Buyback vs dividend.** A buyback that is cancelled reduces share count and can
raise EPS/DPS per share; a buyback used for an employee plan is compensation and
does not necessarily reduce the count. Read the purpose, not just the amount.

**Stock Connect.** For mainland individual investors buying HK stocks through
Stock Connect, dividend withholding is 20% for both H shares and non-H shares;
non-H shares are withheld by ChinaClear. Do not use a 10% rate for individuals.
Source: 财税〔2014〕81 号.

## Analysis Workflow

### Step 1: Normalize the Dividend

- Use the latest **implemented** annual or interim distribution for recurring
  payments; keep 预案 separate and label it.
- Separate ordinary dividends from special dividends.
- Check whether the latest declared dividend is annual, semiannual, quarterly,
  monthly, or irregular.
- For ADRs and cross-listed shares, account for depositary ratios; for A-shares,
  apply the holding-period tax rules above; for Stock Connect, apply the 20%
  withholding rate.

```python
annual_dividend = regular_dividend_per_period * payments_per_year
dividend_yield = annual_dividend / current_price
```

### Step 2: Check Coverage

Start with earnings coverage, then confirm with cash coverage.

```python
earnings_payout = dividends_paid / net_income
fcf_payout = dividends_paid / free_cash_flow
cfo_coverage = operating_cash_flow / dividends_paid
```

Interpretation:

- Good: net income, CFO, and FCF all cover dividends across multiple years.
- Watch: earnings cover dividends but FCF does not, especially during capex-heavy periods.
- Avoid: dividends are paid while both earnings and FCF are negative, unless there is a clear one-time reason and a strong balance sheet.

### Step 3: Diagnose Dividend Growth Quality

Dividend growth is high quality when it follows business growth.

```python
dividend_cagr = (dps_end / dps_start) ** (1 / years) - 1
eps_cagr = (eps_end / eps_start) ** (1 / years) - 1
fcf_cagr = (fcf_end / fcf_start) ** (1 / years) - 1
```

Quality rules:

- Dividend CAGR below EPS and FCF CAGR usually leaves room for future increases.
- Dividend CAGR above EPS/FCF CAGR means payout ratio is expanding.
- Flat dividend with rising FCF may imply hidden capacity or conservative management.
- Repeated small increases can still be fragile if leverage is rising.

### Step 4: Check Balance Sheet Flexibility

Look for the ability to maintain dividends during stress.

| Item | Why It Matters |
|------|----------------|
| Cash and short-term investments | Near-term cushion |
| Net debt / EBITDA | Debt burden against operating earnings |
| Interest coverage | Ability to service debt before shareholder returns |
| Debt maturity wall | Refinancing risk in high-rate environments |
| Credit rating or covenant language | External constraints on payout policy |

### Step 5: Separate Dividend Yield from Total Return

Dividend stocks can underperform if the yield comes from a falling price. Always connect income to valuation and growth.

```python
expected_total_return = dividend_yield + expected_eps_growth + valuation_rerating
```

Do not present this as a guarantee. Use it as a scenario framework, with explicit
assumptions and a data date.

## Yield-Trap Checklist

Flag a potential yield trap when several of these are true:

- Dividend yield is more than 2x the company's 5-year median or sector median.
- Payout ratio is above 90%, or FCF payout is above 100%.
- Revenue, EPS, or FCF has declined for 2+ years.
- Net debt / EBITDA is rising while interest coverage is falling.
- Management has recently issued equity or debt while maintaining dividends.
- The stock price fell before the yield became attractive.
- Dividend history includes cuts, suspensions, or frequent special dividends labeled as ordinary income.
- Sector faces structural pressure, regulation risk, or commodity down-cycle exposure.

## Strategy Types

### Dividend Growth

Prioritize moderate yield, strong dividend CAGR, low payout ratio, and durable business quality.

Good for users seeking compounding and lower cut risk.

### High-Yield Quality

Prioritize yield, but require cash coverage, balance sheet resilience, and sector-aware payout norms.

Good for users seeking current income, but the answer must discuss cut risk.

### Shareholder Yield

Combine dividends, net buybacks, and debt reduction.

Useful when companies return capital mostly through buybacks rather than cash dividends.

```python
shareholder_yield = dividend_yield + net_buyback_yield + debt_paydown_yield
```

### Dividend Capture

Buying before the ex-dividend date only to collect the dividend is not a free-money strategy. Prices usually adjust around the ex-dividend date, and taxes, spreads, and slippage can erase the gross dividend. In A-shares the ex-price is adjusted mechanically and the holding-period tax can exceed the gross dividend for very short holds.

Use this only as an event-risk analysis, not as a default recommendation.

## Data Sources

| Market | Useful Fields |
|--------|---------------|
| A-shares | `company_financials` for net income, CFO, and dividends paid; `company_announcements` (检索公告) with `company_announcements(url=...)` for 预案/实施公告, record/ex/pay dates, and 每 10 股派息 |
| A-shares (optional cross-check) | If the session has a tushare interface: `dividend.cash_div_tax`, `record_date`, `ex_date`, `pay_date`; `daily_basic.dv_ttm`; `cashflow.c_pay_dist_dpcp_int_exp` |
| US/HK | yfinance `Ticker.dividends`, `Ticker.info`, financial statements, cash flow; HKEXnews for the official distribution announcement |
| ETFs | distribution yield, SEC yield, holdings yield, expense ratio, distribution history |
| REITs | FFO, AFFO, occupancy, debt maturities, AFFO payout |

When live data is unavailable, state the limitation and provide the analysis template instead of inventing dividend figures.

## Output Template

```markdown
### Dividend Analysis: [ticker/company]  (as_of YYYY-MM-DD)

**Data basis:** [latest implemented distribution / 预案 only / missing]

**Verdict:** [sustainable / watchlist / yield-trap risk] — framework-conditional

| Metric | Value | Period / date | Interpretation |
|--------|-------|---------------|----------------|
| Dividend yield | ... | ... | ... |
| Earnings payout | ... | ... | ... |
| FCF payout | ... | ... | ... |
| Dividend growth | ... | ... | ... |
| Balance sheet | ... | ... | ... |

**What supports the dividend**
- ...

**What could break the dividend**
- ...

**Scenario view**
- Base: ...
- Downside: ...
- Upside: ...

**Research note:** This is investment research, not live trading advice.
```

## Common Mistakes

- Treating high yield as cheap valuation without checking why the price fell.
- Mixing special dividends with regular dividends.
- Comparing REIT payout ratios to ordinary industrial companies.
- Ignoring withholding tax, ADR ratios, currency conversion, or ETF expense drag.
- Using a 预案 as if it were an implemented distribution.
- Mixing 每 10 股派息 with per-share DPS, or treating 送股/转增 as cash.
- Forgetting that ex-dividend capture is usually offset by price adjustment and transaction costs.
- Recommending a dividend stock without discussing total return and dividend-cut risk.
