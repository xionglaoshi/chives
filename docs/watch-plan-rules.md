# chives-radar 计划规则（Plan rules）契约 v1（验收者维护；实现者以它为准）

**决策（用户，2026-11-04）**：盘中只有**一套**评估逻辑——盯盘引擎 chives-radar。作战卡不再由 hub 自己评估状态，而是作为 chives-radar 的一种**计划规则**：hub 保存卡片的业务属性（复盘关联、仓位计算、确认/锁定策略、判断文字），确认后把"计划规则"下发给 chives-radar；chives-radar 评估、产出状态跃迁告警；hub 只订阅结果。以后盘中能力一律增强 chives-radar。

计划规则与现有的"单指标规则"（pct_change / vwap_deviation / limit_proximity / price_cross / volume_surge）并存：后者是"某个指标越线就告警"，前者是"一组条件的组合判断 + 状态机"。

## 通用约定
- 写接口沿用 chives-radar 现有约束：仅回环、POST + JSON、大小上限、`actor` 头审计；业务错误返回 `{ok:false, code, message, field?}`（HTTP 400）。
- 计划规则**绝不触发交易**，只产生状态与告警。

## 数据模型
```
Plan = {
  id: "^[A-Za-z0-9_-]{1,40}$",           // hub 用 "card-<卡片id>"
  code: "NNNNNN.SH|SZ",                   // 不含北交所/指数
  market:  [Cond] (≤6),  sector: [Cond] (≤6),  stock: [Cond] (≤6),
  policy: "all|any",                      // 只作用于 stock；market 与 sector 必须全部成立
  giveup: [Cond] (≤6),
  stop_price: number>0 | null,
  held: bool,                             // 是否持有该票（由 hub 维护；只有 held=true 时才会进入 exit）
  expires_at: ISO8601 +08:00 | null,      // 过期后状态为 expired、停止评估
  label: string ≤40                       // 仅展示
}
Cond（type 白名单；其它一律 400 invalid_condition）:
  {type:"regime", values:["strong","neutral","weak"…]}
  {type:"index_pct", code:"000001.SH|399001.SZ|399006.SZ|000300.SH|000852.SH|000688.SH", op:">=|<=", value}
  {type:"sector_change", sector_code:"BK\\d{4}", op:">=|<=", value}
  {type:"sector_rank", sector_code:"BK\\d{4}", op:"<=|>=", value}
  {type:"price_cross", direction:"up|down", level}
  {type:"price_in_range", lo, hi}                      // lo<hi
  {type:"pct_change", direction:"up|down", threshold_pct}
  {type:"open_pct", op:">=|<=", value}                  // 开盘价相对昨收 %，09:25 后可评估
  {type:"volume_ratio", op:">=|<=", value}              // 行情源的量比字段；取不到则 unknown
```
`regime` 的取值：`strong`（chives-compass regime `risk_on`）、`neutral`、`weak`（`risk_off`）。

## 端点
| 方法 路径 | 说明 |
|---|---|
| `POST /plans/upsert` | body 为一个 Plan（同 id 覆盖）；校验严格（字段白名单、范围、条数、`lo<hi`、代码合法）；**同 code 的 upsert 自动把该票加入监控范围**（见"自动监控"）；返回 `{ok, plan:<PlanState>}` |
| `POST /plans/remove` | `{id}` → 删除并（若该票是被计划自动加入的）撤销自动监控 |
| `GET /plans` | `{ok, as_of, market_context:{ok, age_s, regime|null}, plans:[PlanState]}` |
| `GET /plans?id=<id>` | 单个 PlanState，不存在 `not_found` |
| `GET /alerts`（沿用） | 计划状态跃迁也以告警形式出现，见下 |

PlanState：
```
{ id, code, label, state:"observe|await_confirm|execute|abandon|exit|expired", since:ISO, last_price|null, held,
  conds:{market:[true|false|null], sector:[...], stock:[...], giveup:[...]},      // 逐条当前是否成立；null=取不到数据
  history:[{ts, from, to, reason}] (≤30 条，最近在后), expires_at|null, active:bool }
```

## 评估（每个行情轮询周期，确定性，不调模型）
- `expired` 优先（`expires_at` 已过）。其次：**任一 giveup 成立 → `abandon`**；否则 `held` 且现价 ≤ `stop_price` → `exit`；否则 market 与 sector 条件全部成立（**空列表视为成立**）且 stock 按 `policy` 成立 → `execute`；仅 market/sector 成立 → `await_confirm`；否则 `observe`。
- **unknown（数据取不到）一律不算成立，也不算 giveup 命中**（giveup 的 unknown 只记在 history 的 reason 里）。
- **滞回**：从 `execute` 或 `await_confirm` 退回较低状态（`observe`/`await_confirm`）需要**连续 3 次评估**都不满足才生效；升级（进入 `execute`/`abandon`/`exit`/`await_confirm`）立即生效。`abandon`/`exit` 是终态之一：进入后保持，直到 `held` 或条件使其回到非终态且连续 3 次评估支持。
- **去噪**：同一 (plan, to_state) 5 分钟内不重复产生告警。
- 启动/重启后第一次评估只恢复状态，不产生告警（避免重复告警）。
- 市场上下文（regime、指数涨跌幅、行业板块涨幅/排名）来自 chives-compass（回环，默认 `http://127.0.0.1:8866`，可配置，**只读**）：每 5 秒取一次 `/overview`、`/sectors`；数据超过 30 秒未更新或取不到 → 相应条件 unknown。收盘/非交易时段：不评估、不产生告警（状态保持），`GET /plans` 照常返回最后状态。

## 告警（沿用 `/alerts` 通道）
状态跃迁到 `execute`/`abandon`/`exit`/`await_confirm` 时产生一条告警：`rule_id:"plan:<id>"`, `rule_type:"plan"`, `code`, `price`, `severity`（execute/abandon/exit=L2，await_confirm=L1）, `detail:{plan_id, from, to, reason, label}`；沿用现有的去重键与存储。**深度分析触发器（cn-watch-trigger）必须跳过 `rule_type=="plan"` 的告警**（盘中快速判断由 hub 的触发队列与独立运行器负责，避免两条队列重复处理）。

## 自动监控（盯盘与作战卡打通）
- `POST /plans/upsert` 时，若该 code 不在监控列表（YAML 自选 + 运行期自选），引擎把它加入**运行期自选**，并标记 `source:"plan"`（`/watchlist` 与 `/state` 里可见）；监控范围的现有上限与校验沿用（超限 → `watchlist_full`，该 upsert 整体失败）。
- 当没有任何计划引用该 code、且它不是 YAML 自选/用户手动加入的，则自动撤销（`/plans/remove`、`expired` 后 1 个交易日、或计划 `inactive` 时）。**不得移除用户自己加的票。**
- 因此：计划票会自动出现在盯盘页的"我的盯盘"、拿到迷你线、并适用通用规则（若该规则的 `symbols` 允许）。

## 持久化与隐私
- `plans.runtime.json`（与 `rules.runtime.json` 同目录，原子写，坏文件按空处理并告警不覆盖）；`history` 一并保存。
- 计划里**没有任何持仓数量、成本、资金信息**（只有 `held:bool`）；日志里不写计划内容。
