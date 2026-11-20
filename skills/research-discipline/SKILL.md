---
name: research-discipline
description: "研究纪律：任何投资研究（选股、行业研究等）开始时的偏差自查清单。 A short self-bias checklist to run at the START of any investment research task (stock screen / sector study / company deep-dive). Covers leader-bias, source-language and primary-source bias, narrative-bias, confirmation-bias, and recency-bias, with an A-share-specific correction for each. Load this first, then research with the corrections in mind. A checklist, not a workflow and not investment advice."
---

# AI Research Bias Self-Check

Run this at the **start** of any research task (screening, sector study, company
deep-dive). These are common failure modes of AI-generated research; the checklist
makes them visible before they shape the answer. It is an attitude reset, not a
guarantee of better output.

## The biases and their corrections

| Bias | How it shows | Correction |
|------|--------------|------------|
| **Leader-bias** | Search results are dominated by large-caps; you end up analyzing only the obvious names. | Deliberately look at mid-caps and suppliers as well; add the Chinese industry term, product term, or customer name to queries. Before adding a small-cap, check liquidity (average daily turnover), ST/*ST status, delisting risk, pledge ratio of the controlling shareholder, and free-float. "Small" is not a reason to include a name. Ask: "who is NOT in the top-10 that should be here?" |
| **Source-language / primary-source bias** | You search English secondary sources for a Chinese company and miss the primary disclosure; or you treat a blog summary as the filing. | For A-share and HK names, go to the primary source first: cninfo (巨潮资讯), SSE/SZSE/BSE announcement pages, HKEXnews, the company's annual/interim report, 互动易, 业绩预告/业绩快报. Search in Chinese with the company's full name and stock code. Use English/JP/KR/TW sources only for a genuine supply-chain thesis, and label them as secondary. |
| **Narrative-bias** | You get pulled in by a concept label ("AI stock", "new energy") and analyze the marketing instead of the business. | Ignore the label; look at the actual product, unit economics, and financial statements. A company tagged "AI" may have no AI revenue. Ask which reportable segment, if any, contains the revenue. |
| **Confirmation-bias** | Once a thesis forms, you only search for evidence that supports it. | Force a Munger inversion: for every bull point, deliberately search the bear case ("X risks / problems / bear case / 问询函 / 处罚"). Cite at least one disconfirming data point per conclusion, or state that none was found. |
| **Recency-bias** | You rely on a cached/outdated figure because it ranks high in search. | For any material number, write down its period and `as_of` date. Use the latest reporting period (annual, interim, or quarterly) and say which one. Do not apply a fixed "30-day/one-year" rule: annual financials are legitimately up to about 12 months old, while a price or a consensus estimate may be stale in days. If a figure's date cannot be established, do not use it as a conclusion. |

## Data-date rule

Every conclusion-carrying number gets a date and a source. Write it as
`value (period, as_of YYYY-MM-DD, source)`. A number without a period is treated as
missing, not as current. For market data, state the trading date; for financials,
the report period; for announcements, the publication date; for consensus data,
the snapshot date.

## How to apply

1. Before the first search, read the rows above.
2. Write the thesis in one sentence, then for each bias ask: "am I about to fall into this?"
3. Consciously broaden the query plan: mid-caps? primary Chinese disclosures? the bear case? the latest reporting period?
4. After research, before writing conclusions, re-check: did I cite any disconfirming evidence? did I use a primary source for the key facts? is every key figure dated?

This pairs with:
- `financial-statement` — verify the **numbers** (data layer)
- `report-generate` — verify the **final report** (output layer)
- this skill — verify the **reasoning** (thinking layer)

> 本清单用于研究流程。
