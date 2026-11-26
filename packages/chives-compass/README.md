# Chives 罗盘

正式程序名为 `chives-compass`，生产服务监听本机 8866。由 `scripts/chives.sh start --engines` 启动，通过设置页「内核设置」查看状态。配置中的旧标识、MCP 工具名和已有数据目录用于兼容升级。

大盘 / 板块 / 情绪盯盘引擎（确定性、只读、本机回环）。与 `chives-radar`（个股，127.0.0.1:8865）并列：
`chives-compass` 负责 **6 个宽基指数 + 市场宽度/情绪 + 全 A 榜单/资金流/涨停池的只读展示 + 6 条横截面规则**。
**T157 起取数全部改走本机数据网关 `chives-data`（`POST 127.0.0.1:8868/v1/call`）**，
本包不再持有任何外部主机白名单、不再抓取东财/腾讯/新浪/乐咕/申万，只保留规则与对外契约。
R1/R2 照常工作；R3–R6 因网关行业口径没有稳定的板块代码、成分集合与涨停归属而停用，
原因在 `/health.rules.suppressed` 给出。

- Python ≥ 3.12，**只用标准库**（`urllib` / `http.server` / `sqlite3` / `threading` / `json`）；
  测试依赖仅 pytest。**不 import akshare / pandas / requests**。
- 取数 → 算指标 → 评估规则 → 存告警，全程不调用模型。
- 只发只读 `GET`；不连接券商、不交易、不读任何密钥。

## 快速开始

```bash
cd packages/chives-compass
python3.12 -m venv .venv            # 任务要求 ≥3.12
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q       # 491 个离线测试，不访问公网
```

运行（推荐用启停脚本，pid/日志/sqlite 都在仓库 `runtime/market/`）：

```bash
scripts/market-watch.sh check       # 校验配置
scripts/market-watch.sh start       # 127.0.0.1:8866
scripts/market-watch.sh status
scripts/market-watch.sh logs 100
scripts/market-watch.sh stop
```

手动运行：

```bash
cd packages/chives-compass
PYTHONPATH=src .venv/bin/python -m chives_compass --config config.example.yaml --check-config
PYTHONPATH=src .venv/bin/python -m chives_compass --config config.example.yaml          # 常驻
PYTHONPATH=src .venv/bin/python -m chives_compass --config config.example.yaml --once   # 轮询一次并打印 /overview
```

`scripts/market-watch.sh` 默认用 `packages/chives-compass/config.yaml`；该文件不存在时直接用
`config.example.yaml`。`MARKET_WATCH_CONFIG=/abs/path.yaml` 可指定别的配置。

## 配置

配置使用 **YAML 的极小子集**（`src/market_watch/yamlmini.py`：块状映射、`[a,b]`/`{k: v}`、
标量、注释；不支持锚点/多行字符串）。相对路径以配置文件所在目录为基准。

| 键 | 默认 | 说明 |
|---|---|---|
| `api.host` / `api.port` | `127.0.0.1` / `8866` | host 只允许回环；服务实际永远绑定 `127.0.0.1` |
| `runtime.db_path` | `../../runtime/market/market.db` | sqlite（告警、日频基线、成分缓存、**各数据块最后有效值**） |
| `runtime.out_dir` | `../../runtime/market` | 仅用于脚本/日志目录 |
| `calendar.source` / `.file` | `weekdays` / — | `file` 读 `config/trade_calendar.json`（只读）；缺失时降级为工作日 |
| `watchlist_file` | — | 只读 chives-radar 的 `config/watch.yaml` 里的 `watchlist`（R1/R6 的自选股快照用） |
| `gateway.url` | `http://127.0.0.1:8868` | 唯一取数入口；必须是回环 http(s)，不接受凭据 |
| `polling.*_seconds` | 指数 3 / 宽度 20 / 板块 20 / 涨停池 40 | 分层轮询；板块沿用 `breadth_seconds` 的节奏 |
| `polling.member_min_interval_seconds` | `0.5` | 只对仍保留的板块成分接口生效；当前网关行业口径没有成分，端点返回 `reason` |
| `polling.timeout_seconds` | `5` | 单请求超时（上限 5） |
| `polling.movers_seconds` | `30` | 全 A 榜单轮询间隔；上游 `clist` 缓存 TTL 固定 ≥15 秒 |
| `polling.flows_seconds` | `30` | 资金流榜（行业 + 个股两个方向）轮询间隔；上游缓存 TTL 固定 ≥20 秒 |
| `polling.daily_spark_seconds` | `300` | 指数日线缓存刷新间隔（≥5 分钟），供休市迷你线回退 |
| `polling.stale_after_seconds.{index,breadth,limit_pool,industry}` | 15/90/150/90 | 各块新鲜度阈值 |
| `limits.max_per_minute.gateway` | `600` | 网关请求的本地预算；`/health.limits` 公开 |
| `limits.max_concurrency` | `2` | 每源并发上限（硬上限 2） |
| `limits.alert_max_per_hour` | `10` | 全局限流：每小时最多写入的告警条数 |
| `suppression.{enabled,open_minutes,close_minutes}` | true/15/5 | 开盘前 15 分钟、收盘前 5 分钟只计数不发送 |
| `rules.R1..R6.{enabled,level,confirm,cooldown_minutes,params}` | 见下表 | 阈值/确认/冷却/级别均可配 |

**热更新**：引擎按配置文件的 mtime 检测变更，成功则替换规则/阈值/限流/抑制窗口与自选股
（保留规则确认/冷却状态）；解析或校验失败时 **保留旧配置**，并在
`GET /health` 返回 `config_reload_error`。`db_path` 与 `api.port` 的变更需要重启。

## HTTP API（127.0.0.1:8866，只读 GET）

| 路径 | 说明 |
|---|---|
| `GET /health` | `gateway` 连通性、每个块 `ok/age_s/last_error?`、`trading_state`、`sector_universe`（网关口径）、启用的规则与 `suppressed`、限流、`config_reload_error?`；`no_fallback` 列出网关覆盖不到的字段/能力 |
| `GET /overview` | 6 个指数（现价/昨收/涨跌幅/成交额/`spark`/`spark_kind`）、宽度/情绪、`regime`；涨跌家数块带 `previous_day{amount_yuan,limit_up}`（引擎自己的日快照，缺失则无该键） |
| `GET /movers?kind=gainers\|losers\|active&limit=10&include_st=0&include_new=0&include_bj=0` | 全 A 榜单（v1.2）：涨幅/跌幅/成交额，`limit` 5–20 |
| `GET /flows?kind=sector_in\|sector_out\|stock_in\|stock_out&limit=10&include_st=0&include_new=0&include_bj=0` | 主力净流入榜（v1.3）：行业宇宙内升/降序、全 A 个股升/降序，`limit` 5–20，非法参数 HTTP 400 |
| `GET /flows/northbound` | 北向可用性：交易所自 2024-08-19 起不再实时披露净买入，恒返回 `available:false` + `reason`，不给数字 |
| `GET /pool?kind=zt\|zb\|dt&date=&limit=` | 涨停/炸板/跌停池明细，优先读 sqlite，未落库时经网关按 `date` 现取；网关单次最多 200 行，跌停池无直连源时 `reason`；行业/成交额可能为 null |
| `GET /pool/ladder?date=` | 连板梯队（v1.4）：按 `streak` 降序，1 板只给家数，其余层最多 8 行 |
| `GET /pool/history?days=10..30` | 封板率与 1进2/2进3/3板以上晋级率（v1.4），缺失日 `available:false` 不插值，带 `backfill` 进度 |
| `GET /pool/yesterday` | 昨日涨停股今日开/高/低/现价相对昨收（v1.4，腾讯批量快照） |
| `GET /pool/by-industry?date=` | 行业口径的涨停/炸板家数（v1.4），不是题材口径 |
| `GET /breadth/series?date=` | 盘中每分钟涨跌家数与涨停/跌停序列（v1.4），最近 10 个交易日，重启空窗 `gaps:true` |
| `GET /themes?kind=concept&limit=5..30&sort=change\|amount` | 网关概念板块榜（新浪口径，`taxonomy:"gateway_concept"`），排除“昨日…”衍生概念 |
| `GET /summary` | 确定性市场摘要（v1.2）：3–5 条 headline，`generated_by:"engine"` |
| `GET /sectors?level=sw1`（或 `industry`） | 网关行业排行（同花顺/新浪口径，`taxonomy:"gateway_industry"`、`fallback:true`）；名称稳定、外部板块代码可能为 null，`limit_up_count`/`rank_change_30m`/`leaders` 的缺失项为 null；`rel_300_pct` 可由网关行情计算 |
| `GET /sectors/{code}` | 仅当网关行带代码时可用；`trend`/`history` 已弃用，返回空数组与 `reason` |
| `GET /sectors/{code}/members` | 已弃用：网关行业口径没有成分；返回空 `rows` + `reason` |
| `GET /alerts?since_id=N&limit=50` | 告警流（id 升序），`next_id` 供轮询；`status` 初始 `new` |
| `GET /rules` | 规则清单（`id/name/enabled/params/confirm/cooldown_minutes/level`） |

约定：

- 板块 id 不再是 `BKxxxx` 契约：`/sectors` 行的 `code` 可能为 null，客户端应以 `name` 为主键；
  `/sectors/{code}` 只接受网关实际返回的代码，未知代码返回 `{"ok": false, "error": {"code": "unknown_sector"}}`。
- 时间一律 ISO8601 带 `+08:00`；每个数据块带 `as_of`（源时间，源不提供时为本地抓取时间）、
  `fetched_at`、`source`、`stale`。
- 取不到的数值为 `null` 并带 `reason`；**不用旧值或 0 顶替**。上游异常返回 HTTP 200 +
  `{"ok": false, "error": {"code","message"}}`，不会 500。
- `_pct` 字段是百分数（`1.25` 表示 +1.25%）；`_ratio` 是小数；`_yuan` 是元；家数是整数。
- 未知路径 404、非 GET 405；`/sectors?level=sw2` 等业务错误返回 200 + `ok:false`。
- 休市（`pre_open/lunch/closed/holiday`）返回最后一次有效值，`stale:false`，
  `/overview` 与 `/sectors` 带 `state_note:"休市，显示上一交易时段最后值"`。

## 数据来源（T157：只经网关）

`chives-compass` 只向 `gateway.url`（默认 `http://127.0.0.1:8868`）发 `POST /v1/call`，请求体
`{"tool": "...", "args": {...}}`。源码中没有任何外部行情主机，`127.0.0.1:8868` 是唯一允许地址。
`tests/test_gateway_only.py` 会扫描 `src/` 并断言这一点。

| 本地块 | 网关工具 | 用途 |
|---|---|---|
| 指数 + 自选股快照 | `market_quote`（每批 ≤20 个代码） | `/overview` 的 6 个指数、R1 的成交额基线、`/pool/yesterday` 的今日快照 |
| 市场宽度 | `market_overview` | `/overview.breadth` 的涨/跌/平家数与全市场成交额 |
| 涨停/炸板/跌停池 | `market_limit_pool`（`kind=zt/zb/dt`，`limit=200`） | `/pool*`、封板率、连板梯队；`date` 由网关接受 |
| 行业排行 | `market_sectors`（`kind=industry`） | `/sectors`、`/flows` 的行业维度 |
| 概念排行 | `market_sectors`（`kind=concept`） | `/themes` |
| 全 A 榜单 | `market_movers` | `/movers` |
| 资金流 | `market_fund_flow`（`sector/rank`） | `/flows` |
| 指数日线 | `market_bars`（`interval=1d`） | 休市迷你线 `spark` |
| 北向 | `market_northbound` | 恒不可用，给 `reason`，不造数 |

**网关覆盖不到、按现有外壳写 `missing`/`unavailable` 的能力**（同时写入 `/health.no_fallback`）：

- **跌停池**：无直连源，`/pool?kind=dt` 返回 `reason`；
- **按日期回补的涨停历史**：网关直连按 `date` 取同花顺，单次最多 200 行，且无成交额/行业；
- **板块代码、成分、板块日线/分时**：网关行业口径没有这些字段，`/sectors` 行的 `code` 可能为 null，
  `/sectors/{code}` 的 `trend`/`history` 与 `/sectors/{code}/members` 已弃用；
- **`limit_up_count`**：原口径依赖板块成分，网关行业口径没有成分，恒为 null；
- **北向净流入**：交易所已停止实时披露，任何源都不产出；
- **申万健康检查**：已随直连层删除。

## 指标口径

| 指标 | 公式 / 口径 |
|---|---|
| `change_pct` | 网关 `market_quote` / `market_sectors` 返回的百分数；缺失为 `null` |
| `rel_300_pct` | `板块 change_pct − 沪深300 change_pct`（百分点，算术超额；仅本地计算，不再与原口径可比） |
| `amount_share_ratio` | `板块成交额 / 全市场成交额`；分母 = 上证指数 + 深证成指成交额（不含北交所） |
| `up_ratio` | `上涨家数 / (上涨家数 + 下跌家数)`，平盘/停牌不计入分母 |
| `seal_ratio` | `ZT / (ZT + ZB)`（小数，不是百分数）；`market_limit_pool` 直连缺失时由本地用 `zt/zb` 计数计算 |
| `max_streak` | 涨停池 `max(streak)` |
| `limit_up_count` | 原口径为“涨停池代码 ∩ 行业成分”；网关行业口径没有成分，**该字段为 `null`** |
| `member_count` | 网关行业行提供时使用；同花顺行业汇总不提供，为 `null` |
| `leaders` | 网关行业行的 `leader`（领涨股名称/代码/涨跌幅）；缺失为 `null`/空列表 |
| `laggards` | 已弃用；网关行业口径没有成分，恒为 `[]` |
| `volume_ratio` | `成交额 / (过去最多 5 个完整交易日的日均成交额 × f(t))`，`f(t)=已交易分钟/240`（跳过午休，开盘至少按 1 分钟计）；过去不足 5 日用现有天数，0 日则为 `null` |
| `rank` | 网关行业行内按 `change_pct` 降序，1 = 最强；并列按名称稳定排序 |
| `rank_change_30m` | `30 分钟前排名 − 当前排名`；**正数 = 排名上升**；不足 30 分钟为 `null` |
| `regime` | `risk_off`：R1 或 R2 当前处于触发窗口；`risk_on`：`up_ratio ≥ 0.6` 且上证/深证/沪深300 全部为正；其余 `neutral`，`reasons` 给中文理由 |

`spark`（指数迷你线）：`open`/`lunch` 用当日 3 秒轮询价格按“保留首尾的均匀降采样”压到 ≤120 点
（`spark_kind:"intraday"`）；`pre_open`/`closed`/`holiday` 回退为**最近 30 个交易日收盘**
（`spark_kind:"daily"`，经网关 `market_bars` 取指数日线，缓存 300 秒，冷启动也抓）。

`sectors/{code}.trend` 与 `.history` 已弃用：网关行业口径没有板块日线/分时，返回 `[]`/`null` + `reason`。

## 全 A 榜单与资金流

- `/movers`：`kind=gainers|losers|active`，`limit` 5–20；网关只返回排序后的前 20 行，本地再做
  ST/新股/北交所过滤与截断，因此极端情况下行数可能少于 `limit`。
- `/flows`：`kind=sector_in|sector_out|stock_in|stock_out`，`limit` 5–20。行业维度直接转发网关
  `market_fund_flow(scope=sector)`（新浪行业口径），个股维度转发 `scope=rank`。非法参数仍返回 HTTP 400。
- `definition`：资金流统一标注“新浪资金流（个股主力=超大单 r0_net，行业/概念为净流入；厂商口径，
  仅作辅助参考）”，不再声称是东财主力口径。
- 缓存 TTL 20 秒；盘中按 `polling.flows_seconds`（默认 30 秒）轮询；冷启动与休市都完整取一次并写回 sqlite。
- 北向：交易所自 2024-08-19 起不再实时披露净买入，网关不输出净流入；`/flows/northbound` 恒
  `available:false` + `reason`，不返回 `net_yuan`/`as_of`，不把 0 当真实值。

## 市场摘要（v1.2）

`calc/summary.py` 是纯函数（无 I/O、无时钟、不调用模型），输入就是同一时刻 `/overview`、`/sectors`、
`/movers` 的返回、引擎 sqlite 里的上一交易日快照与当日告警。最多 5 条：

| id | 内容 | 数字来源 |
|---|---|---|
| `indexes` | 上证/深证/创业板涨跌幅 + 收涨/收跌措辞 | `/overview.indexes[].change_pct` |
| `breadth` | 涨跌家数、上涨占比、涨停数、全市场成交额；有前一日快照时附“上一交易日”对比 | `/overview.breadth`、`/overview.breadth.previous_day` |
| `sectors` | 成分 ≥10 的最强/最弱行业及涨幅 | `/sectors.rows` |
| `limit` | 涨停/跌停/炸板/最大连板 + 涨幅榜首位 | `/overview.breadth`、`/movers.rows[0]` |
| `risk` | 当日有告警时一条风险提示（标题用规则中文名，不含数字） | `/alerts` 的规则与对象 |

数据缺失的条目整条省略；文案不带买卖建议。前一日快照由引擎在成功取数后写入 sqlite `day_stats`
（成交额、涨停数），当天没有历史行时不写对比。

## 复盘数据层

| 端点 | 口径 |
|---|---|
| `/pool?kind=zt\|zb\|dt&date=&limit=` | 网关 `market_limit_pool` 的 `count` 为家数（不受 `limit` 截断），`limit` 1–500；行字段沿用 `price/change_pct/amount_yuan/turnover_pct/streak/first_seal_time/broken_times/industry/seal_amount_yuan`，缺失为 `null`。`zt` 连板数降序+首封升序，`zb` 炸板次数降序，`dt` 成交额降序。跌停池无直连源时给 `reason`。 |
| `/pool/ladder` | 按 `streak` 分层，降序；`streak=1` 只有 `count`，其余层最多 8 行；`first_board_count` 为 1 板家数。 |
| `/pool/history` | `seal_ratio_pct=zt/(zt+zb)×100`；晋级率按代码匹配相邻两日；某日缺失 `available:false`，不插值。 |
| `/pool/yesterday` | 昨日涨停池 × 网关批量快照；开/高/低/现价均相对**今日昨收**；休市日返回最近交易日相对其前一日。 |
| `/breadth/series` | 交易时段每分钟一点（09:30–11:29、13:00–14:59，共 240 点），只留最近 10 个交易日；首点优先；`gaps` 按应有分钟网格判断，重启空窗不插值。 |
| `/themes` | 网关 `market_sectors(kind=concept)`（新浪口径），排除名称含“昨日”的衍生概念；`limit` 5–30。 |
| `/pool/by-industry` | 按池内 `industry` 分组，不是题材口径；一只股票只按池内一行计一次；`leaders` 最多 3。行业字段缺失时该组为“未分类”。 |

/health 暴露 sources.pool_history、sources.breadth_series、sources.themes 与顶层 backfill；
`/summary`、`/overview` 原有字段不变。池历史与宽度序列仍写 sqlite；池历史回补按日期请求网关，
单次最多 200 行、请求间隔 ≥1 秒，失败日期记 available:false，不重试同一日。

已知限制：网关直连的涨停池没有成交额/行业（为 null）；跌停池不可用；历史回溯深度由同花顺接口
决定，报告不写死天数；`/pool/yesterday` 的行情是**请求时点**的快照，不是历史回放。

## 规则 R1–R6（默认值）

R1/R2 照常评估；R3–R6 依赖板块代码、成分与涨停归属，网关行业口径不提供，因此停用并在
`/health.rules.suppressed` 标记 `sector_taxonomy_changed`。规则参数仍保留在配置里，便于以后
网关补上稳定行业代码后恢复。

| ID | 触发 | 确认 | 冷却 | 级别 |
|---|---|---|---|---|
| R1 指数放量下跌 | `change_pct ≤ -1.0%` 且 `volume_ratio ≥ 1.5`；无基线不触发 | 2 次 | 60 min | L2 |
| R2 宽度恶化/背离 | (`up_ratio ≤ 0.30` 且沪深300 `≥ -0.3%`) 或 30 分钟内 `up_ratio` 下降 ≥0.15 | 3 次 | 60 min | L2 |
| R3 板块排名跃升 | 排名 ≤5、30 分钟前 ≥15（提升 ≥10）、涨幅 ≥1.5%、`up_ratio ≥ 0.6`、成分 ≥10、成交额 ≥5 亿 | 2 次 | 30 min | L2 |
| R4 板块涨停骤增 | 30 分钟涨停家数 +≥3、当前 ≥5、`up_ratio ≥ 0.5`、成分 ≥10、成交额 ≥5 亿 | 2 次 | 30 min | L2 |
| R5 相对强弱穿越 | `rel_300_pct` 上/下穿 0，±0.3 个百分点缓冲，且行业自身涨跌同向 | 2 次 | 60 min | L1 |
| R6 个股-板块背离 | 自选股相对行业 30 分钟超额 ≤ -3%，个股 `volume_ratio ≥ 2`；仅 `config/watch.yaml` 的 `watchlist`；ST/新股/B 股/涨跌停跳过；映射不到不触发 | 2 次 | 30 min | L2 |

- **确认**：连续 N 次轮询条件成立。条件中断即清零。
- **冷却 + 再武装**：触发后 `armed=false`；必须“条件已回撤 + 距上次触发 ≥ 冷却”才重新武装。
- **抑制**：开盘 15 分钟、收盘前 5 分钟只累计 `suppressed`，不写告警。
- **聚合**：同一时刻同一规则多个对象合并为 1 条，`payload.objects[]` 列出全部对象与各自 metrics。
- **风暴上限**：全局每小时最多 `limits.alert_max_per_hour` 条（默认 10），超出只计数。
- **存储**：sqlite `alerts` 表（`status` 默认 `new`，预留 `analysis_id`），`GET /alerts` 按 id 升序返回。

## 冷启动、持久化与休市

- 进程启动（`Engine.__init__`）先读 sqlite `blocks` 表的**最后有效值**；`__main__` 在开 HTTP 前调用
  `engine.bootstrap()`，因此服务一上线就有数据，重启不会白屏。
- 启动后**无论 `trading_state` 都立即完整取数一次**：指数、宽度、涨停池、板块各自独立，
  某源失败只影响该块（保留旧值 + `reason`），不会拖垮其他源。
- 每次成功取数后把该块写回 `blocks`（`index/stock/breadth/pool/boards/members:*/history:*/trend:*`）；
  失败时**不覆盖**旧值，只把 `reason` 附在内存块上。
- 休市（`pre_open/lunch/closed/holiday`）返回最后有效值，`stale:false` + `state_note`；
  只有交易时段内超过 `stale_after_seconds` 才标 `stale:true`。
- 上游全挂且有旧值：返回旧值；交易时段内超过阈值时 `stale:true`。上游全挂且无旧值：`null` + `reason`。

## 轮询、限频与降级

- 分层：指数 3 s；宽度 20 s；板块 20 s；涨停池 40 s；日线 300 s；榜单/资金流 30 s。
- 所有请求都发往同一个回环网关；本地不再维护每源令牌桶/熔断。`/health.gateway` 记录请求数、
  失败数、最后错误与每个工具的次数。
- 降级：单块失败该块保留旧值并带 `reason`；字段缺失只在行内 `reason` 注明；休市时保留最后有效值
  并标 `state_note`。**不把旧值冒充当前值。**

## 交易日历与休市

- 读 `config/trade_calendar.json`（只读，和 chives-radar 同一文件）；缺失/损坏时降级为“周一到周五”，
  `/health.calendar_status` 为 `degraded`。
- `trading_state`：`pre_open`(<09:30) / `open`(09:30–11:30, 13:00–15:00) / `lunch` / `closed`(≥15:00) / `holiday`。
- 盘中正常轮询；午休只轻量刷新指数；休市期间只在 09:25–09:30 与 15:00–15:05 各刷新一次。
  冷启动不受这些窗口限制。

## 测试

测试使用 `tests/support.py` 的假网关（`FakeClient.call/data`），把旧样本转换成网关外壳；
`R1/R2`、`regime`、`/alerts` 契约测试保留。已删除只测旧直连解析器的测试（东财/腾讯/申万/备用源），
只保留仍适用的纯函数与契约测试。当前 **491 个离线测试**，不访问公网。

```bash
cd packages/chives-compass && .venv/bin/python -m pytest -q
```

覆盖：YAML/配置校验与热更新、网关地址必须是回环、配置/持久化/重启、上游全挂时有旧值/无旧值、
`stale`、R1/R2 的触发/确认/冷却/再武装/抑制/聚合/风暴上限、regime、`/alerts` 分页、
榜单/资金流/池/主题的字段与过滤、sqlite 并发读写、9 个端点契约，以及
`tests/test_gateway_only.py` 对“源码无外部主机、只有 127.0.0.1:8868、无 push2/eastmoney”
的静态断言。

`tests/fixtures/` 是 2026-11-03 录制的旧直连样本，仅作为假网关的输入数据保留；
不再有生产代码解析它们。

## 已知限制 / 待验证

1. **R3–R6 停用**：网关行业口径没有稳定的板块代码、成分集合与涨停归属；`/health.rules.suppressed`
   给出 `sector_taxonomy_changed`。R3/R4 的成员数/涨停归属、R5 的 30 分钟排名、R6 的个股-板块
   映射都不可用。
2. **板块代码**：同花顺行业汇总只给名称，`/sectors` 行的 `code` 为 `null`；`/sectors/{code}` 只能
   在网关行确实带代码时使用。`/sectors/{code}/members`、板块日线/分时已弃用，返回空 + `reason`。
3. **跌停池**：网关没有不含禁用主机的直连源，`/pool?kind=dt` 为 `unavailable`/`reason`。
4. **涨停历史**：同花顺直连单次最多 200 行，且没有成交额/行业；`/pool/history` 的晋级率在历史日
   缺失时为 `null`，不插值。
5. **北向**：交易所自 2024-08-19 起停止实时披露，`/flows/northbound` 恒不可用。
6. **`rank_change_30m` 与 `rel_300_pct`**：本地计算，重启后前 30 分钟为 `null`；不再与原东财口径
   逐项可比。
7. **`volume_ratio`**：用“日均成交额 × 已交易分钟占比”的粗口径，不是 5 日同刻基线；首日无基线为
   `null`。
8. **指数 `spark`**：盘中是 3 秒自采样降采样，不是分钟 K；重启后当日已采样的点会丢失。休市回退的
   日线最多 30 点，最后一点是最后一个交易日的收盘，不是实时价。
9. **冷启动请求量**：6 个指数 + 自选股、宽度、3 个池、行业/概念、榜单、资金流、6 条指数日线，
   全部经网关；网关自身缓存/限频，不再由本包控制。
10. 免费接口的参数/字段可能变化；本 README 的口径基于 2026-11-03/17 的样本与网关现有实现，需持续回归。

## 与 chives-radar 的关系

- 结构对齐：配置热更新、`/health`、纯标准库 HTTP、pytest 风格、`scripts/*.sh` 启停方式。
- 不复用 chives-radar 的 `watchlist` 语义（它明确拒绝指数）。`chives-compass` 只读它的 `watchlist`
  用于 R6，不改该文件。
- 数据、告警、状态完全独立：`runtime/market/market.db` vs `runtime/watch/`。
