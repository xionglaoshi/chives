---
name: research-conventions
description: "研究规范：所有研究交付都要遵守的证据、判断、提问与行情数据规则，第一次研究前先读。 The evidence, judgement, intake and market-data rules every research deliverable follows. Read before the first deliverable of a research task; when a number has no source; when two sources disagree; when a figure may be stale; when deciding what to ask the user; before any valuation, thesis or recommendation."
---

# Research Conventions

The shared layer beneath every research skill in this collection. Each research skill says what to build; this one says what a figure has to carry, how far the evidence lets the language go, what is worth asking before starting, and how periods, windows and returns are computed. It holds those rules so no skill re-derives them: on evidence, judgement, intake and market-data mechanics this layer is the source of truth, and the calling skill owns what its deliverable contains.

## Reference files

- Any deliverable that prints a figure, a number with no source, two sources disagreeing, a figure that may be stale, or how densely to cite: `.agents/skills/research-conventions/references/evidence.md`.
- A valuation, a thesis, a recommendation, a scenario set, or any section that ends in what to do: `.agents/skills/research-conventions/references/judgment.md`.
- Before asking the user anything at the start of a task, and when deciding whether to ask at all: `.agents/skills/research-conventions/references/intake.md`.
- Before the first market-data pull of anything that prints a period label, a multiple, a growth rate or a return: `.agents/skills/research-conventions/references/market-data-rules.md`.
- Choosing how long a deliverable runs, a draft over its length band, or a request for a short version of something already built: `.agents/skills/research-conventions/references/depth.md`.

## Readiness posture

Every deliverable states one posture, once, near the top, in the reader's language. Posture is about inputs, not conviction: a high-conviction view resting on stale inputs is not decision-grade, and saying so is what makes the rest of the artifact usable.

| Posture | Holds when | Forced down by |
|---|---|---|
| `decision-grade` | every load-bearing figure is sourced and inside its freshness threshold, the downside is mechanical, and the inputs the recommended action needs are in hand | one load-bearing figure that is stale, unsourced or contested |
| `review-ready` | the analysis is complete and sourced, and one check or one input is still open | an unresolved conflict on a load-bearing claim, or a check that fails |
| `screen-grade` | coverage or depth is deliberately thin and the artifact says so | a headline conclusion that outruns the coverage behind it |
| `not-ready` | a load-bearing claim is unsupported, stale or contested with nothing settling it, and the conclusion rests on it | already the floor for a claim problem; state what would lift it |
| `blocked` | an input cannot be obtained at all (a tool failure, an undisclosed metric, a document we do not have) | already the floor; name the missing input and what would unblock it |

A posture below `decision-grade` names the specific figure or input responsible, so the reader can decide whether it matters to them. Posture is read from this table against the current input state, never stepped up or down from a previous value: when an input changes state, re-read the rows. This is the only readiness scale; a skill that needs a finer status for one of its objects labels that object, and the artifact still carries one posture from this table.

## Chives 本地工具

机构观点用 research_report_lookup 逐条检查机构、发表日期、预测财年、是否获得正文。已归档的 PDF 通过 evidence_page 读第二页之后的原文。年度 EPS 预测、历史目标价和当前一致预期分别引用。用 equity_review 冻结个股研究快照，用 research_snapshot 读回原值。对冷门股记录未取得的字段与检索截止日。
