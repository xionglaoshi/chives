# market-watch API 契约（v1.5 / T157，验收者维护，后端与前端都以它为准）

> **T157 变更**：market-watch 只保留规则层，所有取数经本机网关 `POST 127.0.0.1:8868/v1/call`；
> 对外 `/overview`（含 `regime`）、`/alerts` 与告警事件格式保持兼容。数据类端点继续保留，但字段
> 来源改为网关；网关覆盖不到的字段为 `null` + `reason`，不再有东财直连口径。

背景：个股盯盘由 `cn-watch`（127.0.0.1:8865）负责；**大盘/板块/情绪**由新引擎 `market-watch`（127.0.0.1:**8866**，纯本机回环，只读 GET，无认证，浏览器只经 `watch-panel` 的 Host 半同源代理访问）负责。字段和刷新条件见下列端点说明。

## 通用约定
- 所有响应 JSON，UTF-8；时间一律 ISO8601 带 `+08:00`；每个数据块带 `as_of`（数据源给出的时间，不是抓取时间）与 `fetched_at`、`source`、`stale`（布尔，超过该块的新鲜度阈值即为 true）。**取不到的数值为 `null` 并带 `reason`，不得用旧值或 0 顶替**。
- 金额字段名以 `_yuan` 结尾（单位元）；比例字段以 `_pct` 结尾（**百分数，如 1.25 表示 +1.25%**，与 cn-watch 口径一致）；比率以 `_ratio` 结尾（小数）。家数为整数。
- 错误：HTTP 200 + `{"ok": false, "error": {"code","message"}}` 用于业务错误；上游异常不得让接口 500。
- **行业板块代码**：T157 起行业口径由网关提供（同花顺/新浪分类），**不再保证有 `BKxxxx` 代码**；`/sectors` 行的 `code` 可能为 `null`，客户端应以 `name` 为主键。`level` 仍接受 `sw1`/`industry` 作为兼容别名，但返回 `taxonomy:"gateway_industry"`、`fallback:true`。`/sectors/{code}` 只在网关行确实带代码时可用；`/sectors/{code}/members`、板块 `trend`/`history` 已弃用（空数组/`null` + `reason`）。指数代码仍用 `000001.SH` 形式。
- **冷启动与休市**：引擎启动后**无论是否交易时段都必须立刻完整取数一次**，并把每个数据块的**最后有效值持久化到 sqlite**；重启时先加载上次的最后有效值再轮询。休市时返回最后有效值（`stale:false` + `state_note`），**不得因休市而返回空值**。
- 休市/非交易时段：`trading_state` ∈ `pre_open | open | lunch | closed | holiday`；休市时返回最后一次有效值并 `stale:false`、`state_note:"休市，显示上一交易时段最后值"`。

## 端点
| 方法 路径 | 返回 |
|---|---|
| `GET /health` | `{ok, as_of, trading_state, gateway:{requests,failures,last_error?,last_ok?,tools}, sources:{index,breadth,limit_pool,industry,movers,flows,themes,daily_spark,pool_history,breadth_series}, rules:{enabled,suppressed,suppressed_counts,suppressed_reasons}, limits:{alerts}, sector_universe, no_fallback, backfill}`；每个 source 带 `ok/age_s/primary/last_error?/fallback?` |
| `GET /overview` | `{ok, as_of, trading_state, indexes:[{code,name,price,prev_close,change_pct,amount_yuan,volume_ratio?,spark:[{t,p}...],as_of,stale}], breadth:{up,down,flat,up_ratio,limit_up,limit_down,broken,seal_ratio,max_streak,amount_yuan,as_of,stale,reason?}, regime:{label:"risk_on|neutral|risk_off",reasons:[...]}}`；指数固定 6 个：上证 000001.SH、深证成指 399001.SZ、创业板指 399006.SZ、沪深300 000300.SH、中证1000 000852.SH、科创50 000688.SH；`spark` 为当日分钟或 3 秒采样降采样后的 ≤120 点 |
| `GET /sectors?level=sw1`（或 `industry`） | `{ok, as_of, level, rows:[{code,name,change_pct,amount_yuan,amount_share_ratio,rel_300_pct,up_count,down_count,limit_up_count,member_count,rank,rank_change_30m,leaders:[{code,name,change_pct}],laggards:[...],as_of,stale}], sort:"change_pct"}`；`rel_300_pct` 为 `change_pct − 沪深300涨跌幅`（百分点，本地计算）；`source:"gateway.market_sectors"`、`taxonomy:"gateway_industry"`；网关不提供的 `code/limit_up_count/member_count` 等为 `null` |
| `GET /sectors/{code}` | **已弃用板块趋势/历史**：仍返回行字段，`trend:[]`、`history{ret_5d_pct:null,...}` + `reason`；只有网关行带代码时可查 |
| `GET /sectors/{code}/members` | **已弃用**：网关行业口径没有成分，返回 `{ok:true, rows:[], reason}` |
| `GET /alerts?since_id=N&limit=50` | `{ok, alerts:[{id,ts,rule_id,object:{type:"index|sector|stock",code,name},severity:"L1|L2|L3",title,detail,payload,status:"new|analyzed|skipped",analysis_id?}], next_id}`；R1/R2 正常，R3–R6 在 `/health.rules.suppressed` 标 `sector_taxonomy_changed` |
| `GET /rules` | 规则清单：`id, name, enabled, params（含阈值）, confirm, cooldown_minutes, level` |

## 运行与限频
- 轮询分层（默认）：指数 3 秒；宽度 20 秒；行业 20 秒；涨停/炸板池 40 秒；榜单/资金流 30 秒；指数日线 300 秒。**所有请求只发往 `gateway.url`（默认 `http://127.0.0.1:8868`），网关自身负责上游限频/熔断**。
- 全部为**确定性计算**，不调用模型；告警由独立的触发器（后续任务）决定是否交给模型分析。
- 单位换算（元/万元/百万元/亿元、手/股）在引擎内部完成并有单元测试；对外只暴露上表单位。

## v1.2 新增（工作台单页）
| 方法 路径 | 返回 |
|---|---|
| `GET /movers?kind=gainers\|losers\|active&limit=10&include_st=0&include_new=0&include_bj=0` | `{ok, as_of, kind, rows:[{rank, code:"600519.SH", name, price, change_pct, amount_yuan, turnover_pct?, industry?}], filters:{include_st,include_new,include_bj}, source, stale, state_note?}`；全 A 范围（沪深主板/创业板/科创板，北交所按 `include_bj`）；`kind` 白名单三种；`limit` 5–20（默认 10）；`active` 按成交额降序；默认排除 ST/*ST、上市不足 5 个交易日的新股；休市返回最后有效值；取不到 `rows:[]` + `reason` |
| `GET /summary` | `{ok, as_of, generated_by:"engine", headlines:[{id, tone:"up\|down\|neutral\|warn", title, body, refs:[{type:"index\|sector\|stock", code, name}]}], note?}`；**3–5 条**，由确定性规则生成，**每条的每个数字都必须能在 `/overview`、`/sectors`、`/movers` 里找到**（不得编、不得用模型）；覆盖：指数总体、宽度与成交额（与前一交易日对比，前一日缺失则不写对比）、最强与最弱行业（成分≥10）、涨停生态（涨停/跌停/炸板/最大连板）、有告警时的一条风险提示；数据缺失的条目整条省略 |
| `GET /overview` 的 `indexes[].spark` | 盘中为分时降采样（≤120 点）；**休市/无分时则回退为最近 30 个交易日收盘**；新增 `spark_kind: "intraday"\|"daily"` |

## v1.3 新增（资金流向）
| 方法 路径 | 返回 |
|---|---|
| `GET /flows?kind=sector_in\|sector_out\|stock_in\|stock_out&limit=10` | `{ok, as_of, kind, rows:[{rank, code, name, main_net_yuan, main_net_pct, change_pct, amount_yuan}], definition:"新浪资金流（个股主力=超大单 r0_net，行业/概念为净流入；厂商口径，仅作辅助参考）", source, stale, state_note?, reason?}`；`sector_*` 直接转发网关新浪行业榜，不再按东财行业宇宙过滤；`stock_*` 用与 `/movers` 相同的全 A 范围与过滤（默认排除 ST/次新/北交所，参数同 `include_*`）；`limit` 5–20；休市返回最后有效值；取不到 `rows:[]` + `reason` |
| `GET /flows/northbound` | `{ok, available:bool, reason?, as_of?, net_yuan?}`：**先验证是否有可用的免费日内源**，没有就 `available:false` + 原因，不得编 |

## v1.4 新增（复盘数据层：池明细/梯队/历史/昨日表现/宽度序列/概念榜）

所有端点仍是只读 GET，返回 JSON；通用约定（`as_of`/`source`/`stale`/单位/错误形状）与上文相同。v1.4 的参数错误返回 **HTTP 200 + `{"ok":false,"error":{"code","message"}}`**（本版没有沿用 `/flows` 的 400 例外）。日期参数一律 `YYYY-MM-DD`，省略时取最近一个已开盘的交易日；未来日期、非交易日、格式错误分别返回 `bad_request` / `not_trading_day` / `bad_request`。

| 方法 路径 | 返回 |
|---|---|
| `GET /pool?kind=zt\|zb\|dt&date=YYYY-MM-DD&limit=200` | `{ok, as_of, date, kind, count, rows, definition, source:"gateway.market_limit_pool", stale, reason?, state_note?}`；`count` 是池接口 `tc`（总家数，不受 `limit` 截断），`rows` 最多 `limit` 行（1–500）。行字段：`code`（`NNNNNN.SH/SZ`）、`name`、`price`（`p/1000`，缺失 null）、`change_pct`、`amount_yuan`、`turnover_pct`、`streak`（`lbc`，缺失 null）、`first_seal_time`（`HH:MM:SS`，缺失 null）、`broken_times`（`zbc`，缺失 null）、`industry`（`hybk`）、`seal_amount_yuan`（`fund`）。排序：`zt` 连板数降序+首封时间升序，`zb` 炸板次数降序，`dt` 成交额降序；并列按代码。已落库日期读 sqlite，未落库日期按 `date` 参数现取并落库；网关按 `date` 直接请求同花顺，单次最多 200 行，不提供成交额/行业（`missing`）；跌停池无直连源，`kind=dt` 返回 `unavailable` + 原因。 |
| `GET /pool/ladder?date=` | `{ok, date, max_streak, tiers:[{streak,count,rows?}], first_board_count, definition, source}`；`tiers` 按 `streak` 降序，`streak=1` 只给 `count` 不给 `rows`，其余层最多 8 行（字段同 `/pool`）；`first_board_count` 是 `streak=1` 家数。取不到涨停池时 `max_streak:null`、`tiers:[]`、`first_board_count:null` + `reason`。 |
| `GET /pool/history?days=10..30`（默认 20） | `{ok, as_of, days:[{date, zt, dt, zb, seal_ratio_pct, max_streak, promote_1to2_pct, promote_2to3_pct, promote_3up_pct, available, reason?}], backfill:{running,done,total,failed,started_at,finished_at}, definition, source}`；按交易日升序。`seal_ratio_pct=zt/(zt+zb)*100`；晋级率按股票代码跨相邻两日匹配：`1to2`=昨日 `streak=1` 中今日 `streak=2` 的家数 ÷ 昨日 `streak=1` 家数 ×100，`2to3`=昨日 2 中今日 3，`3up`=昨日 ≥3 中今日 ≥昨日+1；前一日缺失或分母为 0 时 `null`。某日三池未回补/取不到 → `available:false` + `reason`，数值不插值（`null`）；回补进行中返回已有部分并带进度。 |
| `GET /pool/yesterday` | `{ok, date, prev_date, avg_open_pct, avg_high_pct, avg_close_pct, win_ratio_pct, rows:[{code,name,prev_streak,open_pct,high_pct,low_pct,now_pct}], definition, source:"gateway.market_limit_pool+gateway.market_quote", reason?, state_note?}`；取 `prev_date` 的涨停池，用网关 `market_quote` 批量快照（每批 ≤20）算开盘/最高/最低/现价相对**今日昨收**的涨跌幅。`avg_close_pct` 是 `now_pct` 均值（收盘后即收盘价）；`win_ratio_pct` 是 `now_pct>0` 占比。今日未开盘（`pre_open`）返回 `rows:[]` + `reason`；休市日返回最近一个交易日相对其前一日（`date` 为该交易日）；快照取不到时 `rows:[]` + `reason`。 |
| `GET /breadth/series?date=` | `{ok, as_of, date, points:[{t:"HH:MM",up,down,flat,limit_up,limit_down}], gaps:bool, definition, source, reason?}`；交易时段每分钟一点（上午 09:30–11:29、下午 13:00–14:59，共 240 点），只保留最近 10 个交易日。重启造成的空窗不插值；缺少应有分钟点（或整日无点）时 `gaps:true`。 |
| `GET /themes?kind=concept&limit=20&sort=change\|amount` | `{ok, as_of, kind, sort, rows:[{rank, code:"BK0xxx", name, change_pct, amount_yuan, up_count, down_count, leader:{code,name,change_pct}\|null}], definition:"新浪概念板块（厂商口径）", source:"gateway.market_sectors", stale, reason?, state_note?}`；网关 `market_sectors(kind=concept)`；排除名称含“昨日”的衍生概念；`limit` 5–30。 |
| `GET /pool/by-industry?date=` | `{ok, as_of, date, rows:[{industry, zt_count, zb_count, max_streak, leaders:[≤3]}], definition, source, reason?}`；**行业口径**（网关行的 `industry`），不是题材口径；`leaders` 为该行业涨停池按连板数/首封时间排序的前 3（`{code,name,streak,change_pct}`）。 |
| `GET /health` | 在原有 `sources` 上新增 `pool_history`（`ok/days/available_rows/last_date/age_s/last_error?`）、`breadth_series`（`ok/days/points/last_date`）、`themes`（同其他源 `ok/age_s/last_error?`），并在顶层新增 `backfill:{running,done,total,failed,started_at,finished_at}`。`/summary`、`/overview` 原有字段不变。 |

落库与回补：
- 新增 sqlite `pool_day(day, kind, count, rows_json, fetched_at, available, reason)` 与 `breadth_series(day, t, up, down, flat, limit_up, limit_down)`；`day_stats` 补齐 `limit_down/broken/max_streak`（旧库自动加列）。
- 引擎在每个交易日 15:05 后补一次当日三池快照；首次启动（或库里缺交易日）后台回补最近 30 个交易日，逐日逐池调用池接口的 `date` 参数，**全程请求间隔 ≥1 秒**，不阻塞 `/health` 与其他端点。失败的日期写入 `available:false` + `reason`，本轮不重试；同一天三池都有记录（无论可用与否）后，下次启动不再重复回补。
- 池历史回溯上限由网关直连源决定，回补仍尝试 30 个交易日，取不到的日期如实标 `available:false`，不假设 30 天全可用。跌停池无直连源，回补时该池记 `available:false`。
- T157 已删除东财/腾讯/申万直连与备用源代码；本文件中的旧字段名仅作为契约兼容说明保留。
