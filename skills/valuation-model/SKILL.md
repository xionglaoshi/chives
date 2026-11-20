---
name: valuation-model
description: 估值方法：判断贵不贵、估值分位与合理价位，DCF/DDM/分部估值，PE-Band、PB-ROE、EV/EBITDA 相对估值，敏感性分析与估值陷阱识别。 Valuation methodology — absolute valuation with DCF / DDM / SOTP, relative valuation with PE-Band / PB-ROE / EV-EBITDA, sensitivity analysis, and valuation-trap detection. Outputs assumption-driven ranges and scenarios, and can state a rating and target price with assumptions and falsifiers.
---

# Valuation Methodology

## Overview

A valuation is a set of explicit assumptions about the future, discounted back at a
risk-adjusted rate, cross-checked against how the market prices comparable
businesses. This skill covers absolute valuation (`DCF / DDM / SOTP`) and relative
valuation (`PE / PB / EV-EBITDA`), sensitivity analysis, and a checklist for
valuation traps.

**Output rule:** report a scenario range and the assumptions that drive it; when the user
wants a view you may also give a rating and a target price (a point plus a range),
always with the assumptions and what would falsify it.

## Data inputs and freshness

Before any calculation, write a table of inputs with value, period, and `as_of`.
Do not use a stale risk-free rate, a stale price, or a consensus EPS without its
snapshot date.

| Market | Typical inputs | Where to get them |
|--------|----------------|-------------------|
| A-share | Financial statements, share count, price, market cap, Beta | `company_financials`, `market_bars`, `company_valuation(scope="stock")`, `company_search`; filings via cninfo/exchange `web_fetch` |
| HK | Filing data, price, shares, dividends | HKEXnews/company IR via `web_fetch`; price via `market_global(symbols=["hk00700"])` when available |
| US | 10-K/10-Q, price, shares, dividends | SEC EDGAR/company IR via `web_fetch`; price via `market_global(symbols=["usAAPL"])` when available |
| Risk-free rate | 10-year government yield on the valuation date | Fetch the current yield; for A-share use the 10Y Chinese government bond, for HK/US use the local sovereign curve. Record date and source. |

If a data tool is unavailable, use `web_fetch` on the primary filing and say what
you could not get. Never fill a missing input with a "typical" number without
labelling it as an assumption.

## Absolute Valuation Methods

### 1. DCF (Discounted Cash Flow)

**Core formulas**:

```
Enterprise value = Σ FCFF_t / (1+WACC)^t + TV / (1+WACC)^n
Equity value = EV - interest-bearing debt - minority interest - preferred stock
               + cash and non-operating assets
Per-share value = equity value / diluted shares outstanding
```

Do not use `EV - net debt` as a complete bridge for A-shares: minority interests
and non-operating assets (investment properties, associates, excess cash) are often
material.

**Free cash flow to the firm**:

```
FCFF = EBIT × (1 - tax rate) + depreciation & amortization
       - capital expenditure - increase in net working capital

Equivalent from the cash-flow statement (classification-dependent):
FCFF = CFO + interest paid × (1 - tax rate) - capex   # if interest paid is in operating cash flow
FCFF = CFO - capex                                    # if interest paid is in financing cash flow
```

`CFO - capex` is not automatically FCFF. Check where interest paid is classified:
under US GAAP it is usually operating, so add back after-tax interest; under CAS
it is usually financing, so CFO is already before interest and adding it back
would double count. State which convention you used.

**FCFE** (for a levered equity view):

```
FCFE = net income + D&A - capex - ΔNWC + net borrowing
```

#### Step 1: Forecast free cash flow (explicit horizon, usually 5–10 years)

Build revenue, margin, capex, and working-capital assumptions separately. Show the
forecast table with units and the driver behind each line. A DCF with a single
"growth" input and no operating detail is a sensitivity exercise, not a valuation.

#### Step 2: Calculate WACC

```
WACC = E/(D+E) × Ke + D/(D+E) × Kd × (1 - T)

Ke = Rf + β × ERP + [optional size/country premium]
```

- **Rf**: current 10-year government yield on the valuation date. Do not hard-code
  2.5% or any other historical level.
- **β**: estimate from a stated window and benchmark (e.g. 2–5 years weekly vs. the
  relevant index), or use peer unlevered beta and relever to the target capital
  structure. State the method.
- **ERP**: an explicit assumption with a source or a stated range (e.g. 5–7% for
  China A-shares is a common planning range, not an observed fact). Test it in
  sensitivity.
- **Kd**: the company's actual borrowing cost, or Rf + a credit spread consistent
  with its rating.
- **T**: effective tax rate, not always the statutory 25%.

Do not apply a WACC/FCFF DCF to banks and insurers; use DDM, residual income, or
PB-ROE instead. For companies with negative or near-zero FCFF, use a scenario or
reverse DCF rather than forcing a positive terminal value.

#### Step 3: Terminal Value

```
Perpetual growth: TV = FCFF_n × (1 + g) / (WACC - g)
Exit multiple:    TV = EBITDA_n × EV/EBITDA multiple
```

- `g` must be below WACC and should not exceed long-run nominal GDP growth; state
  why the chosen `g` is defensible.
- Cross-check the implied exit multiple against the scenario, and cross-check the
  perpetual-growth TV against the exit-multiple TV. A large gap means the
  assumptions disagree.

#### Step 4: Sensitivity Analysis

Always show a WACC × growth grid (and, for the exit multiple, a multiple × WACC
grid). Generate the numbers with a script so the table is consistent with the
formula; do not hand-type a table that contradicts the model.

```python
def dcf_value(fcf, wacc, g, years):
    pv = sum(cf / (1 + wacc) ** t for t, cf in enumerate(fcf, 1))
    tv = fcf[-1] * (1 + g) / (wacc - g)
    pv_tv = tv / (1 + wacc) ** years
    return pv + pv_tv
```

### 2. DDM (Dividend Discount Model)

**Applicable to**: high-dividend stocks with a stable payout (banks, utilities,
mature consumer companies).

```
Two-stage DDM:
P = Σ D_t / (1+Ke)^t + D_n × (1+g) / [(Ke-g) × (1+Ke)^n]

Gordon model (single stage):
P = D_1 / (Ke - g)
```

**Applicability checklist**:
- Has paid dividends consistently for more than 3 years
- Payout ratio is stable and covered by earnings/FCF
- Earnings and dividends are predictable enough for a terminal growth assumption
- Not suitable for high-growth companies with no dividend or a low payout

For A-shares, use the **implemented** dividend and the holding-period tax
assumption; a 预案 is not a paid dividend. For Stock Connect, use the 20%
withholding rate for mainland individuals.

### 3. SOTP (Sum of the Parts)

**Applicable to**: diversified conglomerates with separable segments.

```
Group value = Σ segment value + net cash + non-operating assets
              - minority interest - holding-company discount
```

Each segment needs its own profit base and multiple. Applying a PE multiple to a
revenue line is a unit error. The table below is **illustrative**; replace every
number with fetched data and state the date.

| Segment | Revenue | Net margin | Net profit | Multiple | Value |
|---------|---------|------------|------------|----------|-------|
| Segment A | 80 | 40% | 32 | 20x PE | 640 |
| Segment B | 50 | 10% | 5 | 8x PE | 40 |
| Segment C | 30 | 30% | 9 | 10x PE | 90 |
| **Sum** | | | | | **770** |
| Less: holding-company discount (15%, assumption) | | | | | -115.5 |
| Add: net cash / non-operating assets | | | | | 30 |
| **Equity value** | | | | | **684.5** |

The discount is an assumption, not an observed constant; show the range and why it
is applied. If the segments cannot be valued separately from disclosure, say SOTP
is not feasible rather than inventing segment profits.

## Relative Valuation

### PE

- Use trailing PE on **recurring** earnings; strip one-offs and check accounting
  quality first (see `financial-statement`).
- For cyclicals, use normalized/mid-cycle earnings, not peak earnings.
- A PE band is a description of history, not a law: compute the percentile of the
  current PE against its own 3–5 year history, and mark regime changes (rate
  level, growth, index composition).
- Cross-check with a reverse DCF: what growth does the current price imply?

### PB-ROE

For banks, insurers, and asset-heavy financials:

```
Justified PB = (ROE - g) / (Ke - g)
```

Use sustainable ROE, not a single peak year; use a cost of equity consistent with
the risk-free rate. A low PB with a low ROE is not automatically cheap.

### EV/EBITDA

- Useful for capital-intensive, comparable businesses with positive EBITDA.
- Not meaningful for banks/insurers, or when EBITDA is negative or inflated by
  capitalised costs.
- EV must include debt, minority interest, and preferred stock, and subtract cash
  and non-operating assets; otherwise the multiple is not comparable.
- Do not use fixed "undervalued/overvalued" industry bands. Use the peer
  distribution and state the peer set, date, and whether the peers are truly
  comparable.

### PE-Band percentile (implementation)

```python
pe_series = price / eps_ttm            # align dates and EPS definition
pct = (pe_series <= pe_series.iloc[-1]).mean()
# report: current PE, 3-5y median, 10th/90th percentile, sample window
# caveat: regime shifts and negative-EPS periods distort the series
```

## Cross-checks and valuation traps

1. **Value trap**: cheap on PE/PB because earnings are in structural decline.
   Check revenue trend, unit economics, debt maturities, and industry capacity.
2. **High PE with high growth**: a high multiple can be justified by growth, but
   `PEG < 1` alone is not proof. PEG ignores the duration of growth, reinvestment,
   risk, and the cost of capital. Use a reverse DCF to test what growth is priced
   in.
3. **Cyclical peak earnings**: low PE at the top of a cycle is a warning, not a
   bargain. Normalize earnings and check capacity/utilization.
4. **Accounting distortions**: capitalised costs, aggressive revenue recognition,
   receivables/inventory build, related-party transactions, and one-off gains.
5. **Goodwill and acquisitions**: high goodwill with missed performance promises
   can hide impairment.
6. **Dilution**: convertible bonds, options, and equity placements change per-share
   value; use diluted shares and scenario the conversion.
7. **Governance and policy**: controlling-shareholder pledges, related-party
   funding, trading suspensions, delisting risk, and policy changes can dominate
   the arithmetic.
8. **Liquidity**: a valuation that assumes a liquid market may not be realisable in
   a small-cap A-share name.
9. **"Shell value" and "policy premium"**: do not add an unquantified premium to a
   DCF. If you cannot measure it, discuss it as a risk, not as value.

## Output template

```markdown
## 估值分析: [公司名/代码]  (as_of YYYY-MM-DD)

### 数据与假设
| 输入 | 值 | 期间/日期 | 来源 |
|------|-----|-----------|------|
| 股价 | ... | ... | ... |
| 稀释股本 | ... | ... | ... |
| 营收/EBIT/FCFF | ... | ... | ... |
| Rf | ... | ... | ... |
| β / ERP | ... | ... | ... |
| WACC | ... | ... | 计算式 |
| 永续增长率 g | ... | ... | 假设 |

### 绝对估值（情景，不是单点）
| 情景 | 关键假设 | 每股价值区间 |
|------|----------|--------------|
| Bear | ... | ... |
| Base | ... | ... |
| Bull | ... | ... |

### 相对估值
| 方法 | 结果 | 可比公司/历史分位 | 数据日期 |
|------|------|-------------------|----------|
| PE | ... | ... | ... |
| PB-ROE | ... | ... | ... |
| EV/EBITDA | ... | ... | ... |

### 敏感性
| WACC \ g | ... | ... | ... |
|----------|-----|-----|-----|
| ... | ... | ... | ... |

### 交叉验证
- DCF 隐含的退出倍数 vs 可比交易倍数: ...
- 当前价格隐含的增长 vs 基准假设: ...
- 主要分歧: ...

### 结论（证据—判断—不确定性）
- 证据: ...
- 判断: 在 [假设] 下，估值区间为 [...]; 这不是目标价。
- 不确定性: ...
- 数据缺口: ...
```

## Notes

1. **DCF is highly sensitive to assumptions**: a 1% change in WACC can move the
   value by 20%+, so sensitivity analysis is mandatory.
2. **Comparable companies must truly be comparable**: same industry, scale, growth
   stage, accounting, and capital structure; do not apply a leader's multiple to a
   small company without adjustment.
3. **A-share valuation is not US-equity valuation**: liquidity, policy, ownership,
   and disclosure differ; state the market-specific assumption.
4. **Valuation is not a target price**: markets can remain irrational for a long
   time; a valuation range is an anchor for discussion, not a trading signal.
5. **Cyclicals**: use normalized earnings, not current peak/trough earnings.
6. **Not suitable for cryptocurrencies**: traditional valuation frameworks do not
   apply to BTC/ETH. This skill does not cover on-chain metrics.
7. **Every number gets a date**: price date, statement period, consensus snapshot,
   risk-free date. A valuation without dates is not reproducible.

## Chives 本地工具

使用 bot_assets 的 valuation_scenarios 或 discounted_cashflow。区分披露值、用户假设和 Bot 假设，记录估值日、年度 EPS、币种、股本、净债务与终值占比。用 financial_ratio 保留原值与分母。亏损企业切换估值方法，折现率须高于永续增长率。
