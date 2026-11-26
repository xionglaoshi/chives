# Chives 信号枢纽

正式程序名为 `chives-signals`，生产服务监听本机 8867。由 `scripts/chives.sh start --engines` 启动，通过设置页「内核设置」查看状态。配置中的旧标识、MCP 工具名和已有数据目录用于兼容升级。

本机中枢服务（**127.0.0.1:8867，仅回环**）：把个股告警（chives-radar，8865）与板块/市场告警
（chives-compass，8866）确定性加工成**信号卡**，保存并评估**计划条件**，把**作战卡**交给
chives-radar 的计划规则评估（hub 只下发与镜像），提供**私有持仓视图**、**设置/纪律**与
**复盘数据包**，
并在每个交易日收盘后写一条**收益快照**。**不调用模型，不连接券商，不下单。**

- Python ≥ 3.12，运行时**只用标准库**；测试依赖只有 pytest。
- 接口契约：`docs/hub-api.md`（v1）。浏览器只经 watch-panel 的 Host 半同源代理访问。
- 包内没有 `subprocess` / `exec` / `eval`；TLS 校验保持默认开启，不跟随重定向。

## 快速开始

```bash
cd packages/chives-signals
python3.12 -m venv .venv
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q              # 1054 个离线测试，不访问公网
```

运行（推荐用启停脚本；pid/日志/sqlite 都在仓库 `runtime/hub/`）：

```bash
scripts/chives-hub.sh check       # 校验配置
scripts/chives-hub.sh start       # 127.0.0.1:8867
scripts/chives-hub.sh status
scripts/chives-hub.sh logs 100
scripts/chives-hub.sh stop
```

手动运行：

```bash
cd packages/chives-signals
PYTHONPATH=src .venv/bin/python -m chives_signals --config config.example.yaml --check-config
PYTHONPATH=src .venv/bin/python -m chives_signals --config config.example.yaml          # 常驻
PYTHONPATH=src .venv/bin/python -m chives_signals --config config.example.yaml --once   # 轮询一次并打印 /health
```

`scripts/chives-hub.sh` 默认用 `packages/chives-signals/config.yaml`；不存在时用
`config.example.yaml`。`CHIVES_HUB_CONFIG=/abs/path.yaml` 可指定别的配置。

## 复用 portfolio-mcp（不复制估值代码）

启动时 `portfolio_view.ensure_portfolio_path()` 把
`packages/portfolio-mcp/src` 插入 `sys.path`，随后直接使用
`portfolio_mcp.store.PortfolioStore`、`portfolio_mcp.service.PortfolioService` 与
`portfolio_mcp.quotes.TencentQuoteClient`：

- `/portfolio/overview` 的市值、成本、盈亏、权重与 `portfolio_valuation` 同一份实现；
- `day_pnl_cny` 由 hub 在估值结果上补算：`Σ 数量 × (现价 − 昨收)`；
- `risk` 调用同一个 `PortfolioService.risk()`（`window_days=250`），把
  `*_ratio` 换算成 `*_pct`；K 线取数慢，结果缓存 **600 秒**，取不到返回
  `risk:null` + `risk_reason`；为避免一次请求被多只 K 线拖住，计算最多等待 **2.5 秒**，
  未完成时先返回 `risk:null` + `risk_reason:"risk_pending"`，后台算完后下一次请求命中缓存。

持仓文件路径沿用 portfolio-mcp：`$DSH_FINANCE_PROFILE_DIR` → `$DSH_HOME` → `~/.dsh`，
文件名 `finance-portfolio.json`。测试一律注入临时 profile 目录或假的 service，
**不触碰真实 `~/.dsh`**。

## 配置

配置是 YAML 极小子集（块状映射、标量、注释；也接受 JSON）。相对路径以配置文件所在目录为基准。

| 键 | 默认 | 说明 |
|---|---|---|
| `api.host` / `api.port` | `127.0.0.1` / `8867` | host 只允许回环；服务实际永远绑定 `127.0.0.1` |
| `runtime.db_path` | `../../runtime/hub/hub.db` | sqlite（信号、计划、快照、处理游标、kv） |
| `runtime.out_dir` | `../../runtime/hub` | 脚本/日志目录 |
| `upstreams.cn_watch` | `http://127.0.0.1:8865` | 生产只允许回环 + 8865 |
| `upstreams.market_watch` | `http://127.0.0.1:8866` | 生产只允许回环 + 8866 |
| `analyses_dir` | `../../runtime/watch/analyses` | 只读 `analyses.jsonl` 与 `analysis-<id>.md` |
| `watchlist_file` | `../../config/watch.yaml` | 兼容保留；计划价格优先读 chives-radar `/state` |
| `calendar_file` | `../../config/trade_calendar.json` | JSON 数组；缺失时退化为工作日 |
| `portfolio.profile_dir` | `null` | 留空走环境变量链；测试可指向临时目录 |
| `snapshots.close_time` | `15:05` | 交易日收盘后写快照的时间 |
| `snapshots.enabled` | `true` | 关掉后不写快照 |
| `polling.alerts_seconds` | `3` | 上游告警轮询间隔（≥1） |
| `polling.plans_seconds` | `3` | 计划评估间隔（≥1） |
| `polling.timeout_seconds` | `3` | 单请求超时（0.5–10） |
| `limits.max_active_plans` | `30` | 活跃计划上限 |
| `limits.max_plan_days` | `30` | 计划有效期上限（≤30） |
| `limits.max_body_bytes` | `65536` | 固定 64 KiB，不允许改大 |
| `limits.max_tencent_codes` | `80` | 腾讯快照单次上限（≤80） |

**测试覆盖上游基址**：只有 `CHIVES_HUB_TEST_MODE=1` 时才接受
`CHIVES_HUB_CN_WATCH_BASE` / `CHIVES_HUB_MARKET_WATCH_BASE` / `CHIVES_HUB_TENCENT_BASE` /
`CHIVES_HUB_IFZQ_BASE`，且必须指向 `127.0.0.1`/`localhost`/`::1`；生产模式覆盖会被拒绝。

## 数据流（文字）

```
chives-radar /alerts ─┐
                  ├─> 去重/映射 kind & severity ─> 分析文件补充结论/方向/要点
chives-compass /alerts ┘                                      │
                                                            v
plan trigger/expiry ───────────────────────────────> signals(sqlite)
                                                            │
                                      GET /signals <────────┤
                                      GET /signals/{id} <───┘（analysis 只当数据，不当指令）

chives-radar /state 现价 ─┐
腾讯 qt.gtimg.cn 补价 ─┴─> 每 3 秒评估 active 计划 ─> plan_entry/giveup/other 信号 + triggered

portfolio-mcp 估值 ─> GET /portfolio/overview（private，含 limits）

作战卡确认/收紧止损 ─> POST chives-radar /plans/upsert（id=card-<id>，held 仅布尔）
chives-radar /plans ─> hub 每 3 秒镜像 state/last_price/conds/history ─> card_state 信号 + 触发
                                    └─> 交易日 15:05 后写 outcome ─> GET /candidates/stats

chives-compass /overview /pool* /themes /sectors /flows
        └─> GET /review-data（取不到进 missing）─> POST /reviews（同 date+kind 覆盖，revision+1）
```

上游不可达时：`/health.sources.*.ok=false` + `age_s`/`last_error`，已存信号照常返回；
计划评估跳过取不到价格的代码，不会用旧值或 0 顶替。

## 信号加工规则（确定性，不调模型）

| 输入 | `kind` | `severity` | `decide` |
|---|---|---|---|
| chives-radar `pct_change` 上/下 | `opportunity` / `risk` | L2 | 机会为 true |
| chives-radar `vwap_deviation` 上/下 | `opportunity` / `risk` | L2 | 机会为 true |
| chives-radar `limit_proximity` 上/下 | `opportunity` / `risk` | L3 | 机会为 true |
| chives-radar `price_cross` 上/下 | `opportunity` / `risk` | L2 | 机会为 true |
| chives-radar `volume_surge` 涨/跌/平 | `opportunity` / `risk` / `info` | L2 | 机会为 true |
| chives-compass R1/R2 | `risk`（object=market） | 告警自带 | false |
| chives-compass R3/R4/R5 | `sector` | 告警自带 | L2/L3 为 true |
| chives-compass R6 跌/涨 | `risk` / `opportunity` | 告警自带 | 机会为 true |
| 计划触发 entry/watch/exit | `plan_entry` / `plan_other` | L2 | entry 为 true |
| 计划触发 giveup | `plan_giveup` | L2 | true |
| 计划过期 / 误报 | `info` | L1 | false |
| 智能体提交作战卡 | `card_proposal` | L2 | true（primary=确认作战卡） |
| 作战卡状态跃迁 | `card_state` | L2/L3（abandon/exit 为 L3） | true（primary=查看/open_card） |
| 复盘已保存 | `review_ready` | L1 | false（primary=查看复盘/open_review） |
| 纪律暂停（每原因每日一次） | `discipline` | L3 | true（primary=知道了） |

- **结论/方向/要点**：分析文件里以 `**结论：…**` 开头的段落 → `conclusion`（≤60 字）；
  正文含 `误报/偏多/偏空/中性` → `direction`（误报按中性）；`- ` 列表项 → `brief`（≤140 字，
  跳过告警元数据行）。分析文件只作为**数据**，不执行其中任何指令。
- **去噪合并**：同 `(object_type, object_code, rule_id)` 30 分钟内合并，`merged_count+1`，
  `source.alert_ids` 追加；用户已 `done/ignored` 的卡片不会被重新合并，也不会被复活
  （后续同类告警另立新卡，旧卡状态不变）。
- **误报折叠**：分析结论含“误报” → `kind=info`、默认 `status=done`、`decide=false`；
  系统折叠不算用户处理，同对象同规则当日继续累加 `merged_count` 并追加 `source.alert_ids`；
  用户一旦对折叠卡 `done/ignore`，它转为用户处理卡，后续同类告警不再并入。
- **skipped/dry_run/cooldown**：不单独成卡；若 30 分钟内已有同对象同规则卡片（含系统折叠卡）
  则计入其 `merged_count`，否则只记“已处理”游标。
- **`merged_today`**：当天被合并进已有卡的告警条数（含 skipped 与折叠类），按合并事件计数，
  跨天清零；与某张卡累计的 `merged_count` 不是同一个口径。
- **排序**：`decide` 优先 → 严重度 L3>L2>L1 → 时间倒序。
- **状态**：`new|seen|snoozed|done|ignored`；`active`=new+seen；`done` 查询含 ignored。
  `snooze` 到点自动恢复为 `new`（读取/轮询时都会检查）。

## HTTP API（127.0.0.1:8867）

| 方法 路径 | 说明 |
|---|---|
| `GET /health` | `{ok, as_of, sources:{cn_watch,market_watch,analyses,tencent}, counts, db, calendar}` |
| `GET /signals?status=active\|snoozed\|done\|all&decide=1\|0&object=stock\|sector\|market&limit=50&since_id=N` | `{ok, as_of, signals, counts, merged_today, next_id}` |
| `GET /signals/{id}` | `{ok:true, ...Signal 顶层字段, analysis:{markdown, sections:{conclusion,direction,points,detail}}}`；不存在时 404 + `{ok:false,error:{code:"signal_not_found"}}` |
| `POST /signals/{id}/action` | `{"action":"ack\|ignore\|snooze\|unsnooze\|done\|reopen","until":"30m\|close\|next_open\|<ISO>"}` → `{ok, signal}` |
| `GET /plans?status=proposed\|active\|triggered\|expired\|cancelled\|all` | `{ok, plans, counts}` |
| `POST /plans` | 创建计划 → `{ok, plan}`；`proposed_by:agent` 先落 `proposed` 并生成 `plan_proposal` |
| `POST /plans/{id}/action` | `{"action":"confirm\|cancel\|extend","expires_at"?}` → `{ok, plan}` |
| `GET /portfolio/overview` | **private**：totals/positions/risk；`risk` 取不到为 null + `risk_reason` |
| `GET /portfolio/history?days=90` | **private**：只返回已存快照，不回补历史 |
| `GET /spark?codes=600519.SH,300750.SZ` | 公开分时迷你线：`{ok, as_of, trading_date, sparks:{code:{points≤60, prev_close, last, change_pct, as_of_minute, complete}}, missing}`；最多 30 个规范代码，非法参数 200 + `bad_params`；主主机失败时同路径回退到 `ifzq.gtimg.cn`（失败后 60 秒内优先备用） |
| `GET /settings` | 11 项设置：`value|source(unset/adopted/user_set)|suggestion(value,basis,backtested:false)` |
| `POST /settings/{key}/action` | `{"action":"adopt|set|clear|dismiss"}`（`set` 带 `value`） |
| `POST /settings/{key}/suggest` | 智能体建议：`{"value","basis"}`，只写建议，永不改 `value` |
| `GET /discipline` | 暂停标志/原因/指标/已采纳阈值/三个时点心理状态/仓位余量 |
| `POST /discipline/loss-streak` | `{"action":"add|reset"}` 手动记录连亏笔数 |
| `POST /discipline/mood` | `{"slot":"pre|mid|post","level":"calm|volatile|unfit","note"?}` |
| `GET /review-data` | 复盘数据包（chives-compass `/overview /pool* /themes /sectors /flows` + 私有持仓 + 作战卡 + 设置 + 纪律）；取不到进 `missing`；休市只返回 `trading_day:false` 简包 |
| `POST /reviews` | 严格 schema 保存复盘；同 `date+kind` 覆盖并累加 `revision`；生成 `review_ready` 信号 |
| `GET /reviews?limit=20&kind=` | 复盘列表（精简字段） |
| `GET /reviews/{date}?kind=evening|premarket` | 单份复盘，`body_markdown` 读取时 `untrusted_text:true` |
| `GET /cards?status=proposed|active|closed|all&date=` | 作战卡列表（`closed` 含 expired/cancelled/closed） |
| `POST /cards` | 创建作战卡；`proposed_by:"agent"` 一律 `proposed` 并生成 `card_proposal` |
| `GET /cards/{id}` | 单张作战卡（含 `history`） |
| `POST /cards/{id}/action` | `{"action":"confirm|cancel|tighten_stop|set_state","stop"?,"state"?}` |
| `GET /candidates/stats?days=20` | 候选结果统计；`n<30` → `sample_insufficient:true`，不外推 |
| `GET /triggers?since_id=0&limit=50` | 触发队列：`{ok, triggers:[{id, ts, kind, card_id, code, name, from_state, to_state, reason, context_ready, judged}], next_id}` |
| `GET /triggers/{id}/context` | **private**：触发瞬间冻结的上下文包（≤12KB）；不存在 404 `not_found` |
| `POST /triggers/{id}/judgement` | 判断回写，只能写一次：`{"action":"observe/await_confirm/execute/abandon/exit", "reason"≤60, "next_check"≤60, "risk"≤60}` |
| `GET /guidance?date=YYYY-MM-DD` | 当日盘中指引卡列表（`slot`、`context`、`signal_id`） |

约定：

- 时间 ISO8601 带 `+08:00`；金额 `_cny`（元），比例 `_pct`（百分数），权重 `weight_pct` 为百分数。
- 写接口只接受 `POST + application/json`；请求体上限 64 KiB；未知字段、类型错误、非法枚举一律 400；
  未知路径 404；非 GET/POST 405；非回环 `Host` 403；业务冲突（计划上限、状态不允许）返回 200 +
  `{ok:false,error:{code,message}}`。
- 所有错误信息不含持仓内容；`/portfolio/*` 的异常只记异常类型，不记标的或数量。
- **任何接口都不会下单、转账或连接券商。**

### 计划

```json
{"code":"601099","kind":"entry",
 "condition":{"type":"price_cross","direction":"up","level":4.0},
 "stop":3.5,"rationale":"突破跟进","proposed_by":"user"}
```

`condition` 三种：`price_cross{direction,level}`、`price_in_range{lo,hi}`、
`pct_change{direction,threshold_pct}`。有效期默认 5 个交易日、最长 30 天；
`confirm` 才让 `proposed→active`；`cancel` 取消；`extend` 重新武装触发过的计划。
评估每 3 秒一次：自选股价格来自 chives-radar `/state`，自选外代码用腾讯快照批量取（≤80 只，
主机固定 `qt.gtimg.cn`，不跟随重定向）。**计划只提醒，不触发任何交易。**

## 设置、纪律、复盘与作战卡（hub v1.1）

- **设置**：`total_cap_*_pct`、`single_stock_cap_pct`、`theme_cap_pct`、`per_trade_risk_pct`、
  `pause_day_drawdown_pct`、`pause_total_loss_pct`、`pause_loss_streak`、
  `emergency_index_drop_pct`、`emergency_limit_down_count` 共 11 项。智能体建议 `backtested:false`，
  **不采纳就不生效**；纪律、仓位计算与应急只读取 `adopted`/`user_set` 的值。
- **纪律**：当日回撤用 hub 每日快照与当日总资产；累计浮亏用持仓成本与浮亏；连亏由用户手动记录。
  暂停只是标志（`kind:"discipline"`，同一原因每日一条），不阻断任何操作。心理状态与连亏只存本机 sqlite。
- **复盘**：`/review-data` 由 hub 聚合，取不到的块列进 `missing`，不编造；非交易日只返回简包。
  `POST /reviews` 拒绝多余字段，候选 ≤5，`body_markdown` 视为不可信文本。
- **作战卡**：Cond 白名单（regime/index_pct/sector_change/sector_rank/price_cross/price_in_range/
  pct_change/open_pct/volume_ratio）。hub 只做创建校验、sizing、09:25 锁定、候选统计与信号/触发；
  **状态评估只有一套逻辑：chives-radar 计划规则**（见下节）。
- **09:25 锁定**：交易日 09:25 后 active 卡只允许 `cancel`、收紧止损（新止损必须更高，
  否则 `loosen_not_allowed`）、`set_state` 降级为 `abandon/exit`；09:25 后新建的卡 `late:true`。
- **sizing**：`总资产 × per_trade_risk_pct / 止损距离`，再受单票上限、总仓位余量、
  `position_cap_pct` 约束取最小，`final_qty_shares` 向下取整到 100 股；设置未采纳或无持仓数据时
  `sizing:null`。**仅作风险规划展示，不是买入指令。**
- **候选统计**：交易日 15:05 起对当日有 `review_date` 的 active/closed 卡写一次 `outcome`；
  `n<30` 明确提示样本不足，不外推。

### 作战卡委托 chives-radar（T111）

- **下发**：`active` 卡（用户确认或 `proposed_by:"user"`）向 chives-radar `POST /plans/upsert`：
  `id:"card-<卡片 id>"`、`code`、`market/sector/stock/giveup`（与卡片条件同形）、`policy`、
  `stop_price`、`held`（仅在持仓里时为 true）、`expires_at`、`label:"<名称> 作战卡"`（≤40 字）。
  `tighten_stop` 后重新下发；`cancel`、过期、`closed`、`set_state` 降级到 `abandon/exit` 后
  `POST /plans/remove`。写请求带 `X-Actor: chives-hub`。**hub 不下发数量/成本/资金，只有 `held:bool`。**
- **订阅**：引擎每 3 秒 `GET /plans`，镜像 `state`、`last_price`、逐条 `conds`
  （`market/sector/stock/giveup`，`true/false/null`）与 `history`（按 `(ts,to)` 去重合并）。
  状态变化沿用 T106：`card_state` 信号、`execute/abandon/exit` 触发与冻结上下文包；
  重复同步同一状态不重复产生信号/触发。
- **对账与容错**：chives-radar 不可达时卡片状态不变，`GET /cards` 顶层
  `engine:{ok:false,reason}`；恢复后补发缺失计划；启动时重发全部 active 卡（幂等）；
  chives-radar 里 `card-` 前缀但 hub 已不评估的计划会被删除（绝不动其它规则/计划）。
  下发被拒（如 `watchlist_full`）时卡片保持 active、卡上 `engine.error` 记录原因、
  响应 `warnings` 带 `engine_rejected`，按 3/6/12/30/60 秒退避重试。
- **新增字段（向后兼容）**：Card 增加
  `conds:{market:[true|false|null],sector:[…],stock:[…],giveup:[…]}` 与
  `engine:{ok,error|null,synced_at|null}`；`GET /cards` 顶层增加 `engine:{ok,reason?}`。
  其余 `/cards`、`/triggers`、`/signals` 契约不变。

## 触发队列、上下文包、判断回写、盘中指引与应急（T106）

### 触发（`/triggers`）

- **来源**：作战卡状态跃迁到 `execute`/`abandon`/`exit`（`card_execute`/`card_abandon`/`card_exit`）；
  环境标签变化且存在 active 卡（`regime`）；应急命中（`emergency`）。
  `await_confirm`/`observe` 的跃迁只发 `card_state` 信号，**不产生触发**。
- **事务一致性**：卡片状态、`card_history`、`card_state` 信号、触发记录在**同一个 sqlite 事务**里
  写入，要么都在、要么都不在。手动 `set_state` 到 `abandon`/`exit` 同样生成触发。
- **去抖**：沿用 T105 的 5 分钟窗口，同一 `(card, to_state)` 内不重复出信号/触发；环境标签的
  同一目标标签 5 分钟内也不重复。`regime` 首次观测只记基线、不触发（重启后基线仍在 sqlite `kv`）。
- `from_state`/`to_state` 对作战卡是状态；对 `regime` 是 `strong/neutral/weak` 标签；
  `emergency` 两者均为 `null`。
- `context_ready` 在上下文包写好后为 `true`；`judged` 在判断回写后为 `true`。上下文包组装失败的
  触发保留 `context_ready:false`，之后每轮 tick 重试（最多 5 条）。

### 上下文包（`/triggers/{id}/context`）

- 触发瞬间组装并**冻结**，重复读取内容不变（唯一例外：`today.fast_judgements_used` 是当日实时计数，
  判断回写后 +1）。
- 块：`trigger`、`card`（作战卡全文，含条件/放弃线/风险/仓位/历史）、`review`（最近复盘的
  `date/env_label/evidence/mainline/thesis_from_candidates`）、`snapshot`（`quote` 的价格/涨跌/
  VWAP 偏离/距涨跌停，`sector` 的代码/名称/排名/涨幅，`market` 的环境/宽度/成交额）、
  `holdings_relation`（是否持有/占比/单票上限/总仓位余量）、`discipline`（暂停/心理时点）、
  `thresholds`（**只含 adopted/user_set 的设置**）、`today`（当日触发数、快速判断已用数）。
- 取不到的块为 `null` 并列入 `missing`；因超长被裁剪的块列入 `trimmed`。
  优先级：先裁复盘摘要（证据 → 主线 → 整个复盘），再裁板块细节，再裁作战卡历史，最后截断超长字符串；
  **作战卡正文与行情快照保留**。总长以 UTF-8 JSON ≤ **12KB** 为准。
- `quote.limit_distance_pct` 取到涨停/跌停价中**较近者**的距离百分比（无显式价时按昨收推：
  主板 10%、创业板/科创板 20%）；取不到为 `null`。
- **private**：`GET /triggers/{id}/context`、`POST .../judgement` 响应带 `private:true`；
  上下文包不写日志、不进 `/health`。

### 判断回写（`POST /triggers/{id}/judgement`）

- 只能写一次；再写 → `{ok:false,error:{code:"already_judged"}}`；触发不存在 → 404 `not_found`。
- 文本按短文本规则清洗（压平空白、去控制字符），拒绝指令式文本与资金账号形态数字串。
- 写入后挂到作战卡 `judgement` 与产生该触发的 `card_state` 信号：只补 `conclusion`/`brief` 的
  “Chives 判断…”文字，**不改** `kind`/`decide`/`severity`/`status`。
- **只作补充意见**：不改变卡的 `state`、条件、止损与 chives-radar 的评估结果；`action` 与卡当前状态不一致时仍写入，
  返回 `diverges_from_state:true`。
- 同时把当日快速判断计数 +1（按自然交易日存 sqlite），上下文包的 `today.fast_judgements_used` 反映该计数。

### 盘中指引卡（`GET /guidance`）

- 交易日五个时点：**09:30 / 10:00 / 11:30 / 13:00 / 14:30**，每个时点在 **5 分钟窗口内**生成一次
  （如 10:00–10:05）；窗口外不补。`(day, slot)` 唯一，重启不重复。
- 当日**没有 active 且未过期的作战卡**（状态 observe/await_confirm/execute）时不生成；仅有
  proposed/已终结的卡也不算。
- 信号：`kind:"guidance"`、`severity:"L1"`、`decide:false`、`primary.action:"open"`。
- `context.theme_state` 规则（主线行业取 `/sectors?level=sw1` 排名最靠前者）：

  | 条件 | 结果 |
  |---|---|
  | 取不到板块或排名 | `未知` |
  | 当日第一个时点 | 排名 ≤ **TOP_N=5** → `延续`，否则 `分歧` |
  | 排名下滑 ≥ **RANK_SLIP=1** 位 | `走弱` |
  | 涨停家数减少 ≥ **max(5 家, 上一时点×20%)** | `走弱` |
  | 排名上升且仍 ≤ 5 | `延续` |
  | 排名不变且 ≤ 5，涨幅回落不超过 **0.2** 个百分点 | `延续` |
  | 其它 | `分歧` |

- `market_state.label` ∈ `偏强/中性/偏弱/未知`（risk_on/neutral/risk_off），`basis` 为
  `/overview.regime.reasons` 拼接。`current_action` 取卡状态优先级
  `exit > abandon > execute > await_confirm > observe`，无卡为 `无预案`。
  `next_check` 为下一个时点（14:30 之后为 `15:00`）。`risk_bound` 只列已采纳的总仓位/单票/单笔风险，
  一项都没有时为 `未设置`。

### 应急（确定性）

- **只读已采纳/已设置的阈值**：`emergency_index_drop_pct`、`emergency_limit_down_count`；
  未采纳（含只有建议 `unset`）→ **永不触发**，不使用任何内置默认值。
- 条件（交易日 **09:30–15:00**）：
  1. 任一核心指数（`000001.SH`/`399001.SZ`/`399006.SZ`/`000300.SH`/`000852.SH`/`000688.SH`）
     相对昨收的盘中跌幅 ≥ 阈值；
  2. chives-compass 跌停家数（`/overview.breadth.limit_down`，缺失时回落 `/pool?kind=dt.count`）≥ 阈值；
  3. 持仓股跌停（显式跌停价，或按昨收推：主板 10%、创业板/科创板 20%）或停牌
     （chives-radar `/state` 的 `suspended:true` 或 `status` 为 `suspended/halt/停牌`）。
- 命中生成一条 L3 `emergency` 信号（`decide:true`、`primary.action:"ack"`），
  `brief` 即应急触发链：**暂停新增风险→核实行情/成交/公告→查组合敞口与现金→按既定规则处理→记录事件与偏差**；
  同时写一条 `emergency` 触发。**同一原因当日只出一次**（`emergency_marks` 按 `(day, reason)` 去重），
  次日重新计数；休市、盘前、盘后不触发。持仓代码只进私有上下文包，不进信号文字与日志。

## 每日收益快照

- 交易日 `snapshots.close_time`（默认 15:05）之后写一条当日快照；一天一条（`INSERT OR IGNORE`）。
- 启动时若今天已收盘且尚无快照，补写**今天**这一条；**不回补历史**。
- `/portfolio/history` 只返回 sqlite 里已存的快照；`days` 只限制返回条数，不会生成数据。
- 非交易日（周末或 `calendar_file` 之外）不写。

## 安全与限制

- 只绑定 `127.0.0.1`；校验 `Host` 必须是回环；写接口只接受 JSON、拒绝额外字段。
- 网络：hub 自身只允许 `127.0.0.1:8865`、`127.0.0.1:8866`、`https://qt.gtimg.cn`、`https://web.ifzq.gtimg.cn`、备用 `https://ifzq.gtimg.cn`（测试模式可覆盖为回环，非测试模式覆盖只允许这两个 https 主机）；`risk` 复用 portfolio-mcp 的 K 线客户端（该包自己的固定主机），只在 `/portfolio/overview` 需要时触发。
- 不读取/写入任何凭据；不读 `~/.dsh` 之外的文件（持仓文件按上面的路径链解析）。
- 不调用模型；不做交易；不新增依赖。
- **已知限制**：
  - `price_cross` 按“当前价已越过阈值”判定，不区分同一轮询内的瞬时穿越；
  - 误报折叠按“同对象同规则同一天”，不是跨对象的全局折叠；
  - `risk` 是 250 日窗口的近似值，K 线缺失时为 null；
  - `snooze` 的 `close`/`next_open` 用 `calendar_file` 判断交易日，缺失时只看工作日；
  - 不含融资融券负债、多账户合并、分红送转自动调整。

## 测试

`tests/` 覆盖：设置 11 项的取值范围与 adopt/set/clear/dismiss/suggest、suggest 不改 value、
未采纳不参与纪律判定、纪律三种暂停规则与每日去重、仓位余量、复盘 schema/覆盖 revision/休市简包/
missing、作战卡 Cond 白名单、09:25 锁定后的允许/拒绝操作、
假 chives-radar 驱动的下发/撤销/对账/镜像/历史去重/退避与不可达恢复、sizing 手算与各 capped_by、候选统计手算、新信号 kind 映射、
配置与主机白名单、信号映射/方向/结论抽取/合并/误报/排序、折叠卡累加与
`merged_today` 跨天清零、用户处理卡不复活、动作与 snooze 到点恢复、
计划创建/校验/确认/评估/触发/过期/上限、文本拒绝（账号形态/指令式/敏感串）、持仓估值手算对拍、
风险缓存与 null+reason、快照幂等/不回补/休市补写/历史查询、private 标记与日志不含持仓、
分时迷你线（解析、降采样首尾与 ≤60 点、代码前缀、非当日/空 → missing、缓存与限频、
30 码上限、非法参数、部分失败、盘后、上游超时、公开主机白名单）、
API 逐端点契约、恶意 JSON/超长请求体/重定向不跟随/上游宕机降级、并发写；
触发队列（产生/去抖/不产生/`since_id` 分页/事务回滚/环境触发/手动降级）、上下文包
（字段/冻结/12KB 裁剪/missing/仅已采纳阈值/持仓关系/私有与日志）、判断回写
（一次性/清洗拒绝/不改状态/diverges/信号文字/计数/HTTP 语义）、指引卡
（五个时点/窗口/无 active 卡/重启不重复/`theme_state` 全分支/风险边界）、应急
（两条阈值/未采纳不触发/持仓跌停停牌/去重/休市/触发链）。
