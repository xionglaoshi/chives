---
name: report-generate
description: 写研究报告：摘要、观点、分析、反方证据的结构与数据日期、证据要求。 Professional financial research report generation — structure (summary / views / analysis / disconfirming evidence / risks / data appendix), Markdown conventions, data-date and source rules, A-share-specific risk sections, and backtest evaluation standards. Ratings, target prices and position ideas are allowed with assumptions and falsifiers.
---

# Professional Research Report Generation

## Overview

Generate structured, professional-grade financial research reports. Follow the
conventions used by securities firms and asset managers, and output complete
Markdown reports that can be used for research reference.

A report is an argument, not a template to fill. The conclusion must follow the
evidence; never decide the conclusion first and then collect supports. Every
material number needs a source and a date.

## Delivering a document

If the session has a file-writing tool, write the Markdown report to a file and
return the path. If the session has a PDF/document tool, use it and report the
tool's returned status and path; if rendering fails, say so instead of claiming a
PDF was created.

Do not describe platform-specific chat downloads, channel pushes, or artifact
buckets unless the current session actually provides them. When no document tool
exists, deliver the Markdown directly in the response.

## Report Types and Scope

| Type | Scope | Core content | Trigger |
|------|-------|--------------|---------|
| Deep-dive company report | Full company analysis | Business, financials, valuation, risks | "Analyze company XX" |
| Industry research | Sector structure and trend | Industry map, drivers, peer comparison | "How is sector XX?" |
| Strategy report | Macro/strategy question | Regime, scenarios, allocation logic | "What is the market outlook?" |
| Backtest report | One strategy | Method, results, costs, robustness, failure modes | After a backtest |
| Flash comment | One event | What happened, why it matters, what to watch | "How should we view event XX?" |

Scope is set by the question, not by a word count. Do not pad a report to hit a
length target; a 1,200-word memo with complete evidence is better than a
5,000-word survey.

## Standard Structure Template

```markdown
# [Report Title]

> **Data as of**: YYYY-MM-DD  |  **Framework**: [DCF / relative / event study / ...]
> **Analyst**: [name or "research assistant"]  |  **Report date**: YYYY-MM-DD

## Summary

3–5 key points, each 1–2 sentences, covering the core conclusion and its
conditions. Use plain, calibrated language: "under assumption X, we see Y"; avoid
certainty and avoid forced bullish/bearish labels.

## Core Views

### View 1: [One-line heading]
2–3 paragraphs of discussion, each linked to data with a source and date.

### View 2: [One-line heading]
...

### View 3: [One-line heading]
...

## Main Analysis

### [Section 1: industry / business model / strategy logic]
...

### [Section 2: financial analysis / competitive landscape / backtest results]
...

### [Section 3: valuation / catalysts / risk-reward]
...

## Disconfirming Evidence

- The strongest fact that argues against the thesis: ...
- What would change our mind: ...
- Data we could not obtain: ...

## Data Appendix

| Item | Value | Period / as_of | Source | Unit |
|------|-------|----------------|--------|------|
| ... | ... | ... | ... | ... |

## Risk Warnings

1. [Risk 1]: specific description + trigger condition + impact
2. [Risk 2]: ...
3. [Risk 3]: ...
（按实际重大风险列，不凑数）

## Conclusion (evidence—judgment—uncertainty)

- Evidence: ...
- Judgment: under [assumptions], the range/scenario is ...
- Uncertainty: ...
- What to monitor next: ...

---
*以上为研究观点，决策与风险由你自行承担。*
```

## Ratings, target prices and position ideas

The user has asked for opinions, so give them: a rating, a target-price range, entry/exit conditions and a position
or stop-loss idea are all allowed when the user asks or the evidence supports them. Keep them honest:

- put the **assumptions** behind each case next to the number, and the **falsifiers** that would make the view wrong;
- separate facts from your judgment, and pair a single-point target with a range;
- if the user gave a holding period, capital or risk preference, build the plan around it; otherwise state the
  assumption you used and proceed.

## Data and source rules

1. Put a **data-as-of line** under the title.
2. Every table gets a period/date and a unit (元/万元/亿元, %, shares).
3. Every material number gets a source: filing, exchange, regulator, data tool, or
   `web_fetch` URL with fetch date.
4. Separate **actual**, **guidance**, **consensus**, and **forecast** in the text
   and in tables.
5. If a number cannot be obtained, write "取不到" and say what it would change.
6. Do not use a stale price or a stale consensus snapshot without flagging it.

## A-share-specific risk checklist

Include the ones that are material; do not pad:

- **ST / 退市风险**: risk-warning status, delisting indicators, restructuring.
- **Controlling-shareholder pledge**: pledge ratio, margin calls, forced sales.
- **Lock-up expiry**: 解禁 dates, size, holders, and supply overhang.
- **业绩预告 / 快报**: preliminary numbers, revision risk, and the difference
  between 预告 and 正式报告.
- **Related-party transactions and guarantees**: cash diversion, 资金占用,
  off-balance-sheet obligations.
- **Audit opinion and auditor changes**: qualified opinion, key audit matters.
- **Accounting quality**: receivables, inventory, capitalised R&D, goodwill.
- **Policy/regulatory risk**: industry policy, price controls, antitrust, export
  controls.
- **Liquidity**: free float, average turnover, impact cost, suspension history.
- **Dilution**: convertible bonds, private placements, equity incentives.

## Backtest evaluation standards

A backtest is evidence only if it states its assumptions. Require:

- universe and survivorship treatment (delisted names included?);
- sample period, in-sample/out-of-sample split, and parameter sensitivity;
- T+1 execution, limit-up/limit-down and suspension handling;
- transaction costs: commission, stamp duty (sell-side), transfer/handling fees,
  slippage, and the 5-yuan minimum where relevant;
- benchmark and factor exposure (size, value, industry);
- capacity/liquidity: how much capital the strategy can absorb;
- drawdown definition (peak-to-trough, daily close, including costs).

Report return, volatility, Sharpe, max drawdown, turnover, and capacity together.
Do not grade a strategy on in-sample Sharpe alone, and do not use fixed "good"
thresholds without a sample and a benchmark. A strategy with a high Sharpe but no
out-of-sample test, no costs, or impossible fills is not evidence.

## Plain language

Write what happened. Use "下跌" for a fall, "反弹" for a rebound, "回撤" for a
drawdown, and "估值收缩" for a de-rating. Do not replace plain words with
euphemisms, and do not replace "buy" with "overweight" to sound softer. If a
statement is a forecast, label it as a forecast and give the base rate or the
assumption behind it.

## Quality checklist before delivery

- [ ] Data-as-of line and report date are present.
- [ ] Every material number has a source and a period.
- [ ] The summary's claims match the body; no number appears twice with different values.
- [ ] Disconfirming evidence is included, not just the bull case.
- [ ] The conclusion is conditional and has an uncertainty section.
- [ ] A-share-specific risks are covered where material.
- [ ] Any rating, target price or position idea states its assumptions and falsifiers.
- [ ] A one-line risk note ("以上为研究观点，决策与风险由你自行承担") closes a formal report.
- [ ] No unsourced "probability", "empirical", or "backtest shows" claim.

## Notes

1. **Do not make overly precise forecasts**: use ranges rather than single points
   (`25–30 元` rather than `27.5 元`), and show what moves the range.
2. **Data consistency**: all quoted numbers must be consistent throughout the
   report; if two sources disagree, show both and explain which you use.
3. **Mark timeliness**: state both the data cut-off date and the report date.
4. **Risk note**: close a formal report with one line: "以上为研究观点，决策与风险由你自行承担。"
5. **Avoid absolutes**: "likely" is better than "certain"; "may" is better than
   "will".
6. **A-share risks**: policy, delisting, goodwill impairment, major-shareholder
   selling, lock-up expiry, pledge, and related-party transactions.
7. **Do not import a US sell-side template**: A-share disclosure, liquidity, and
   policy risks need their own sections.

## Chives 本地工具

接收上游提供的 snapshot_id、document_id 和物理页。用 research_snapshot 或 evidence_page 查原话，然后调用 save_report 交付 Markdown；数字保留报告期、单位和出处。公共证据链接使用原公告 URL 加 #page=N；工作台原件备用路径为本机 /api/research-documents/<SHA>、公网 /chives/api/research-documents/<SHA>。报告、委托问题和关注理由使用所属 Bot 的私有工作区。
