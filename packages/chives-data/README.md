# Chives 数据站

正式程序名为 `chives-data`，生产服务监听本机 8868。由 `scripts/chives.sh start --engines` 启动，通过设置页「内核设置」查看状态。配置中的旧标识、MCP 工具名和已有数据目录用于兼容升级。

本机只读数据网关。bot 只调用 `market_*` 与 `company_*` 能力工具；选源、限流、熔断、重试、换源、缓存、
单位换算与字段合并在网关内部完成。T140 提供 `market_quote`、`market_bars`、`market_intraday`、
`market_global`，T141 增加 `market_overview`、`market_movers`、`market_limit_pool`、
`market_sectors`、`market_fund_flow`、`market_trading_activity`、`market_northbound`；
T142 增加 `company_search`、`company_financials`、`company_valuation`、`company_consensus`、
`company_reports`、`company_earnings`、`company_holders`、`company_profile`；T143 增加
`news`、`company_announcements`、`convertible_bonds`（共 22 个工具）。
网关实现在本包的 `src/cn_market_gateway/`。

- Python 3.12，包名 `cn_market_gateway`
- 守护进程只监听回环，默认 `127.0.0.1:8868`
- MCP 转发层无状态、不缓存、不直连上游
- 返回外壳不出现来源名、主机名、URL、原始错误、栈或实现词

## 安装

```bash
cd packages/chives-data
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
```

`.venv` 不提交。依赖版本与现有数据包一致：`mcp>=1.0,<2`、`akshare>=1.20,<2`，HTTP 使用标准库。

## 两个入口

```bash
# 守护进程（只监听回环）
.venv/bin/chives-data serve --host 127.0.0.1 --port 8868

# stdio MCP 转发层（MCP 名 cn_market）
.venv/bin/cn-market-mcp
```

HTTP 接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/call` | body `{"tool": "...", "args": {...}}`，返回统一外壳 |
| GET | `/v1/tools` | 工具清单与 JSON Schema |
| GET | `/health` | 每台上游的限流计数、熔断状态、缓存命中、最近 50 次换源/失败记录 |

来源名只出现在 `/health` 和日志里。MCP 转发层启动时从 `/v1/tools` 取清单，取不到时使用包内置静态清单；
每次调用转发到 `/v1/call`；守护进程不可达时返回
`{"status":"unavailable","message":"数据服务没有启动"}`，不抛 MCP 协议错误。

## 返回外壳

```json
{
  "status": "ok | partial | unavailable",
  "as_of": "2026-11-17T10:44:00+08:00",
  "data": {},
  "basis": [{"field": "amount_yuan", "note": "..."}],
  "missing": [{"item": "600519.SH", "field": "pe_ttm", "reason": "..."}],
  "stale": false,
  "message": "仅 unavailable 时出现"
}
```

- `ok`：请求的字段/标的全部取到；`partial`：部分缺失并逐项写入 `missing`；
  `unavailable`：全部取不到或参数错误，`message` 给一句中文修改建议。
- `basis` 只在本次结果口径与该能力默认口径不同时出现。
- `stale:true` 表示使用了缓存兜底，`as_of` 保持数据本身时间。
- 参数错误也返回 `unavailable`，不抛协议错误。

## 工具与字段

### `market_quote`

`codes`：1–20 个股票/ETF/指数，接受裸 6 位、`sh600000`、`600000.SH`、`000300.SH`。
每只返回 `price`、`prev_close`、`change_pct`、`open`、`high`、`low`、`volume_shares`、
`amount_yuan`、`turnover_pct`、`volume_ratio`、`pe_ttm`、`pb_mrq`、`limit_up`、`limit_down`、
`quote_time`。源链：腾讯快照 → 新浪 A 股行情行；新浪没有的字段逐项进 `missing`。

### `market_bars`

`code`、`interval`（`1m/5m/15m/30m/60m/1d/1w/1M`，默认 `1d`）、`start`、`end`、
`adjust`（`none/qfq/hfq`，默认 `none`）、`limit`（默认 250，≤1000）。
每行返回 `time`、`open/high/low/close`、`volume_shares`、`amount_yuan`，日线另有 `turnover_pct`。

源链：

- 个股日线：新浪日线（含成交额与换手）→ 腾讯日 K（无成交额与换手，`missing` 说明）
- 指数日线：新浪指数日线 → 腾讯日 K。**东财 `push2*` 主机按仓库红线禁用**，
  因此没有沿用旧 `cn_get_index_bars` 的东财主机；指数日线的成交额与换手可能缺失。
- 周/月线：由日线在代码内聚合，时间取该周期最后一个交易日，成交量/额/换手求和
- 分钟：新浪分钟 → 腾讯当日分时（只覆盖最近一个交易日，跨日请求用 `missing` 说明）
  5/15/30/60 分钟由 1 分钟线在代码内聚合。

### `market_intraday`

`code`、`date`（YYYY-MM-DD）。字段与旧 `cn_intraday_summary` 定义一致，按字段字典改单位后缀：

`open`、`close`、`high`、`low`、`high_time`、`low_time`、
`vwap = sum(amount_yuan) / sum(volume_shares)`（4 位小数）、
`close_vs_vwap_pct = (vwap - close) / vwap * 100`（2 位小数，正数表示收盘低于 VWAP）、
`first_30min_volume_share_pct`（09:31–10:00 成交量占比，1 位小数）、
`volume_share_from_high_bar_pct`（最高价那根起到收盘的成交量占比，1 位小数）、
`complete`（最后一根 ≥15:00）、`bars`。

### `market_global`

`groups`（`us_index/hk_index/a50/fx/commodity/rates/leaders`）或 `symbols`（1–10 个海外代码，
如 `usNVDA`、`hk00700`），二选一。沿用旧 `cn_get_global_snapshot` / `cn_get_overseas_quote`
的字段与口径：`price`、`prev_close`、`change_pct`、`quote_time`、`quote_tz`；
期货 `prev_close` 为昨结算价，涨跌幅相对昨结算（`basis` 说明）；
利率项 `price` 为百分数，另给 `change_bp`（基点）。

## 单位与口径

| 后缀/字段 | 规则 |
|---|---|
| `_shares` | 股。上游为手时 ×100 |
| `_yuan` | 元。上游为万元时 ×10000 |
| `_pct` | 百分数，`0.85` 表示 0.85% |
| `_bp` | 基点 |
| `price/open/high/low/close/prev_close` | 元/股；利率项为百分数，另带 `unit` |
| 时间 | ISO8601 带 `+08:00`；日线日期 `YYYY-MM-DD`；海外另给 `quote_tz` |
| 代码 | `NNNNNN.SH/.SZ/.BJ` |

换算依据沿用 `packages/cn-extra-mcp/README.md` 的字段核对结论：腾讯快照成交量单位为手、
成交额为万元；新浪 A 股行情行成交量单位为股、成交额为元；新浪日线
`volume` 为股、`amount` 为元、`turnover` 为比例（×100 得百分数）；
旧东财指数日线 `volume` 为手（×100）、`amount` 为元（见 `cn_research_mcp/service.py` 的
`INDEX_VOLUME_LOT_SIZE`）。指数日线现在走新浪，若上游只给成交量则按股处理，成交额进 `missing`。

## 传输层

- 按主机的令牌桶 + 并发上限 + 最小间隔，全进程共享；初值见 `src/cn_market_gateway/config.py`
- 主机白名单只含本任务用到的主机；任何含 `push2` 的主机直接拒绝
- 熔断：同一主机连续 3 次连接重置/超时/429/空响应 → 打开 300 秒 → 半开放行 1 次
- 同请求合并：相同 `(tool, 规范化 args)` 同时只打一次上游
- 分级缓存与兜底：快照 3 秒/60 秒、分钟 30 秒/300 秒、日线盘中 60 秒/1 天、
  外盘 30 秒/60 秒；兜底返回 `stale:true`
- AKShare 调用进线程池，20 秒硬超时；连接级错误重试 1 次（带抖动），业务空结果不重试

## 测试

全部离线，上游通过假 `Sources` / 假 fetch 注入：

```bash
.venv/bin/python -m pytest -q
```

覆盖：四个工具的正常、部分缺失、全部失败、参数错误、北交所/指数代码、周月线聚合、
熔断打开/半开/恢复、并发合并、缓存与兜底 `stale`、`push2` 拒绝、守护进程 HTTP、转发层在/不在，
并用旧包测试 fixtures 与旧工具（quote/minutes/daily/intraday/global）做单位换算后的字段对比。

## 手动冒烟

```bash
.venv/bin/python tools/smoke.py
```

默认请求 `600519`、`000300.SH`、`000528` 与外盘 `a50,fx`，打印外壳与 `/health` 摘要。
脚本不在测试里运行；请遵守限频，不访问东财 `push2`。

## 已知边界

- 指数日线没有东财源（`push2` 禁用），成交额/换手可能为 `null` 并进 `missing`。
- 腾讯分时只有最近一个交易日；跨日分钟请求会 `partial`。
- `market_global` 的 `rates` 依赖 AKShare 的美债/中债收益率表；取不到时该组逐项进 `missing`。
- 海外个股的标的身份未逐一核对（仅按代码取快照），与旧工具行为一致。
- 北向名称替换依赖的全市场简称表以股东户数表为底；个别 A 股（实测 601899.SH）不在该表时
  按任务规则保留英文名，不猜测译名。

## 市场级能力（T141）

**T157 起网关不再有“引擎路径”**：七个市场工具只走直连链（非 push2 的公开源），
不再访问本机盯盘引擎、不再维护引擎客户端/熔断器，`/health` 也不再返回 `engine` 与
`eastmoney_open`。`/health.recent` 记录每次请求实际使用的公开源。直连覆盖不到的字段/能力
逐项写入 `missing`/`unavailable`，不会用旧值或 0 顶替。

### `market_overview`

无参数。返回 `indexes`、`breadth`（涨/跌/平家数、上涨占比）、`limit`
（涨停/跌停/炸板、最大连板、封板率）、`amount_yuan` 与 `headlines`。

- 指数复用 `market_quote`；涨跌家数与涨停/跌停家数取乐咕市场活跃度页。
- 乐咕口径为**沪深两市、不含北交所、含 ST**，写入 `basis`；炸板/最大连板/封板率直连源
  不提供，逐项进 `missing`。全市场成交额 = 上证指数成交额 + 深证成指成交额（写入 `basis`）。
- `headlines` 没有直连源，恒进 `missing`（空列表）。

### `market_movers`

`kind`（gainers/losers/active）、`limit`（1–200，默认 10）、`include_bj`（默认 false）。
按 `hs_a` 排序取页、过滤北交所、按代码去重；源失败时 `unavailable`。

### `market_limit_pool`

`kind`（zt/zb/dt/ladder/stats）、`date`、`limit`（1–500，默认 50）、`days`（stats 用，10–30）。

- 涨停/炸板/连板梯队用同花顺数据中心公开接口；**跌停池没有找到不含禁用主机的直连源，
  恒返回 `unavailable` 并说明**。
- 字段差异：不提供成交额与行业（`missing`），涨停行多给 `theme`（题材）与 `board_type`；
  `stats` 用当日与上一交易日的涨停/炸板数与连板代码计算封板率、1→2、2→3、3 板以上晋级率，
  只给当日，`days` 进 `missing`。
- 同花顺单次最多 200 行；请求更多时 `missing` 说明剩余行未取。

### `market_sectors`

`kind`（industry/concept）、`sort`（change/amount）、`limit`（1–100，默认 20）；给 `code`
时返回详情。

- 行业排行走同花顺行业汇总（`q.10jqka.com.cn`，`stock_board_industry_summary_ths`），提供
  涨跌幅、成交额、上涨/下跌家数、净流入与领涨股。该口径**只有名称、没有板块代码**，因此
  `code`、`limit_up_count`、`rel_300_pct`、`rank_change_30m`、`member_count` 逐项进
  `missing`，并在 `basis` 说明分类不可与旧口径对齐。
- 概念排行走新浪板块页（`kind=concept`），代码形如 `new_*`/`gn_*`，`basis` 说明分类口径。
- 行业领涨股：传 `kind=industry`、`code=industry:行业名称`，返回最多五只领涨股及成交额。旧调用使用的 `ths:行业名称` 继续接受。
- 概念或旧板块节点详情：只有新浪节点代码（`new_*`/`gn_*`）可用，走
  `Market_Center.getHQNodeData?node=<code>`；`BKxxxx` 没有直连成分源，`unavailable`。

### `market_fund_flow`

`scope`（stock/sector/rank）、`kind`（in/out）、`code`（stock 必填）、`limit`（1–100）、
`days`（stock 历史，默认 20）。

- 排行/板块：新浪行业资金流与个股资金流榜；个股：新浪个股资金流历史接口，返回最近 `days`
  个交易日。
- **口径核实结论**：新浪同一字段在不同页面标注不一致——排行榜页把 `r0_net` 标注为
  **超大单**，个股详情页把 `r0_in/r0_out/r0_net` 标注为**主力**；两处都是新浪自己的页面。
  数值上 `r0_net` 与东财主力净流入（大单+超大单）不一致：贵州茅台 2026-11-16 新浪
  `r0_net=677,679,142.74` 元，同日东财主力净流入 `516,422,832` 元、东财超大单
  `-179,663,632` 元、大单 `696,086,464` 元。因此不能把新浪 `r0` 当作东财主力口径；
  `basis` 写明"排行页/详情页标注矛盾、与东财主力不一致、不能直接比较"。

### `market_trading_activity`

`kind`（dragon_tiger/block_trades/margin）、`code`、`date`、`days`、`limit`。

- 只走东财**数据中心** `datacenter-web.eastmoney.com`，不使用行情主机。
- 龙虎榜：`RPT_DAILYBILLBOARD_DETAILS`；给 `code` 时再取 `RPT_BILLBOARD_DAILYDETAILSBUY/SELL`
  并按上榜原因分组、每侧从 1 编号。金额元、涨跌幅百分数。
- 大宗：`RPT_DATA_BLOCKTRADE`；`premium_pct` 为相对收盘价的**百分数**（原字段
  `PREMIUM_RATIO` 是小数，代码 ×100）；成交量单位股、成交额元。
- 两融：`RPTA_WEB_RZRQ_GGMX`；余额/买入/偿还/融券余额元，融券余量股，T+1。
- 字段与单位沿用 `docs/cn-data-tool-matrix.md` 的核对结论。

### `market_northbound`

`kind`（daily/top_active/holdings）、`date`、`code`（holdings 可选）。

- `daily`/`top_active`：港交所每日统计静态文件。`Total Turnover`、`ETF Turnover` 为
  人民币**百万元**（×1e6 得元）；`Total Trade Count` 为笔；top10 的 `Total Turnover`
  为人民币**元**。已用 2026-11-13、2026-11-16 两天样本复核。
- `holdings`：披露易季度持股页（沪股通/深股通）。持股数股、占比百分数。当前季度用 GET；
  历史季度用同一页面的表单 POST（带 viewstate），逐季回溯。变化 = 本季末 − 上季末，
  给出 `change_shares` 与 `change_pct_points`；上季取不到时进 `missing`。
- 所有返回都带 `basis`："自 2024-08-19 起没有每日净买入数据；成交额为买卖合计"；
  **不输出也不估算净流入**。

## 传输层新增主机与限频

| 主机用途 | 限频初值 |
|---|---|
| 乐咕市场活跃度 | 6/分钟、间隔 ≥10 秒 |
| 新浪节点与资金流（`vip`/`money` 共用 `sina` 桶） | 30/分钟、间隔 ≥0.5 秒 |
| 东财数据中心 `datacenter-web` | 30/分钟 |
| 同花顺数据中心 `data.10jqka` | 20/分钟 |
| 港交所日报 | 10/分钟 |
| 披露易 | 6/分钟 |

任何名称含禁用主机标记的主机仍在白名单校验前直接拒绝。T157 起 `/health` 只有
`status/uptime_s/upstreams/recent/cache/tools`，不再有 `engine` 与 `eastmoney_open`。

## 禁用词表的调整

`FORBIDDEN_OUTPUT` 把原来的 `circuit` 改为 `circuit_open` / `circuit breaker`。原因：港交所
前十活跃股里有公司名含英文单词 `CIRCUIT`（例如 `WUS PRINTED CIRCUIT KUNSHAN`），原规则会把
第三方专有名词误判为实现词泄漏；实际的实现词是 `circuit_open` 或 `circuit breaker`，仍被拦截。
其余来源名、主机名、URL、`source` 字段与中文实现词不变。

## T141 测试与样本

离线测试覆盖：每个工具的直连成功/失败路径、参数错误、北向三种 kind、季度持股变化、
跌停池 `unavailable`、禁用词与 `source` 字段。T157 删除了引擎路径测试，测试数由 300 降到 292。
样本在 `tests/fixtures/market/`：

| 样本 | 内容 |
|---|---|
| `hkex_daily_20261113e.js`、`hkex_daily_20261116e.js` | 港交所日报两天 |
| `hkex_holdings_sh.html.gz`、`hkex_holdings_sz.html.gz` | 披露易沪深各一页（gzip 原文） |
| `sina_movers_*.json`、`sina_industry.js`、`sina_concept.js`、`sina_node_new_kfq.json` | 新浪榜单/分类/节点 |
| `sina_flow_sector.json`、`sina_flow_stock.json`、`sina_flow_stock_history.json` | 新浪资金流（历史样本裁到 40 行） |
| `sina_moneyflow_labels.txt` | 新浪资金流页面字段标注（r0 的两处不同口径） |
| `ths_pool_zt.json`、`ths_pool_zb.json`、`ths_pool_ladder.json` | 同花顺涨停/炸板/连板 |
| `legu_activity.html` | 乐咕市场活跃度 |
| `dc_*.json` | 东财数据中心龙虎榜、席位、大宗、两融 |

样本只用于离线解析测试；`pytest` 的默认 marker 不访问网络。

## 公司与研究能力（T142）

八个工具都复用 T140/T141 的守护进程、传输层、缓存、同请求合并、外壳与测试夹具。工具描述与
`basis`/`missing`/`message` 不写来源名；来源只出现在 `/health` 与日志里。

### `company_search`

`query`（名称、简称、拼音首字母、6 位代码），`limit` 默认 10、最多 20。返回 `candidates[]`：
`code`、`name`、`market`（沪/深/北）、`type`（股票/ETF/指数）、`pinyin`。`count` 为本次返回数，
`total_matching` 为匹配总数。检索走东财建议接口（非 push2 主机），查不到时再退回 A 股简称表，
退回时 `basis` 说明本次只匹配 A 股简称与代码（指数代码用内置名称清单，不覆盖 ETF）。

### `company_financials`

`code`、`statement`（`indicators` 默认 / `income` / `balance` / `cashflow`）、`periods` 默认 8、最多 40。

- `indicators`：`report_date`、`report_name`、`announce_date`、`revenue_yuan`、`revenue_yoy_pct`、
  `net_profit_yuan`、`net_profit_yoy_pct`、`net_profit_deducted_yuan`、`net_profit_deducted_yoy_pct`、
  `eps_yuan`、`bps_yuan`、`roe_pct`、`gross_margin_pct`、`net_margin_pct`、`debt_ratio_pct`、
  `operating_cash_flow_per_share_yuan`、`operating_cash_flow_yuan`、`total_liabilities_yuan`。
- `income`/`balance`/`cashflow`：按报告期返回常用报表行（营收、成本、费用、利润、资产、负债、
  权益、经营/投资/筹资现金流、资本开支等），字段名带 `_yuan` 或 `_pct`。
- 指标来自东财 F10 主要指标表；经营现金流总额按报告日与新浪三表接口的"经营活动产生的现金流量净额"
  对齐；取不到时该字段进 `missing`，状态 `partial`。金额元、比例百分数。

### `company_valuation`

`scope`：

- `stock`：给 `code`，返回 `current`（`date`、`close`、`pe_ttm`、`pe_static`、`pb_mrq`、`ps_ttm`、
  `market_cap_yuan`、`float_cap_yuan`、股本）与 `percentile`（`pe_ttm_pctile`、`pb_mrq_pctile`、
  `ps_ttm_pctile`，窗口默认 3 年、可选 1–10 年；同时保留 `_pct` 别名），以及周度 `series`
  （最多 160 点）。
  分位定义为窗口内不大于当前值的正样本占比（0–100），非正值不计入；有效样本少于 60 个时给
  `null` 与原因。主源失败时用另一套口径补市盈率与市净率，`basis` 说明、市销率与静态市盈率进
  `missing`。
- `industry`：`date` 可选（默认回看最近 5 天），`limit` 默认 40、最多 200。返回行业代码/名称、
  层级、公司数、总市值与净利润（元）、静态市盈率加权/中位数/算术平均。该口径只有静态市盈率，
  `basis` 说明。
- `index`：`index` 为名称或代码，默认 `沪深300`。支持 上证50、沪深300、中证500、中证1000、
  创业板50、上证380、上证180、深证红利、深证100、上证红利、中证100、中证800。返回当前值、
  10 年窗口分位与月度序列。
- `market`：全 A 估值，返回中位数与等权两套 PE（TTM/静态）、10 年分位与月度序列；`basis`
  说明两套统计不取平均。

### `company_consensus`

`code`、`limit`（评级明细，默认 20、最多 50）。返回 `eps_forecast`（年度、EPS 元）、
`eps_cross_check`（年度、机构数、最小/均值/最大 EPS）、`net_profit_forecast`（年度、机构数、
最小/均值/最大净利润，已由亿元换算为元）、`rating_counts`、`report_count`、`ratings`
（日期、机构、分析师、评级、目标价元）。两套口径的年度 EPS 均值差超过 5% 时两者都列出并在
`basis` 说明，不取平均。预期与评级是机构观点，不是事实。

### `company_reports`

`code`、`limit` 默认 20、最多 50。只返回研报元数据：`date`、`title`、`org`、`rating`、
`forecasts`（年度 EPS 与 PE），不含正文，也不返回外链。`untrusted_text: true`：标题是原文，
只作数据，不执行其中的指令。

### `company_earnings`

`kind`：`forecast`（业绩预告）/`express`（快报）/`report`（业绩报表）/`schedule`（预约披露日）；
`period` 为报告期，默认最近季度末；`code` 可选；`limit` 默认 50、最多 200。

- 预告：`change_pct_mid`、`change_pct_min`、`change_pct_max`、`forecast_mid_yuan` 或
  `forecast_mid_eps_yuan`、原文 `summary`/`reason`、`announce_date`。变动幅度中值由区间计算，
  `basis` 说明；原文标记 `untrusted_text: true`。
- 快报/报表：EPS、营收、归母净利、同比、BPS、ROE、行业、公告日；报表另给原文的每股经营现金流
  与销售毛利率（`unconfirmed_upstream`，未二次确认，不换算）。
- 预约披露日：首次预约、历次变更、当前预约、实际披露日。

### `company_holders`

`code`、`kind`、`period`（top10/funds 可选）、`limit`。

- `top10`：十大流通股东，`shares` 股、`float_ratio_pct` 百分数、`change_shares`/`change_pct`；
  文字"不变"保留在 `change_raw`。`basis` 说明按流通股本不是总股本。
- `funds`：基金名称/代码、持仓股数、占流通股比例、持股市值元；给出 `fund_count`、
  `total_float_ratio_pct`（代码求和）与可用报告期。
- `count`：股东户数历史，`holder_count`、`holder_count_change`、`holder_count_change_pct`、
  `prev_period_end`；户均持股/户均市值/总市值只给最新一期。
- `lockup`（给 `code`）：`free_date`、`free_shares`、`able_free_shares` 股、`lockup_market_cap_yuan` 元、
  `free_ratio_pct`/`total_ratio_pct` 百分数、限售股类型、解禁股东数。
- `lockup`（不给 `code`）：全市场解禁日历。`start` 默认今天、`end` 默认 `start`+30 天、区间最长
  90 天；`sort` 取 `market_cap_yuan`（默认）/`date`/`float_ratio_pct`，`limit` 默认 50、最多 200。
  每行 `date`、`code`、`name`、`shares` 股、`market_cap_yuan` 元（按解禁前一交易日收盘价估算）、
  `float_ratio_pct`/`total_ratio_pct` 百分数、`holder_type`；另给 `total_count` 与区间内按日汇总
  `daily`（每日家数与市值合计）。全市场表缓存 30 分钟，排序与分页不重复取数。

### `company_profile`

`code` 与 `index` 至少给一个；`by` 取 product/region/industry；`period` 可选；`limit` 为成分股
上限，默认 500、最多 1000。

- 主营构成：按产品/地区/行业，收入、成本、毛利、收入占比、毛利率；上游只给收入与成本时由代码
  计算毛利/毛利率并标 `computed`。
- 所属行业：三级行业路径与最后一级（例如 交运设备-汽车-汽车零部件 → 汽车零部件）。
- 概念：板块代码、名称、是否精确、原文说明；`untrusted_text: true`。
- `index`：指数成分名单，`as_of`、`count`、`returned`、`dropped`、每行代码/名称/市场；同时给
  `code` 时附 `in_index`。深证成指、创业板指没有公开成分名单，返回 `unavailable` 并说明。

## AKShare 主机核对（T142）

每个用到的 AKShare 函数都读过新包 venv 中的 `akshare@1.20.65` 源码，确认实际请求主机；请求
主机含 `push2`（含 `push2his`、`push2ex`）的函数一律不用。下表的行号是函数内发起请求的 URL 行。

| AKShare 函数 | 请求主机 | 证据 |
|---|---|---|
| `stock_zh_a_gdhs` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/holder/stock_gdhs.py:24` |
| `stock_financial_analysis_indicator_em` | datacenter.eastmoney.com | `akshare@1.20.65/stock/issue/stock_finance_sina.py:202` |
| `stock_financial_report_sina` | quotes.sina.cn | `akshare@1.20.65/stock/issue/stock_finance_sina.py:45` |
| `stock_value_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/valuation/stock_value_em.py:23` |
| `stock_zh_valuation_baidu` | gushitong.baidu.com | `akshare@1.20.65/stock/valuation/stock_zh_valuation_baidu.py:32` |
| `stock_industry_pe_ratio_cninfo` | webapi.cninfo.com.cn | `akshare@1.20.65/stock/research/stock_industry_pe_cninfo.py:44` |
| `stock_index_pe_lg` | legulegu.com | `akshare@1.20.65/stock/valuation/stock_a_pe_and_pb.py:422` |
| `stock_a_ttm_lyr` | legulegu.com | `akshare@1.20.65/stock/valuation/stock_ttm_lyr.py:22` |
| `stock_profit_forecast_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/research/stock_profit_forecast_em.py:25` |
| `stock_profit_forecast_ths` | basic.10jqka.com.cn | `akshare@1.20.65/stock/research/stock_profit_forecast_ths.py:30` |
| `stock_institute_recommend_detail` | stock.finance.sina.com.cn | `akshare@1.20.65/stock/research/stock_recommend.py:107` |
| `stock_research_report_em` | reportapi.eastmoney.com | `akshare@1.20.65/stock/research/stock_research_report_em.py:25` |
| `stock_yjyg_em` | datacenter.eastmoney.com | `akshare@1.20.65/stock/finance/stock_yjyg_em.py:145` |
| `stock_yjkb_em` | datacenter.eastmoney.com | `akshare@1.20.65/stock/finance/stock_yjyg_em.py:27` |
| `stock_yjbb_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/finance/stock_yjbb_em.py:28` |
| `stock_yysj_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/finance/stock_yjyg_em.py:235` |
| `stock_gdfx_free_top_10_em` | emweb.securities.eastmoney.com | `akshare@1.20.65/stock/holder/stock_gdfx_em.py:388` |
| `stock_restricted_release_detail_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/issue/stock_restricted_em.py:117` |
| `stock_restricted_release_queue_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/issue/stock_restricted_em.py:213` |
| `stock_board_industry_summary_ths` | q.10jqka.com.cn | `akshare@1.20.65/stock/board/stock_board_industry_ths.py:360` |
| `stock_fund_stock_holder` | vip.stock.finance.sina.com.cn | `akshare@1.20.65/stock/issue/stock_finance_sina.py:689` |
| `stock_zh_a_gdhs_detail_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/holder/stock_gdhs.py:139` |
| `stock_zygc_em` | emweb.securities.eastmoney.com | `akshare@1.20.65/stock/finance/stock_zygc.py:23` |
| `index_stock_cons_csindex` | oss-ch.csindex.com.cn | `akshare@1.20.65/index/index_cons.py:136` |

直接 HTTP、不经过 AKShare 的取数只有两类：

| 用途 | 主机/路径 | 证据 |
|---|---|---|
| 名称/拼音/代码检索 | `searchapi.eastmoney.com/api/suggest/get` | `src/cn_market_gateway/company_sources.py:169-183` 的 `CompanySources.search` |
| 公司概况与概念板块 | `datacenter.eastmoney.com/securities/api/data/v1/get`，报表 `RPT_F10_BASIC_ORGINFO`、`RPT_F10_CORETHEME_BOARDTYPE` | `src/cn_market_gateway/company_sources.py:285-289` 的 `CompanySources.org_info` / `concepts` |
| 全市场限售解禁 | `datacenter-web.eastmoney.com/api/data/v1/get`，报表 `RPT_LIFT_STAGE` | `src/cn_market_gateway/company_sources.py:242-283` 的 `CompanySources.lockup_market` |

所有主机都已加入 `config.HOST_POLICIES`，沿用按主机令牌桶、并发上限、最小间隔、300 秒熔断与
20 秒 AKShare 硬超时。任何名称含禁用主机标记的主机仍在白名单校验前直接拒绝。

## 北向英文名换中文

`market_northbound` 的 `top_active` 与 `holdings` 在返回前用同一份 A 股代码→中文名缓存替换
`name`：缓存来自 `stock_zh_a_gdhs(symbol="最新")` 的全市场代码/简称表，TTL 6 小时；取不到或
查不到该代码时保留原英文名，不改变 `status`。名称替换在缓存外壳之后执行，所以第一次调用即使
名称表还在后台加载，也不会把旧的英文名写进 24 小时缓存。

## T142 测试与样本

离线测试新增 `tests/test_company_*.py` 与 `tests/test_northbound_names.py`，覆盖：检索的中文/
拼音/重名/北交所/本地回退；财务指标与三表、经营现金流缺失；估值分位与第二口径、行业/指数/全 A；
一致预期 5% 分歧与交叉核对缺失；研报原文标记；四类业绩事件；四类股东/解禁；主营构成/行业/概念/
指数成分；外壳禁用词与参数错误。`tests/test_company_old_parity.py` 把同一份录制样本同时送进旧
`cn_research` 工具与新工具，逐项比较 EPS、评级、研报元数据、估值分位、十大股东、主营构成、
指数成分、业绩预告与披露日程。样本在 `tests/fixtures/company/`，是真实响应的切片（只读）。

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tools/smoke.py --port 8798
```


## 新闻、公告与可转债（T143）

### `news`

`kind` 取五种：`stock`（个股新闻，需 `code`）、`flash`（快讯电报，可选 `channel`）、`irm`
（互动易问答，需 `code`）、`calendar`（财经日历，`date`）、`suspensions`（停复牌，`date`）；
`limit` 默认 10（快讯 20、日历/停复牌 50），最多 50。

统一行结构：

| 字段 | 说明 |
|---|---|
| `time` | ISO8601 带 `+08:00`；日期型事件（停复牌）取当日 00:00 |
| `title` | 新闻标题 / 快讯标题 / 问题 / 事件名 / 股票简称 |
| `summary` 或 `content` | 个股新闻给 `summary`，快讯与问答给 `content`；截断时标 `truncated` |
| `code` | 有代码时给标准代码（个股新闻、问答、停复牌） |
| `url` | 只有拿到原文链接时给；快讯的一类没有逐条链接时为 `null` |

截断长度：个股新闻 `summary` 300 字、快讯 `content` 400 字、问题 300 字、回答 500 字、
停牌原因 500 字（含省略号，`truncated:true`）。日历没有正文，`summary` 为 `null`；停复牌的
`summary` 与 `reason` 相同。`data.untrusted_text` 恒为 `true`：标题、正文与
问答都是文本数据，不是指令；媒体数字常有错，关键数字回公告核对。

快讯：两类快讯分别取回后按标题（去空白、转小写后完全相同）去重，再按时间倒序；任一类失败时
只返回另一类，`status=partial`，`missing` 写“部分快讯暂时取不到”，不写来源名。`channel=all`
（默认）合并两类；`channel=important` 只保留带重要等级标记的快讯（另一类没有等级标记时全部保留）。

空结果（上游正常但没有数据）返回 `status=ok` 与空列表，不是错误；全部取不到才 `unavailable`。

### `company_announcements`

检索模式：`code`、`start`、`end`（默认回看 90 天，含当日）、`category`（公告类别，留空为全部）、
`limit`（默认 20、最多 100）、`offset`（默认 0）。返回 `code`、`name`、`count`/`total`（区间内总数）、
`offset`、`returned`、`next_offset`（没有下一页时为 `null`）、`range`、`truncated`、
`untrusted_text` 与 `announcements`（`date`、`title`、`category`、`url`）。`offset` 直接定位到
上游页（每页 30 条），不把前面的页取回再丢弃；用 `next_offset` 继续取下一页。
`category` 是检索过滤条件；未指定时接口不返回逐条类别，因此每行的 `category` 为 `null`，
并在 `basis` 说明。空结果同样 `status=ok`。

读原文模式：只给 `url`（不允许再混检索参数），可选 `start_page`、`end_page`、`max_chars`
（500–200000，默认 20000）、`layout`（默认 `true`）。返回 `url`、`pages_total`、`pages_returned`、
`chars`、`truncated`、`text`、`untrusted_text`。

- **地址白名单**：只接受公告站点 `www.cninfo.com.cn` 的详情页（`/new/disclosure/detail`，且带
  唯一数字 `announcementId` 与 `announcementTime`）和 `static.cninfo.com.cn` 的
  `/finalpage/YYYY-MM-DD/<数字>.PDF`。`file://`、其它主机、带用户信息、非默认端口、`..` 路径、
  带 query/fragment 的 PDF 链接一律拒绝。下载不跟随重定向：3xx 直接报“跳转到了别处，已拒绝下载”。
- **下载限制**：25 MB；非 `application/pdf` 或响应体不以 `%PDF-` 开头即 `unavailable`；下载走
  传输层（按主机限频、熔断、计入 `/health`）。
- **解析限制**：`pdftotext` 用参数数组调用、不经 shell，超时 30 秒；缺失时 `unavailable` 并给
  中文原因。只处理带文本层的 PDF，扫描件返回“不支持 OCR”。页数用 `pdfinfo`，缺失时退化为
  `pdftotext -bbox` 的 `<page>` 计数；页码越界、`end_page < start_page` 都是参数错误。
- **URL 编码**：检索返回的详情页链接把 `announcementTime` 编码为
  `YYYY-MM-DD+HH%3A%MM%3ASS`，可以直接作为 `url` 传回本工具。

### `convertible_bonds`

`kind=list`：条款表，`underlying`（正股代码，可选）、`limit` 默认 50、最多 500；缓存 30 分钟。
每行含 `bond_code`、`bond_name`、`underlying_code`、`underlying_name`、`bond_price_yuan`、
`change_pct`、`amount_yuan`、`underlying_price_yuan`、`conversion_price_yuan`、
`conversion_value_yuan`、`premium_pct`、`maturity_date`、`credit_rating`、`issue_size_yuan`、
`listing_date`、`listing_status`、`remaining_size_yuan`（有则附 `remaining_size_date`）。
上市时间缺失或在未来的按未上市剔除；简称含“退”或代码以 404 开头的按退市剔除，剔除数量写在
`dropped_*` 字段。

`kind=quote`：`codes` 1–20 只 6 位转债代码；行情缓存 30 秒。每行含 `bond_code`、`name`、
`bond_price_yuan`、`change_pct`、`amount_yuan`、`underlying_code`、`underlying_price_yuan`、
`conversion_price_yuan`、`conversion_value_yuan`、`premium_pct`、`maturity_date`、
`credit_rating`、`quote_time`。行情缺失时仍返回该行，价格字段为 `null` 并进 `missing`。

**公式（由代码计算，不采用上游的转股价值/溢价率字段）**：

```
conversion_value_yuan = 100 / conversion_price_yuan * underlying_price_yuan
premium_pct = (bond_price_yuan / conversion_value_yuan - 1) * 100
```

正股价或转股价取不到时，`conversion_value_yuan` 与 `premium_pct` 为 `null` 并进 `missing`；
转债价取不到时 `premium_pct` 为 `null`。`issue_size_yuan` 是发行规模（亿元 × 1e8）；
`remaining_size_yuan` 优先取可查的最新未转股余额（元，附 `remaining_size_date`）；尚未进入
转股期的转债，因不可能发生转股，取发行规模并标 `remaining_size_computed:true`。其余取不到的
保持 `null` 并进 `missing`，不用估算值顶替。

### 链接例外（只对 `url` 字段）

公告与新闻原文链接是 bot 继续读原文所必需的，因此 `data.url`（公告原文、新闻原文）允许出现
URL。运行时禁用词检查只扫 `basis`/`missing`/`message` 与字段名，本来就不扫 `data`；测试的全量
禁用词扫描对 `url` 字段放行，其余位置仍禁止 `http`。除该例外，网关自写文字与字段名仍不得出现
来源名、主机名、URL 或实现词。

### T143 主机核对

AKShare 函数（读 1.20.65 源码确认实际请求主机；含 `push2` 的函数一律不用）：

| AKShare 函数 | 请求主机 | 证据 |
|---|---|---|
| `stock_news_em` | search-api-web.eastmoney.com | `akshare@1.20.65/stock/research/stock_news_stock.py:25` |
| `stock_news_global_cls` | www.cls.cn | `akshare@1.20.65/stock/research/stock_info.py:200` |
| `stock_news_global_em` | np-weblist.eastmoney.com | `akshare@1.20.65/stock/research/stock_info.py:67` |
| `macro_calendar_baidu` | finance.pae.baidu.com；另取 cookie 时访问 finance.baidu.com、hm.baidu.com | `akshare@1.20.65/macro/macro_news_baidu.py:61`、`akshare@1.20.65/utils/baidu_finance.py:34,129` |
| `stock_tfp_em` | datacenter-web.eastmoney.com | `akshare@1.20.65/stock/issue/stock_tfp_em.py:23` |
| `stock_irm_cninfo` | irm.cninfo.com.cn | `akshare@1.20.65/stock/board/stock_irm_cninfo.py:40`（组织代码在 :22） |
| `bond_cb_realtime_sina` | vip.stock.finance.sina.com.cn | `akshare@1.20.65/bond/bond_zh_cov.py:59` |

本任务没有使用 `bond_cb_list_em`：它把到期日、发行规模等字段裁掉，无法满足本任务的字段要求；
改为直接读取同一张报表 `RPT_BOND_CB_LIST`，并保留 `EXPIRE_DATE`、`ACTUAL_ISSUE_SCALE`。也没有
使用 `stock_zh_a_disclosure_report_cninfo`：它固定每页 30 条并一次翻完所有页，改为直接分页查询
以控制页数与返回量。

直接 HTTP、不经过 AKShare 的取数：

| 用途 | 主机/路径 | 证据 |
|---|---|---|
| 公告检索与代码→orgId | `www.cninfo.com.cn/new/hisAnnouncement/query`、`/new/data/szse_stock.json` | `src/cn_market_gateway/news_sources.py:136-237` |
| 公告 PDF 下载 | `static.cninfo.com.cn/finalpage/...` | `src/cn_market_gateway/news_sources.py:330-360` |
| 可转债条款与行情列 | `datacenter-web.eastmoney.com/api/data/v1/get`，报表 `RPT_BOND_CB_LIST` | `src/cn_market_gateway/news_sources.py:239-292` |
| 可转债未转股余额 | 同一主机，报表 `RPTA_WEB_KZZ_LS` | `src/cn_market_gateway/news_sources.py:294-328` |

以上主机全部加入 `config.HOST_POLICIES`，沿用按主机令牌桶、并发上限、最小间隔、300 秒熔断与
20 秒 AKShare 硬超时；下载 PDF 另有 25 秒超时与 25 MB 上限。

### T143 测试与样本

离线测试新增 `tests/test_news.py`、`tests/test_announcements.py`、
`tests/test_convertible_bonds.py`、`tests/test_news_contract.py` 与
`tests/test_news_old_parity.py`，覆盖：五种 `kind` 的正常/空结果/全部失败/参数错误；快讯合并
去重与单源失败；问答/日历/停复牌字段；公告白名单、分页、字数截断、`pdftotext` 缺失、重定向拒绝；
转股价值与溢价率公式、正股价缺失、剩余规模缺失；`url` 例外；`request_bytes` 的大小上限与跳转拒绝。
同一份录制样本同时送进旧 `cn_research`/`cn_extra` 工具与新工具，逐项比较文本与数值。

样本在 `tests/fixtures/news/`（真实响应的切片，只读）：柳工个股新闻、两类快讯、互动易问答、
2026-11-17 财经日历与停复牌、公告查询响应、一份 59 KB 的文本层公告 PDF、12 行可转债条款与
20 行转债行情。录制遵守限频，每类只取一次。

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tools/smoke.py --port 8798
```
