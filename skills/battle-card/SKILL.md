---
name: battle-card
description: "单只标的作战卡写法与 Cond 取值指南：市场/板块/个股条件怎么取（regime 值域、指数代码、BK 板块代码、价位、volume_ratio 含义与取不到的处理），放弃条件怎么写（板块转弱/竞价偏离/承接不足/失效位），如何避免把放弃条件改成买入理由；只写条件式预案，不预测、不下单。"
---

# 作战卡写法（battle-card）

作战卡是**条件式预案**：写清"什么情况下才成立、什么情况下放弃、最多亏多少、怎么退出"，由 hub 每 3 秒用确定性规则判定状态。它不是买入名单，也不是价格预测。

## 一张卡必须写全的东西

| 字段 | 怎么写 | 注意 |
|---|---|---|
| `code` | 沪深 A 股 `NNNNNN.SH/.SZ` | **不含北交所**，本地会拒绝 `.BJ` |
| `thesis` | ≤200 字：为什么观察它（主线、位置、催化） | 事实与判断分开；写失效条件 |
| `market_conditions` | 环境/指数条件 | 可以没有；没有时视为市场条件成立 |
| `sector_conditions` | 板块涨幅/排名条件 | 必须全部满足（不受 `confirm_policy` 影响） |
| `stock_conditions` | 个股确认条件 | `confirm_policy:"all"`（默认）时全部满足才 `execute`，`"any"` 时任一满足 |
| `confirm_policy` | `all` / `any` | 只作用于 `stock_conditions` |
| `giveup` | 放弃条件 | 任一命中即 `abandon`，优先级最高 |
| `risk.stop_price` | 止损价 | 必须低于入场参考价；距离 >30% 或 ≤0 会被拒绝 |
| `risk.per_trade_risk_pct` | 单笔风险预算 | 缺省取用户已采纳的设置；未采纳时 `sizing` 为 null |
| `risk.position_cap_pct` | 本卡仓位上限 | 可选 |
| `risk.exit_rules` | ≤3 条、每条 ≤80 字 | 程序无法判定的退出规则只作展示，不自动触发 |
| `tags` | `streak`（连板数）、`theme`（题材）、`env`（环境） | 用于候选统计分组 |

提交用 `hub_propose_card(card)`；`proposed_by` 固定为 `agent`、没有 `status` 参数，提交后是 `proposed`，**必须用户在「复盘」页确认后才生效**。

## Cond 取值指南

条件白名单共 9 种，`type` 写错或多余字段会被本地拒绝（`bad_condition`）。

### `regime` —— 市场环境标签

- `values` 是非空数组，值只能是 `"strong"`、`"neutral"`、`"weak"`（对应偏强/中性/偏弱）。
- 常用写法：强势环境才做 → `{"type":"regime","values":["strong"]}`；强势或中性 → `["strong","neutral"]`。
- 环境标签由 hub 用规则算，复盘里可以综合判断改档，但卡上写的是**你希望成立的条件**，不是对明天的预测。

### `index_pct` —— 指数当日涨跌幅

- `code` 只接受 6 个：`000001.SH`（上证）、`399001.SZ`（深成）、`399006.SZ`（创业板）、`000300.SH`（沪深300）、`000852.SH`（中证1000）、`000688.SH`（科创50）。
- `op` 只能是 `">="` 或 `"<="`；`value` 是百分数（`0.5` 表示 +0.5%）。
- 例：`{"type":"index_pct","code":"000300.SH","op":">=","value":0.3}`。

### `sector_change` / `sector_rank` —— 板块涨幅/排名

- `sector_code` 必须是 `BK` + 4 位数字（如 `BK0433`）。**不要手写猜代码**：从 chives-compass `/sectors` 的返回里取 `code`，或从 `hub_get_review_data()` 的 `sectors[].code` 取（同一口径）。
- `sector_change.value` 是百分数；`sector_rank.value` 是名次（≥1，越小越靠前）。
- 例：`{"type":"sector_change","sector_code":"BK0433","op":">=","value":1.0}`、`{"type":"sector_rank","sector_code":"BK0433","op":"<=","value":5}`。

### 价位类：`price_cross` / `price_in_range` / `pct_change`

- `price_cross`：`direction` 为 `up|down`，`level` 为正数；`up` 表示向上穿越。
- `price_in_range`：`lo < hi`，都为正数；**区间下沿会被 hub 当作入场参考价**，止损距离按它计算。
- `pct_change`：`direction` 为 `up|down`，`threshold_pct` ≤100。
- 价位取法：用当日 VWAP、前高/前低、平台上下沿、缺口位、涨停价/跌停价附近等**可复核的位置**，写清依据与数据时间；不要取"感觉差不多"的整数。价位是条件，不是预测目标。

### `open_pct` —— 开盘价相对昨收

- `op` 为 `">="|"<="`，`value` 在 -100..100。09:25 后才有值。
- 盘前写卡时可以用它表达"高开不超过 X%"或"低开不超过 Y%"；**09:15–09:25 竞价数据没有稳定来源，不要在盘前假装知道开盘价**。

### `volume_ratio` —— 量能确认

- 含义：**当前成交额相对昨日同时刻累计成交额的倍数**（不是"量比"指标的另一个口径）。
- `op` 为 `">="|"<="`，`value` 为正数。
- 取不到数据时该条件为 `unknown`：**不算满足，也不算放弃命中**；因此不要只用一条 `volume_ratio` 作为唯一确认条件，最好配一个价位条件。
- 例：`{"type":"volume_ratio","op":">=","value":1.2}` 表示当前成交额至少是昨日同时刻的 1.2 倍。

## 放弃条件怎么写

放弃条件是**风险边界**，不是"看错了再说"。每条都要能由程序判定或能明确交给用户执行：

| 类型 | 写法 | 例子 |
|---|---|---|
| 板块转弱 | `sector_change` 跌破阈值，或 `sector_rank` 掉出前 N | `{"type":"sector_change","sector_code":"BK0433","op":"<=","value":-0.5}` |
| 指数/环境转弱 | `regime` 不再包含原档，或 `index_pct` 跌破线 | `{"type":"regime","values":["weak"]}` |
| 竞价/开盘偏离 | `open_pct` 超出可接受区间 | `{"type":"open_pct","op":"<=","value":-3}` |
| 承接不足 | 跌破入场参考位/平台下沿（`price_cross down`） | `{"type":"price_cross","direction":"down","level":9.2}` |
| 失效位 | 跌破止损或关键结构位（`price_in_range` 下沿之下） | 与 `risk.stop_price` 一致或略高 |

写法要求：

- 放弃条件与确认条件**不能互相矛盾**（例如确认要求 `price_in_range 9.4–9.6`，放弃却写 `price_cross down 9.5`）。
- 放弃线要在建卡时一次写清；09:25 锁定后只能收紧止损、取消或降级，**不能放宽放弃条件**。
- `giveup` 的 `unknown` 不触发放弃，但要在复盘/盘前里说明数据缺口。

## 三条硬规则

1. **不得把"放弃条件"改写成买入理由**。例如"跌破 9.2 就放弃"不能写成"跌破 9.2 是黄金坑、可以加仓"；同一价位不能既是放弃线又是加仓线。
2. **不预测**。不写"明天必涨/目标价 X%/至少三个板"；只写条件与风险边界。可以给情景（若 A 则观察、若 B 则放弃），但不能给概率或收益承诺。
3. **仓位只用 hub 的 `sizing`**。提交后读返回卡片的 `sizing`（`final_position_cny`、`final_qty_shares`、`capped_by`、`note`）；为 `null` 时写原因（如 `sizing_needs_per_trade_risk_pct`），不自己编百分比或金额。

## 提交后的检查

- 返回 `status:"proposed"`、`proposed_by:"agent"`；告诉用户"待确认"，指路「复盘」页，不说"已生效"。
- 同一代码同一交易日最多 2 张、活跃+待确认最多 15 张；被拒时读错误码（`card_limit`、`card_code_limit`、`bad_stop`、`bad_condition`）并如实转告，不反复重试。
- 需要撤掉自己刚提、仍是 `proposed` 的卡时用 `hub_cancel_card(id)`；已确认的卡只能建议用户取消。
- 想回看历史表现用 `hub_candidate_stats(days=20)`；`n<30` 写"样本不足"，不据此调规则。
