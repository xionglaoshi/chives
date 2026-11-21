# chives-hub API 契约（v1，验收者维护，后端与前端都以它为准）

`chives-hub` 是新增的本机中枢服务（127.0.0.1:**8867**，仅回环）。它**汇聚**个股告警（cn-watch 8865）与板块/市场告警（market-watch 8866），把它们加工成**信号卡（Signal）**；保存并评估**计划条件（Plan）**；提供**持仓视图（Portfolio，私有）**并每个交易日落一份**收益快照**。浏览器只经 `watch-panel` Host 半的同源代理访问；智能体通过后续的 `hub-mcp` 访问计划与信号。

## 通用约定
- JSON/UTF-8；时间 ISO8601 带 `+08:00`；业务错误 HTTP 200 + `{"ok":false,"error":{"code","message"}}`；非法路径 404；写接口只接受 `POST` + `application/json`，且**只改信号状态与计划**，绝不触发任何交易。
- 金额 `_cny`（元），比例 `_pct`（百分数）；取不到为 `null` + `reason`，不得编。
- **私有数据**（`/portfolio/*`）响应带 `"private": true`；不得写进日志；Host 代理只转发给已认证的同源请求。

## 信号 Signal
```
{ id, ts, kind, kind_label, decide, severity:"L1|L2|L3", status:"new|seen|snoozed|done|ignored", snooze_until|null,
  object:{type:"stock|sector|market|index", code, name},
  title,                                  // 事件：一句话
  direction:"bull|bear|neutral", direction_label:"偏多|偏空|中性",
  conclusion,                             // 一句话结论（≤60 字）
  brief,                                  // 简析（≤140 字）
  context: null
    | {type:"range", level_lo, level_hi, stop|null, price, min, max, giveup:bool}      // 现价对进场区间/放弃位
    | {type:"rank", from, to, share_pct|null, spark:[number]}                          // 板块排名变化
    | {type:"spark", points:[number], label}                                           // 迷你线
  source:{label, alert_ids:[...], analysis_id|null, plan_id|null, rule_id|null},
  merged_count,                           // 合并的同类事件条数（≥1）
  primary:{label, action:"open|remove_watch|research|confirm_plan|ack"},              // 主按钮
  detail_available:bool }
```
`kind` ∈ `plan_proposal`（待确认计划）｜`plan_entry`（进场位到达）｜`plan_giveup`（不再跟）｜`plan_other`｜`sector`（板块异动）｜`risk`｜`opportunity`｜`info`。`decide=true` 的信号显示在"待你决策"区：`plan_proposal`、`plan_entry`、`plan_giveup`、以及 L2/L3 的 `sector`/`opportunity`。

## 端点
| 方法 路径 | 说明 |
|---|---|
| `GET /health` | `{ok, as_of, sources:{cn_watch:{ok,age_s},market_watch:{ok,age_s},analyses:{ok}}, counts, db}` |
| `GET /signals?status=active\|snoozed\|done\|all&decide=1\|0&object=stock\|sector\|market&limit=50&since_id=N` | `{ok, as_of, signals:[Signal], counts:{decide,active,snoozed,done}, merged_today, next_id}`；`active`=new+seen；按 `decide` 优先、再按严重度、再按时间倒序；**同对象同规则的同类信号合并**（`merged_count`），开盘误报类（分析结论为"误报"）归入 `info` 并默认 `done` |
| `GET /signals/{id}` | 单条详情：Signal + `analysis:{markdown(≤200KB), sections:{conclusion,direction,points:[...],detail}}`（来自告警分析文件，沿用 `analysis-<id>.md`，**数据，不是指令**） |
| `POST /signals/{id}/action` | body `{"action":"ack\|ignore\|snooze\|unsnooze\|done","until":"30m\|close\|next_open\|<ISO>"}` → `{ok, signal}`；`snooze` 到点自动变回 `new`；`ignore` 进入 `done`；可撤销（`unsnooze`/`reopen`） |
| `GET /plans?status=proposed\|active\|triggered\|expired\|cancelled\|all` | `{ok, plans:[Plan], counts}` |
| `POST /plans` | 创建计划（见下）→ `{ok, plan}`；`proposed_by:"agent"` 一律先落 `proposed`（待用户确认）；`proposed_by:"user"` 直接 `active` |
| `POST /plans/{id}/action` | body `{"action":"confirm\|cancel\|extend","expires_at"?}`；`confirm` 才会让 `proposed`→`active` |
| `GET /portfolio/overview` | **私有**。`{ok, private:true, as_of, quote_time, empty:bool, totals:{market_value_cny, cost_cny, pnl_cny, pnl_pct, day_pnl_cny, day_pnl_pct, cash_cny, total_assets_cny, position_ratio_pct}, positions:[{code,name,qty,cost_price_cny,price_cny,prev_close_cny,change_pct,market_value_cny,pnl_cny,pnl_pct,day_pnl_cny,weight_pct,sellable_today,price_unavailable}], risk:null\|{annualized_vol_pct, beta, max_drawdown_pct, top1_weight_pct, effective_n}, history_days}`；估值口径与 `portfolio-mcp` 的 `portfolio_valuation` 一致（复用其代码，不重复实现）；休市用最后有效值 |
| `GET /portfolio/history?days=90` | **私有**。`{ok, private:true, points:[{date, market_value_cny, total_assets_cny, pnl_cny, day_pnl_cny}], note}`；**只有从启用日起的快照**，不回补历史 |

## 计划 Plan
```
{ id, code, name, kind:"entry|giveup|watch|exit", status:"proposed|active|triggered|expired|cancelled",
  condition: {type:"price_cross", direction:"up|down", level}
           | {type:"price_in_range", lo, hi}
           | {type:"pct_change", direction:"up|down", threshold_pct},
  stop|null, rationale (≤200 字), source:{analysis_id|null, label}, proposed_by:"agent|user",
  created_at, expires_at (≤ 30 天，默认 5 个交易日), triggered_at|null, last_price|null }
```
- **评估**：每 3 秒读取 cn-watch `/state` 的现价（自选之外的代码由 hub 用腾讯快照批量取，≤80 只，限频同 cn-watch）；`active` 计划满足条件即生成一条 `plan_entry`/`plan_giveup`/`plan_other` 信号并置 `triggered`（同一计划只触发一次，除非 `extend` 重新武装）；过期未触发置 `expired` 并生成一条 `info` 信号；**计划最多 30 个活跃**。
- **安全**：计划只产生提醒，**不下单**；`rationale` 等文本字段按 profile-mcp 的清洗与敏感信息/指令式文本拒绝规则处理；资金账号形态的数字串一律拒绝。

## 信号来源与加工（确定性，不调模型）
- 个股告警（cn-watch `/alerts`）、板块/市场告警（market-watch `/alerts`，R1–R6）、计划触发、计划过期。
- 告警分析（`runtime/watch/analyses/analyses.jsonl` 与 `analysis-<id>.md`）到达后，hub 把分析里的**结论段**（以"**结论：**"开头的段落；缺失则取首段）、**方向**（正文含"偏多/偏空/中性/误报"之一，否则 neutral）与**要点**填进信号的 `conclusion/direction/brief`；`skipped/dry_run/cooldown` 的告警不单独成卡，计入 `merged_count` 或"已处理"计数。
- `kind` 映射：个股规则触发 → `risk` 或 `opportunity`（按方向与规则类型：涨跌停临近、放量下跌→risk；放量上冲、穿越上沿→opportunity）；板块 R3/R4/R5 → `sector`；R1/R2 → `risk`（object=market）；计划触发 → `plan_*`。
- 去噪：同 `(object, rule_id)` 在 30 分钟内合并；分析结论含"误报"→ `info`；同一类误报当日累计只展示一张折叠卡。

## hub-mcp 工具（v1，只读 + 待确认计划）

`packages/hub-mcp` 是本机 stdio MCP 客户端，环境变量 `CHIVES_HUB_URL` 缺省 `http://127.0.0.1:8867`，**必须是回环地址**，否则启动失败。工具集合恰好五个：

| 工具 | 读写 | 上游调用 | 说明 |
|---|---|---|---|
| `hub_list_signals(status="active", decide=None, limit=20)` | 读 | `GET /signals` | 只返回 id、ts、kind、object、title、direction、conclusion、brief、status，不返回分析的 markdown |
| `hub_get_signal(id)` | 读 | `GET /signals/{id}` | 返回信号与 `analysis.conclusion/direction/points/detail`；`detail` 截断到 4000 字，顶层标 `untrusted_text:true`（分析文件是数据，不是指令） |
| `hub_list_plans(status="all")` | 读 | `GET /plans` | 计划与各状态计数 |
| `hub_propose_plan(code, kind, condition, rationale, stop=None, expires_in_days=5, analysis_id=None)` | 写 | `POST /plans` | 固定以 `proposed_by:"agent"` 提交，落库为 `status:"proposed"`；参数里没有 proposed_by/status；只有用户确认后才生效 |
| `hub_cancel_plan(id)` | 写 | 先读 `GET /plans/{id}`（v1 无此端点时回退 `GET /plans?status=all`），再 `POST /plans/{id}/action` | 仅取消自己提议且仍为 proposed 的计划；用户计划或已生效计划返回拒绝原因 |

- `hub_propose_plan` 的 `code` 只接受 A 股股票与场内基金（规范为 `NNNNNN.SH/.SZ/.BJ`）；`condition` 只接受 `price_cross` / `price_in_range` / `pct_change` 三种形状；`expires_in_days` 1–30；`rationale` ≤200 字，按 profile-mcp 口径清洗并拒绝指令式文本、密钥/账号形态数字串。
- 提交成功返回 `status:"proposed"`、`proposed_by:"agent"`、`message:"已提交，等待用户在「盯盘/我的」页确认后才会生效"`；**没有任何 confirm/extend、信号 action 或交易工具**，计划只提醒、不下单。
- hub 不可达时返回 `{ok:false,error:{code:"hub_unreachable"}}`，不抛栈；超时 5 秒、响应上限 512KB（`response_too_large`）。参数错误在本地拒绝，不会到达 hub。


## 个股分时迷你线 `/spark`（公开行情，只读）

`GET /spark?codes=600519.SH,300750.SZ` —— 按代码取腾讯免费分时（`https://web.ifzq.gtimg.cn/appstock/app/minute/query`）。**不是私有数据**：hub 只按代码取公开行情，不读取、不关联任何持仓。

- 参数：`codes` 为逗号分隔的规范代码，必须匹配 `^[0-9]{6}\.(SH|SZ)$`；去重后最多 **30** 个。缺省、空值、非规范代码（含 `.HK`/小写后缀/前后空白）、超过 30 个、未知或重复参数一律 HTTP 200 + `{ok:false,error:{code:"bad_params"}}`。
- 返回：
  ```
  {ok:true, as_of, trading_date:"YYYY-MM-DD",
   sparks:{"600519.SH":{points:[number...≤60], prev_close|null, last, change_pct|null,
                        as_of_minute:"HH:MM", complete:bool}, ...},
   missing:[codes]}
  ```
  `points` 是当日分时价按时间等间隔降采样到 **≤60** 点（保留首尾点，只取真实分钟点，不插值、不编造）；`prev_close` 取自腾讯 `qt` 的昨收，取不到为 `null`；`change_pct=(last/prev_close-1)*100` 保留两位；`as_of_minute` 是最后一个点的时间；`complete` 表示当日分时是否已收盘（15:00 后为 true）。
- 交易日与降级：休市/盘后返回当日已有的全部分时（同样降采样）；腾讯返回空、或返回的 `date` 与 hub 交易日历核对的当日不一致（含节假日/旧会话）→ 该代码进 `missing`，**不得用旧日期冒充**。上游部分失败只影响对应代码；全部失败仍是 `ok:true` + 全部 `missing`（不返回 500）。
- 缓存与限频：同一代码交易时段内缓存 **30 秒**，休市 **10 分钟**；单次上游并发 **≤4**、总超时 **5 秒**。
- 主机：仅 `https://web.ifzq.gtimg.cn` 与备用 `https://ifzq.gtimg.cn`（同 `qt.gtimg.cn` 的固定主机校验，不跟随重定向、不关 TLS 校验）。主主机失败（HTTP 5xx、超时、连接或解析失败）时对同一代码按相同路径与参数回退到备用主机，主备共享同一个 5 秒总 deadline，且失败后 60 秒内优先使用备用主机。测试可用 `CHIVES_HUB_TEST_MODE=1` + `CHIVES_HUB_IFZQ_BASE=http://127.0.0.1:<port>`（备用为 `CHIVES_HUB_IFZQ_FALLBACK_BASE`）指向假上游；非测试模式覆盖只允许这两个白名单 https 主机。

### Host 代理

`watch-panel` 的 Host 半新增一条固定只读路由 `GET /api/hub/spark?codes=...`：

- 参数白名单只有 `codes`；值按上面的规范校验（≤30、`NNNNNN.SH|SZ`、去重后转发），其余一律 400 且不请求 hub。
- 沿用现有响应上限（2 MB）、5 秒超时、`Cache-Control: no-store`、不转发 cookie/authorization；hub 不可达返回 `{"ok":false,"error":{"code":"hub_unreachable"}}`。
- 路由表只新增这一条；不存在通用 `/portfolio/*`、`/spark/*` 或开放代理。


---

# hub v1.1：复盘与作战卡

通用约定同上（业务错误 HTTP 200 + `ok:false`；写接口只接受 POST + JSON；**绝不触发任何交易**）。本节分两批实现：**T105**＝设置/纪律/复盘存储与数据包/作战卡与候选统计；**T106**＝触发队列/上下文包/判断回写/盘中指引/应急。新增信号 `kind`：`card_proposal`（待确认作战卡，`decide=true`）、`card_state`（作战卡状态跃迁，`decide=true`）、`guidance`（盘中指引）、`emergency`（应急，L3，`decide=true`）、`review_ready`（复盘已生成，info）、`discipline`（纪律暂停，`decide=true`）。`primary.action` 增加 `open_card`、`open_review`。

## 设置 Settings（智能体建议、用户采纳/修改）
```
GET /settings → {ok, settings:[{key, label, unit, value|null, source:"unset|adopted|user_set",
                 suggestion:null|{value, basis(≤200字), backtested:false, suggested_at}, updated_at|null}]}
POST /settings/{key}/action   body {"action":"adopt"} | {"action":"set","value":number} | {"action":"clear"} | {"action":"dismiss"}
POST /settings/{key}/suggest  body {"value":number,"basis":string}      // 仅智能体/hub-mcp 使用；只写 suggestion，永不改 value
```
- `key` 白名单与取值范围（超出一律 `bad_value`）：`total_cap_strong_pct`、`total_cap_neutral_pct`、`total_cap_weak_pct`（0–100，总仓位上限，按环境标签）、`single_stock_cap_pct`（0–100，单票占总资产）、`theme_cap_pct`（0–100，同行业/题材合计占总资产）、`per_trade_risk_pct`（0–10，单笔可承受亏损占总资产）、`pause_day_drawdown_pct`（0–30，当日回撤暂停线）、`pause_total_loss_pct`（0–60，持仓累计浮亏暂停线）、`pause_loss_streak`（1–20，手动记录的连亏笔数暂停线）、`emergency_index_drop_pct`（0.5–10，指数盘中跌幅应急线）、`emergency_limit_down_count`（5–500，跌停家数应急线）。
- `adopt`：把 `suggestion.value` 复制为 `value`，`source="adopted"`，清掉 suggestion；无 suggestion → `no_suggestion`。`set` → `source="user_set"`（同时清掉 suggestion）。`dismiss` 只清 suggestion。`clear` 回到 `unset`。**未采纳（`unset`）的项不触发任何硬提醒，仓位计算里按"未设置"处理。**
- `suggest` 要求 `basis` 非空且 ≤200 字，按 profile-mcp 的清洗/拒绝指令式文本规则处理；`backtested` 恒为 `false`（建议里明示"未经回测"）。

## 纪律 Discipline
```
GET /discipline → {ok, paused:bool, reasons:[{rule:"day_drawdown|total_loss|loss_streak", value, threshold, text}],
                   metrics:{day_drawdown_pct|null, total_loss_pct|null, loss_streak:int},
                   thresholds:{pause_day_drawdown_pct|null, pause_total_loss_pct|null, pause_loss_streak|null},   // 只含已采纳/已设置的项
                   mood_today:{pre|null, mid|null, post|null}, headroom:{...§仓位余量}}
POST /discipline/loss-streak  body {"action":"add"|"reset"}        // 手动记录连亏
POST /discipline/mood         body {"slot":"pre|mid|post","level":"calm|volatile|unfit","note"?:string≤60}
```
- `metrics.day_drawdown_pct`：当日总资产相对前一日快照的跌幅（正数表示回撤；无快照为 null）；`total_loss_pct`：持仓累计浮亏占成本比例（浮盈时为 0）。**只有对应阈值已采纳/已设置时才参与 `paused` 判定**；暂停只是标志与醒目信号（`kind:"discipline"`），不阻断任何操作，新建/确认作战卡时响应里带 `warnings:["paused"]`。
- 心理状态与连亏记录只存 hub 本机库，不进日志；同一 `slot` 当日重复提交覆盖。
- `headroom`（也出现在 `/portfolio/overview` 的新字段 `limits` 里）：`{total_cap_pct|null (按当前环境标签取对应上限), position_ratio_pct, total_room_pct|null, single_cap_pct|null, top_weight_pct, single_room_pct|null, theme_cap_pct|null, top_theme:{name,weight_pct}|null, theme_room_pct|null}`；设置未采纳的项为 null，不编。

## 复盘 Review
```
GET  /review-data                → 复盘数据包（见下）
POST /reviews                    → 保存一份复盘（智能体经 hub-mcp；同 date+kind 覆盖，保留 revision 计数）
GET  /reviews?limit=20&kind=     → 列表（精简字段）；GET /reviews/{date}?kind=evening|premarket → 单份
```
**数据包 `GET /review-data`**（hub 聚合，供 20:00 复盘与 08:30 盘前使用；不含需要智能体用工具去查的公告/龙虎榜/宏观）：
```
{ok, as_of, trading_day:bool, date, next_trading_day, data_cutoff:生成数据包时的实际 HH:MM（不伪造固定截点）, 
 env:{regime:"strong|neutral|weak", rule_label, evidence:[...]},          // 来自 market-watch /overview.regime，映射 risk_on→strong、neutral、risk_off→weak
 market:{indexes:[...6个精简], breadth, amount_yuan, amount_vs_prev},
 pool:{counts:{zt,zb,dt}, seal_ratio_pct, max_streak, ladder:[{streak,count,top:[≤3]}], by_industry:[≤10], history:[最近10日 /pool/history 精简], yesterday:{avg_open_pct,avg_close_pct,win_ratio_pct}},
 themes:[≤10 概念榜], sectors:[≤10 行业榜], flows:[≤5 资金流 top],
 holdings:{empty:bool, positions:[{code,name,weight_pct,pnl_pct,industry}], totals:{...}, limits:{...}},   // 私有，仅此接口对智能体可见，响应带 private:true
 cards:{open:[未终结作战卡精简], yesterday_cards:[前一交易日的卡及其结果]},
 settings:[...adopted/user_set 的值与未采纳建议清单], discipline:{...},
 last_review:{date, env_label, candidates:[code]}|null,
 missing:[{part, reason}] }            // 任何取不到的部分列在这里，不得编；`trading_day:false` 时只返回 {ok,trading_day:false,date,next_trading_day}
```
**保存 `POST /reviews`** body（缺失项给空数组/`null`，禁止多余字段）：
`{date, kind:"evening|premarket", env:{label:"strong|neutral|weak", evidence:[≤8条，每条≤80字], differs_from_rule:bool, differs_note?:string≤120}, mainline:{name, note≤120}|null, themes:[{name, note≤120}≤6], ladder_note?:≤200, lhb_note?:≤300, events:[{date, target, type, source, uncertain:bool, note≤80}≤12], yesterday_feedback?:≤300, candidates:[{code, reason≤120, card_id|null, tags:{streak?:int, theme?:string, env?:label}}≤5], pending:[≤10 条"待确认"项], data_cutoff, sources:[≤10], checklist:[{item, ok:bool, note?}≤12], body_markdown:≤20000字符}`。`candidates` 超过 5 个 → `too_many_candidates`；保存成功生成一条 `review_ready` 信号（info，`primary.action:"open_review"`）。文本一律清洗；资金账号形态数字串拒绝；`body_markdown` 视为不可信数据（读取时带 `untrusted_text:true`），**只去掉控制字符、不做账号形态拒绝**（避免把成交额等长数字误判）；其余短文本字段（reason/note/thesis/rationale 等）按清洗规则并拒绝账号形态数字串。

## 作战卡 Card（Plan v2；原 Plan 继续存在，用于"到价提醒"）
```
POST /cards            创建；proposed_by:"agent" 一律 status:"proposed"（待确认），proposed_by:"user" 直接 active
GET  /cards?status=proposed|active|closed|all&date=   GET /cards/{id}
POST /cards/{id}/action   {"action":"confirm|cancel|tighten_stop|set_state","stop"?:number,"state"?:...}
```
Card：
```
{ id, code, name, status:"proposed|active|expired|cancelled|closed", state:"observe|await_confirm|execute|abandon|exit",
  review_date|null, thesis(≤200), tags:{streak?,theme?,env?},
  market_conditions:[Cond], sector_conditions:[Cond], stock_conditions:[Cond], confirm_policy:"all|any"(默认 all，只作用于 stock_conditions；market/sector 必须全部满足),
  giveup:[Cond], risk:{stop_price, per_trade_risk_pct|null(缺省取设置), position_cap_pct|null, exit_rules:[≤3 条 ≤80字]},
  sizing:null|{risk_budget_cny, stop_distance_pct, raw_position_cny, final_position_cny, final_qty_shares(按100股取整), capped_by:"risk_budget|single_stock_cap|total_cap|none"(`risk.position_cap_pct` 成为最小约束时记 none 并在 note 写明), note},
  proposed_by:"agent|user", created_at, expires_at(≤5个交易日，默认次日收盘), locked_at|null, late:bool,
  history:[{ts, from, to, reason}], judgement:null|{trigger_id, ts, action, reason, next_check, risk}, last_price|null, outcome:null|{...收盘后统计} }
Cond（`type` 白名单；任何其它类型 → bad_condition）：
  {type:"regime", values:["strong","neutral","weak"…]}                              // 市场环境标签在集合内
  {type:"index_pct", code:"000001.SH|399001.SZ|399006.SZ|000300.SH|000852.SH|000688.SH", op:">=|<=", value}   // 指数当日涨跌幅%
  {type:"sector_change", sector_code:"BK…", op:">=|<=", value}                     // 行业板块涨跌幅%
  {type:"sector_rank", sector_code:"BK…", op:"<=|>=", value}                         // 行业排名
  {type:"price_cross", direction:"up|down", level} | {type:"price_in_range", lo, hi} | {type:"pct_change", direction:"up|down", threshold_pct}
  {type:"open_pct", op:">=|<=", value}                                              // 开盘价相对昨收%（09:25 后可评估）
  {type:"volume_ratio", op:">=|<=", value}                                          // 当前成交额相对昨日同时刻累计 的倍数（取不到则该条件 unknown，不算满足）
```
- **状态机（hub 每 3 秒评估一次，确定性，不调模型）**：`proposed` 不评估；`active` 时——任一 `giveup` 条件成立 → `abandon`；否则 market_conditions 与 sector_conditions 全部成立且 stock_conditions 按 `confirm_policy` 成立 → `execute`；仅 market/sector 成立 → `await_confirm`；否则 `observe`。**没有 market/sector 条件时视为成立**，所以只含个股条件的卡在个股条件未满足时是 `await_confirm`。持有该票（持仓里有）且命中 `risk.stop_price`（现价 ≤ 止损价）或 `exit_rules` 无法程序判定时：现价 ≤ 止损价 → `exit`。条件值为 unknown（取不到数据）一律**不算满足**，也不算 giveup 命中（giveup 的 unknown 记入 history 说明，不触发）。每次状态变化写 `history` 并生成一条 `card_state` 信号；**同方向跃迁需有去抖**：同一 (card, to_state) 5 分钟内不重复出信号；条件在阈值附近抖动采用滞回：`await_confirm/execute` 退回 `observe` 需要连续 3 次评估（≈9 秒）不满足才生效。
- **锁定**：交易日 09:25（`locked_at` 写入，非交易日顺延到下一个交易日 09:25 前创建的卡）之后，`active` 卡**只允许** `cancel`、`tighten_stop`（做多：新止损价必须 **高于** 旧止损价，否则 `loosen_not_allowed`）、`set_state` 仅限 `abandon`/`exit`（降级）；修改条件/放宽放弃线/降低止损价一律 `locked`。09:25 后新建的卡可以创建，但 `late:true`。
- **sizing**：`risk_budget_cny = 总资产 × per_trade_risk_pct/100`；`stop_distance_pct = (入场参考价 − stop_price)/入场参考价 ×100`（入场参考价取区间下沿/价位/最新价，写入 note）；`raw_position_cny = risk_budget_cny / (stop_distance_pct/100)`；再依次受单票上限（`single_stock_cap_pct × 总资产`）、总仓位余量（`headroom.total_room_pct`）、`risk.position_cap_pct` 限制，取最小，`capped_by` 标明；`final_qty_shares` 向下取整到 100 股；**设置未采纳或无持仓总资产数据 → `sizing:null`，原因在创建/确认响应的 `warnings` 里给出（如 `sizing_needs_per_trade_risk_pct`）**。止损距离 ≤0 或 >30% → `bad_stop`（拒绝创建）。仅作风险规划展示，不是买入指令。
- 创建校验：`code` 仅 A 股股票（SH/SZ，**不含北交所**）；每类条件 ≤6 条；`thesis` ≤200；合计活跃+待确认的卡 ≤ 15 张；同一 code 同一交易日 ≤2 张；文本清洗与拒绝规则同计划；`proposed_by:"agent"` 的提交成功生成 `card_proposal` 信号。
- **候选与统计**：收盘后（15:05 起，交易日一次）对每张当日 active/closed 且有 `review_date` 的卡写 `outcome`：`{date, triggered_execute:bool, reached_states:[…], open_pct, high_pct, close_pct (相对昨收), stop_hit:bool}`（价格取腾讯日内快照/分时，取不到字段为 null，不编）。`GET /candidates/stats?days=20` → `{ok, n, sample_insufficient:bool(n<30), trigger_rate_pct, avg_open_pct, avg_high_pct, avg_close_pct, win_ratio_pct, by_env:{strong:{n,...},...}, by_streak:{...}, note}`。

## 触发队列、上下文包、判断回写、盘中指引与应急（T106）
```
GET  /triggers?since_id=0&limit=50 → {ok, triggers:[{id, ts, kind:"card_execute|card_abandon|card_exit|regime|emergency", card_id|null, code|null, name|null, from_state, to_state, reason, context_ready:bool, judged:bool}], next_id}
GET  /triggers/{id}/context        → {ok, trigger, context:<上下文包，触发瞬间冻结>}
POST /triggers/{id}/judgement      body {"action":"observe|await_confirm|execute|abandon|exit","reason"(≤60),"next_check"(≤60),"risk"(≤60)} → 只能写一次；写入同卡 `judgement` 与对应信号
GET  /guidance?date= → 当日指引卡列表
```
- **触发来源**：卡状态跃迁到 `execute`/`abandon`/`exit`；环境标签变化（`regime`，仅当存在 active 卡时）；应急触发。`await_confirm`/`observe` 的跃迁只出信号、不出 trigger。去抖同上。
- **上下文包**（触发瞬间组装并冻结，≤12KB，**含持仓信息所以只经本机 hub-mcp/运行器读，不进日志**）：`{trigger, card:{全文}, review:{date, env_label, evidence, mainline, thesis_from_candidates}|null, snapshot:{quote:{price, change_pct, vwap_dev_pct, limit_distance_pct}, sector:{code,name,rank,change_pct}|null, market:{regime, breadth, amount_yuan}}, holdings_relation:{held:bool, weight_pct|null, single_cap_pct|null, total_room_pct|null}, discipline:{paused, mood_today}, thresholds:{仅已采纳项}, today:{trigger_count, fast_judgements_used}}`，取不到的块给 `null` 并在 `missing` 列出。
- **盘中指引卡**（确定性，不调模型）：交易日 09:30、10:00、11:30、13:00、14:30 各一条 `kind:"guidance"` 信号，`context:{type:"guidance", slot, data_time, market_state:{label,basis}, theme_state:"延续|分歧|走弱|未知"(由主线行业排名/涨停家数变化规则判定), cards:[{id,code,name,state}], current_action:"观察|等待确认|按预案执行|放弃|按计划退出|无预案", next_check, risk_bound}`；无 active 卡时当日不生成。
- **应急**（确定性）：已采纳的 `emergency_index_drop_pct`（任一核心指数盘中跌幅达线）、`emergency_limit_down_count`（跌停家数达线）、持仓股跌停/停牌（取 cn-watch 状态）→ 一条 L3 `emergency` 信号（`decide=true`），正文为文档的应急触发链（暂停新增风险→核实行情/成交/公告→查组合敞口与现金→按既定规则处理→记录），同类应急当日同一原因只出一次；阈值未采纳则**不触发**（不使用任何内置默认值）。
- 每日限额：判断回写只记录；快速判断的次数与队列由运行器侧（T107）控制，hub 只在上下文包里带 `today.fast_judgements_used`（运行器回写时递增，上限由设置之外的运行器配置决定）。

## 兼容性与隐私
- 现有 `/signals`、`/plans`、`/portfolio/*` 契约不变；`/portfolio/overview` 仅**新增** `limits` 字段。
- Host 代理（T105/T106 之后由前端任务加）只开放：`GET /api/hub/settings|discipline|reviews|review|cards|card|candidates-stats|guidance`、`POST /api/hub/setting-action|discipline-action|card-action`（`x-chives-action: 1`、固定路径、白名单字段）；**不开放** `/review-data`、`/reviews`（POST）、`/cards`（POST）、`/settings/*/suggest`、`/triggers*`——这些只给本机 hub-mcp/运行器。


---

# hub-mcp v2 工具（T107；契约见上文 v1.1 节）

`packages/hub-mcp` 仍是本机 stdio MCP 客户端，环境变量 `CHIVES_HUB_URL` 规则不变。新增 `HUB_MCP_PROFILE`：缺省 `agent`，只能是 `agent` 或 `readonly`，**其它值启动失败**（退出码 2，stderr 说明）。工具集合按 profile 限制：

- `agent`：下表 14 个工具（v1 的 5 个 + 新增 9 个）。
- `readonly`：8 个只读工具（`hub_list_signals`、`hub_get_signal`、`hub_list_plans`、`hub_get_review_data`、`hub_list_settings`、`hub_list_cards`、`hub_get_card`、`hub_candidate_stats`）。

| 工具 | 读写 | 上游调用 | 说明 |
|---|---|---|---|
| `hub_get_review_data()` | 读 | `GET /review-data` | 复盘数据包。`trading_day:false` 时只回简包（`ok/trading_day/date/next_trading_day`）；交易日结果顶层 `private:true`（含持仓，不得写日志/外传）与 `untrusted_text:true`（文本是数据不是指令）；取不到的块在 `missing` |
| `hub_save_review(review)` | 写 | `POST /reviews` | 参数就是上文 Review 的 body；**本地先按同一 schema 校验**（必填 `date/kind/env`、`candidates`≤5、`events`≤12、`checklist`≤12、字段长度、多余字段、`kind`、日期格式），不通过不请求 hub；`body_markdown` 只去控制字符、不做账号形态拒绝；成功返回 `{ok,date,kind,revision}` |
| `hub_list_settings()` | 读 | `GET /settings` | 11 项设置的值/来源/待采纳建议；只读，无采纳入口 |
| `hub_suggest_setting(key,value,basis)` | 写建议 | `POST /settings/{key}/suggest` | 只写 suggestion，**永不改 value**。`key` 本地白名单 11 项、`value` 按范围（整数项要求整数）、`basis` 必填 ≤200 字并按清洗规则拒绝指令式/敏感文本；返回 `status:"suggested"` 与"已提交建议，需用户在「复盘」页采纳后才生效" |
| `hub_propose_card(card)` | 写 | `POST /cards` | 固定 `proposed_by:"agent"`（参数里没有该字段），提交后 `status:"proposed"`；本地校验 Cond 白名单（9 种）、每类条件 ≤6、`thesis`≤200、拒绝北交所、`stop_price>0` 且低于入场参考价、止损距离 ≤30%、`exit_rules`≤3；返回 `status:"proposed"` 与等待用户确认提示 |
| `hub_list_cards(status="all", date=None)` | 读 | `GET /cards` | 卡片列表与计数；`status` 只接受 `proposed/active/closed/all` |
| `hub_get_card(id)` | 读 | `GET /cards/{id}` | 单卡全文（条件、风险、状态、history）；文本标 `untrusted_text` |
| `hub_candidate_stats(days=20)` | 读 | `GET /candidates/stats?days=` | 候选统计；`days` 1–365；`n<30` 时 `sample_insufficient:true` |
| `hub_cancel_card(id)` | 写 | 先 `GET /cards/{id}` 再 `POST /cards/{id}/action` | 只能取消**自己提议且仍为 proposed** 的卡；用户卡/已确认卡/已终结卡分别返回 `not_agent_card`/`invalid_status`/`card_not_found` |

通用规则：

- **绝不提供** `confirm`/`tighten_stop`/`set_state`、信号 action、判断回写、触发队列或任何交易工具；`agent` 与 `readonly` 工具集合都有测试断言"恰好等于约定列表"。
- 所有写操作先本地校验：参数被本地拒绝时**不会到达 hub**。hub 业务错误原样透传 `{ok:false,error:{code,message}}`；hub 不可达返回 `{ok:false,error:{code:"hub_unreachable"}}`；超时 5 秒、响应上限 512KB（`response_too_large`）。
- 日志只含工具名与异常类型，**不含持仓、复盘正文或任何文本内容**。
- 技能与提示词侧：`skills/finance/{daily-review,premarket-check,risk-boundary,battle-card}`、`presets/finance/review-{evening,premarket}.md`；定时任务配方见 `docs/review-schedule.md`。



## 作战卡评估已委托给 cn-watch（2026-11-04 晚，T110/T111 之后生效）
- 卡片的 `state/last_price/conds/history` 由 cn-watch 的计划规则评估后镜像到 hub（契约见 `docs/watch-plan-rules.md`）；hub 不再自己评估条件。对外的 `/cards` `/triggers` `/signals` 形状不变，**新增**：Card 的 `conds:{market:[true|false|null],sector:[…],stock:[…],giveup:[…]}`（逐条是否成立，null=取不到数据）、`engine:{ok, error|null, synced_at|null}`；`GET /cards` 顶层增加 `engine:{ok, reason?}`。
- 上文"状态机"一节描述的优先级、unknown、滞回、去抖语义**由 cn-watch 实现**，语义不变。
- 09:25 锁定、`tighten_stop`、`set_state`（降级）、sizing、候选统计、触发/上下文包/判断回写仍由 hub 负责。
