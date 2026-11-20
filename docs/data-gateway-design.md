# Chives A 股研究数据网关

## 2. 设计原则
1. **按能力对外，不按来源对外**：工具名表达"要什么"（行情、日线、资金流），不表达"从哪拿"。
2. **一个进程，全局共享**：网关是本机常驻守护进程，所有 bot 共用同一份限流计数、熔断状态和缓存；每个 bot 只挂一个轻量 MCP 转发层。
3. **统一字段字典**：代码、时间、单位、百分数口径全网关一致，单位写进字段名。
4. **异常在内部消化**：重试、换源、短时缓存兜底；都不行才返回"取不到 + 一句中文原因"，从不透出原始报错、栈或上游 URL。
5. **两条底线不让步**（沿用现有规则）：
   - **口径变化必须说出来**：换到口径不同的源（例如新浪主力资金 ≠ 东财主力资金），返回里写明，不悄悄混用。
   - **取不到就说取不到**：不用旧值、别的标的或估算顶替；用缓存兜底时必须带原始数据时间并标 `stale`。
6. **只读、无交易**：网关没有任何写外部状态或下单的能力。

## 3. 架构

```
 bot (dsh) ──stdio──> cn_market MCP 转发层（每个 bot 一个，薄，无状态）
                              │ HTTP 127.0.0.1:8868（仅回环）
                              ▼
        ┌──────────── cn-market-gateway 守护进程 ────────────┐
        │ 能力层  quote / bars / fund_flow / sectors / …      │
        │   └─ 计划器：每项能力一条源优先级链 + 合并规则       │
        │ 归一层  代码/时间/单位/口径 → 统一字段字典           │
        │ 校验与合并  交叉核对、冲突标注、计算字段（VWAP、分位） │
        │ 供应层  腾讯 | 新浪 | 东财 | 同花顺 | 乐咕 | 巨潮 |   │
        │         财联社 | 百度 | market-watch 引擎 | cn-watch  │
        │ 传输层  按主机的令牌桶 + 并发上限 + 最小间隔          │
        │         熔断（关/开/半开）| 同请求合并 | 分级缓存     │
        │         AKShare 调用进线程池 + 硬超时                 │
        │ 观测  /health、每源成功率/延迟/熔断、换源日志         │
        └────────────────────────────────────────────────────┘
```

- **语言与位置**：Python 3.12，新包 `packages/cn-market-gateway`（守护进程 + 转发层两个入口），沿用现有 AKShare 版本与 venv 约定；不引入新的第三方依赖（HTTP 用标准库，MCP 用现有 `mcp` 包）。
- **启动**：`scripts/chives.sh start` 先起网关（8868），再起服务端；网关不可达时转发层返回统一的 `unavailable`（原因"数据服务没有启动"），并在 Chives 状态接口里显示。
- **与两个盯盘引擎的关系**：market-watch/cn-watch 是有状态服务（30 分钟排名变化、涨停池历史、规则评估），继续独立运行。网关把它们当作**优先供应者**：引擎在线时市场级数据取自引擎（引擎有自己的缓存），引擎不在线时网关直连同一批公开源。网关读取 market-watch `/health` 得知"东财已熔断"，直接跳过东财，避免两边同时打同一个被限流的主机。

## 4. 对外工具（约 20 个，替代 47 个）

| 工具 | 能力 | 替代的现有工具 |
|---|---|---|
| `market_quote` | 1–20 只股票/ETF/指数的实时行情：价、涨跌幅、量、额、换手、量比、PE/PB、涨跌停价、盘口时间 | `cn_get_quote_snapshot`、`mkt_get_overview` 的指数部分 |
| `market_bars` | K 线：`1m/5m/15m/30m/60m/1d/1w/1M`，个股/指数，复权；日线**总是**带成交额与换手率 | `cn_get_market_data`、`cn_get_daily_bars`、`cn_get_minute_bars`、`cn_get_index_bars` |
| `market_intraday` | 单日盘中汇总（VWAP、高低点时间、前 30 分钟量占比等确定性指标） | `cn_intraday_summary` |
| `market_overview` | 大盘：主要指数、涨跌家数、涨停/跌停/炸板/连板、成交额、市场摘要 | `mkt_get_overview`、`mkt_get_summary`、`mkt_get_pool_stats` |
| `market_movers` | 全 A 涨幅/跌幅/成交额榜 | `mkt_get_movers` |
| `market_limit_pool` | 涨停/跌停/炸板/连板池明细 | `mkt_get_pool` |
| `market_sectors` | 行业或概念：排行；给 `code` 时返回单个板块详情与成分 | `mkt_get_sectors`、`mkt_get_sector`、`mkt_get_themes`、`cn_get_sector_info` |
| `market_fund_flow` | 资金流：个股 / 板块 / 排行 | `cn_get_fund_flow`、`mkt_get_flows` |
| `market_global` | 外盘指数、A50、商品、汇率、中美利率、海外个股 | `cn_get_global_snapshot`、`cn_get_overseas_quote` |
| `market_trading_activity` | 龙虎榜、大宗交易、融资融券 | `cn_get_dragon_tiger`、`cn_get_block_trades`、`cn_get_margin_trading` |
| `company_search` | 名称/拼音/代码 → 标准代码 | `cn_search_symbol` |
| `company_financials` | 三表与关键指标，按期 | `cn_get_financial_statements` |
| `company_valuation` | 个股估值历史与分位；`scope=industry/index/market` 时为行业/指数/全 A 估值 | `cn_get_valuation`、`cn_get_industry_valuation`、`cn_get_index_valuation` |
| `company_consensus` | 一致预期、评级分布、评级与目标价明细 | `cn_get_consensus`、`cn_get_ratings` |
| `company_reports` | 研报列表（标题、机构、评级、预测，不含正文） | `cn_get_research_reports` |
| `company_earnings` | 业绩预告、快报、报表、预约披露日 | `cn_get_earnings_events`、`cn_get_disclosure_schedule` |
| `company_holders` | 十大流通股东、基金持股、股东户数、限售解禁 | `cn_get_holders`、`cn_get_shareholder_count`、`cn_get_lockup_expiry` |
| `company_profile` | 主营构成、所属行业/概念、指数成分归属 | `cn_get_business_segments`、`cn_get_index_constituents` |
| `company_announcements` | 公告检索；给 `url` 时读原文 | `cn_get_announcements`、`cn_read_announcement` |
| `news` | `kind`：个股新闻 / 快讯电报 / 互动易问答 / 财经日历 / 停复牌 | `cn_get_stock_news`、`cn_get_flash_news`、`cn_get_irm_qa`、`cn_get_econ_calendar`、`cn_get_suspensions` |
| `convertible_bonds` | 可转债列表、条款、实时行情、转股溢价率 | `cn_get_cb_list`、`cn_get_cb_quote` |

`mkt_get_alerts` 不进网关：告警属于盯盘体系，T139 起由 Chives 直接路由给 bot。

工具描述只写"返回什么、参数怎么填"，不写数据源和单位换算提示（单位在字段名里）。

## 5. 统一返回与字段字典

### 5.1 外壳
```json
{
  "status": "ok | partial | unavailable",
  "as_of": "2026-11-17T10:44:00+08:00",
  "data": { ... },
  "basis": [{"field": "main_net_yuan", "note": "主力口径为超大单（新浪），与默认口径（东财大单+超大单）不同"}],
  "missing": [{"field": "amount_yuan", "reason": "该时段成交额暂不可得"}],
  "stale": false
}
```
- `status`：`ok` 全部取到；`partial` 部分字段/标的缺失（逐项写进 `missing`）；`unavailable` 全部取不到，`missing` 或 `message` 给一句中文原因（"行情服务暂时不可用，稍后再试""该代码不存在""非交易时段还没有当日数据"）。参数错误也走 `unavailable` + 中文提示怎么改，不抛协议错误。
- `basis`：**只在**本次结果的口径与该能力的默认口径不同时出现。这是 bot 唯一需要"感知"的东西。
- `stale`：用了缓存兜底时为 `true`，`as_of` 保持数据本身的时间。
- **不返回任何来源名**（用户决定，2026-11-17）。来源只记在网关日志与 `/health` 里，供排查与验收者核对；bot 答案里改为注明"数据时间"。
- 不出现：来源名、上游 URL、错误原文、栈、token、"fallback""熔断"等实现词。

### 5.2 字段字典（摘要）
| 类别 | 规则 |
|---|---|
| 代码 | `NNNNNN.SH/.SZ/.BJ`；指数 `000001.SH`、`399006.SZ`；输入接受裸 6 位、`sh600000`、中文名（经 `company_search`） |
| 时间 | ISO8601 带 `+08:00`；海外标的另给 `quote_tz`；日线日期 `YYYY-MM-DD` |
| 价格 | 元/股，字段 `price`、`open`、`high`、`low`、`close`、`prev_close` |
| 涨跌幅、比例 | 一律**百分数**，字段名 `_pct`（`0.85` 表示 0.85%） |
| 成交量 | 一律**股**，字段 `volume_shares`（上游为手时 ×100） |
| 金额 | 一律**元**，字段 `_yuan`（上游为万元、亿元时换算） |
| 估值 | `pe_ttm`、`pb_mrq`、`ps_ttm`，分位 `_pctile`（0–100） |
| 市值 | `total_mv_yuan`、`float_mv_yuan` |
| 第三方文本 | 新闻、公告、研报标题、问答：`untrusted_text: true` |

现有各工具字段到字典的映射表放在实现任务的附录里，逐字段写依据（沿用 `cn-data-tool-matrix.md`、T115–T119、T138 的核对结论）。

## 6. 源优先级链与口径（第一批能力）

| 能力 | 默认口径 | 链（左优先） | 换源时的口径说明 |
|---|---|---|---|
| `market_quote` | 交易所实时快照 | 腾讯 → 新浪 | 无差异 |
| `market_bars` 日线 | 不复权；成交额为实际成交额 | 新浪日线（含成交额、换手）→ 腾讯日 K（无成交额：`missing` 标注）→ 东财 | 腾讯无成交额 |
| `market_bars` 分钟 | 新浪分钟 | 新浪 → 腾讯分时（仅当日） | 腾讯只有当日 |
| `market_overview` 涨跌家数 | 沪深两市（东财） | market-watch 引擎 → 东财 → 乐咕 | 乐咕统计口径写进 `basis` |
| `market_sectors` | 东财 31 个一级行业 / 东财概念 | 引擎 → 东财 → 新浪行业/概念 | 新浪分类不同：`basis` + 不提供与东财代码的对应 |
| `market_fund_flow` | 东财主力（大单+超大单） | 东财 → 新浪 | 新浪 `r0` 口径与东财不同（T138 报告认为是超大单，**待 T141 核实**）：`basis` |
| `market_movers` | 沪深（不含北交所） | 引擎 → 东财 → 新浪（过滤北交所） | 无差异 |
| `market_global` | 各品种交易所时间 | 腾讯 → 新浪；美债 AKShare | 期货涨跌幅相对昨结算（字段说明） |

第二批（研究类）沿用 `cn_research` 现有主源，能补第二源的补上：一致预期东财为主、同花顺交叉核对（差异 > 5% 时两者都给并在 `basis` 说明）；估值东财为主、百度备用；其余暂无第二源的，失败即 `unavailable`。

## 7. 传输层：限流、熔断、缓存

- **按主机限流**（全网关共享，跨所有 bot、所有能力）：令牌桶 + 并发上限 + 最小间隔。初值：腾讯 120/分钟；新浪合计 30/分钟；东财 `push2*` 禁用（沿用红线），东财数据中心 30/分钟；同花顺 20/分钟；乐咕 6/分钟且间隔 ≥ 10 秒；巨潮 30/分钟；财联社 30/分钟。
- **熔断**：连续 3 次连接重置/超时/429/空响应 → 打开 300 秒 → 半开放行 1 次探测；熔断期间直接走链上下一个源，不排队等待。读取 market-watch `/health` 同步东财熔断状态。
- **请求合并**：同一时刻相同请求只发一次，其余等待同一结果（5 个 bot 同时问同一只股票时只打一次上游）。
- **分级缓存**：快照 3 秒、分钟线 30 秒、日线（盘中）60 秒 / 收盘后到次日开盘、全市场表 30 分钟、财报 6 小时、新闻 5 分钟、快讯 30 秒。
- **兜底**：所有源都失败时，若缓存里有该请求的结果且年龄不超过该能力的兜底上限（快照 60 秒、日线 1 天、财报 7 天），返回它并标 `stale:true`；否则 `unavailable`。
- **AKShare**：统一进线程池，硬超时 20 秒；超时计入该主机的熔断计数。
- **重试**：仅对幂等读、仅连接级错误重试 1 次（带抖动），业务级空结果不重试。

## 8. 合并与校验

- **合并**：同一请求需要多源字段时（例如 `market_quote` 的价量来自腾讯、PE/PB 来自东财估值），按字段归属合并，`as_of` 取主字段的时间，次要字段过旧（> 1 个交易日）则放进 `missing`。
- **交叉核对**：关键数字有第二源时抽查（成本可控才做）：日线成交额 ÷ 成交量应落在当日高低价之间；快照价与分钟线最后一根差 > 1% 时标注；一致预期两源差异 > 5% 时两者都给。
- **计算字段**：VWAP、估值分位、转股溢价率、相对沪深 300 强弱等由代码算，写明公式（沿用现有实现）。

## 12. 北向资金：免费源调研（2026-11-17 实测）

**结论：每日净买入已经没有任何来源（免费或付费）；能免费拿到的是"北向成交额"（每日）和"北向持股"（每季度），都来自港交所官方披露。**

背景：2024-05-13 起取消盘中实时披露；2024-08-19 起沪深交易所与港交所不再公布每日净买入/卖出，只公布成交总额、笔数、前十活跃股成交额，持股明细改为按季度公布。东财 `stock_hsgt_hist_em` 等接口因此自 2024-08 起为空。Tushare 的同类接口依赖同一披露，同样拿不到净买入。

| 数据 | 免费源 | 实测 | 字段与单位 |
|---|---|---|---|
| 每日北向成交（沪股通、深股通分开） | 港交所 `https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_<YYYYMMDD>e.js`（收市后发布的静态 JS，JSON 数组） | ✅ 2026-11-13、11-16 均可取；沪股通 11-16 成交 108,239.99、笔数 6,258,767，深股通 111,999.64 | `Total Turnover`、`ETF Turnover` 为**人民币百万元**；`Total Trade Count` 为笔；`DQB`（每日额度余额）现恒为 999,999,999，无意义 |
| 每日北向前十活跃股 | 同上文件 `top10Table` | ✅ 沪股通第 1 寒武纪、第 2 贵州茅台 | `Total Turnover` 为**人民币元**（买+卖合计，无买卖拆分）。核对：茅台 11-16 北向成交 16.04 亿，占其当日全市场成交 57.67 亿的 27.8%，合理 |
| 季度北向持股（逐只） | 港交所披露易 `https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=sh`（`t=sz` 为深股通） | ✅ 当前为 2026-09-30，沪股通 2,089 只 | 持股数（股）、占已发行 A 股比例（%）；季末后第 5 个北向交易日发布；查历史季度需按页面表单提交日期 |

可以由代码算出的衍生指标（写明口径，不叫"净流入"）：
- **北向成交占比** = 当日北向成交额 ÷ 当日沪深两市成交额，反映外资交易活跃度；
- **个股北向成交占比** = 前十活跃股的北向成交额 ÷ 该股当日成交额；
- **季度持股变化** = 本季末持股 − 上季末持股（股数与比例），这是现在唯一能看出外资增减持方向的免费数据。

不建议：用龙虎榜"沪股通/深股通专用席位"推算整体净流入（只覆盖上榜个股，以偏概全）；用第三方"估算北向净流入"（无公开方法，不可复核）。

网关落地：预留 `market_northbound`（`kind: daily | top_active | holdings`），日度来自港交所日报文件，季度持股来自披露易；放在 T141（市场级）里实现。字段名与单位按 §5.2（百万元换算为 `_yuan`）。工具描述与返回的 `basis` 写明"自 2024-08-19 起没有每日净买入数据"，避免 bot 自行"估算净流入"。
