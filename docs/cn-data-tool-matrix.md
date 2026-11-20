# Chives 可选 cn_data 接口与数据口径

- 实测日期：2026-11-02（周一，A 股交易日）。
- 实测路径：该适配器经 `packages/mcp-filter-proxy` 加载 `gateways/cn-data/config.yaml` 接入上游 MCP。
- 标的与日期：主要用 `002553.SZ 南方精工`；日线区间 `2026-10-26` 至 `2026-10-30`；龙虎榜用 `2026-10-30`；大宗交易用有成交的 `600519.SH` 与 `920083.BJ`。
- 单位口径：优先用“与 AKShare 同口径数字逐项比对”确认；没有比对或无法确认的，明确写“未确认”，不按字段名猜。
- 统一响应外壳：上游业务错误放在 JSON 的 `ok:false` 里，MCP 协议层 `isError` 仍可能是 `false`；调用方必须检查 `ok`。代理只在成功结果上追加 `meta`（缓存命中/延迟/`proxy`）和 `annotations`（单位）。见 `packages/mcp-filter-proxy/README.md:124-129,145-167` (dsh-finance)。

当前启用项以 [cn_data 网关配置](../gateways/cn-data/config.yaml) 的 allow 列表为准，以下也包括历史字段，便于解读旧数据。

## 通用约定

| 项 | 说明 |
|---|---|
| 代码格式 | A 股用 `<6位代码>.<SH|SZ|BJ>`，如 `002553.SZ`；部分工具也接受裸 6 位代码或 `sh600519`。 |
| 日期格式 | 参数用 `YYYY-MM-DD`；返回字段可能是 `YYYY-MM-DD` 或 `YYYY-MM-DD 00:00:00` / ISO `T` 格式。 |
| 业务错误 | `{"ok": false, "error": "..."}`，MCP `isError` 通常为 `false`。 |
| 代理限流 | 每进程 40 次/分钟（`gateways/cn-data/config.yaml:31-32`），缓存命中不占额度。本次实测全程 ≤30 次/分钟，未触发代理 `rate_limited`。 |
| 上游限流 | 多数工具走 Eastmoney 免费接口，按来源 IP 限流；没有重试或第二数据源（`gateways/cn-data/README.md:100-103`）。 |
| 缓存 TTL | 日线 30s、资金流 120s、财务 3600s、其余 300s（`gateways/cn-data/config.yaml:24-30`）。 |

## 1. `cn_search_symbol`

把公司名/代码片段解析成规范代码。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `query` | 是 | string | 中文或英文公司名/代码片段。 |
| `limit` | 否 | integer | 合并候选上限，默认 10。 |

已验证示例：

```json
{"query": "南方精工", "limit": 3}
```

返回字段：

| 字段 | 单位/含义 |
|---|---|
| `ok` / `market` / `source` | 布尔 / `"multi"` / `"symbol_search"`。 |
| `data.count` | 候选数量（个）。 |
| `data.candidates[]` | `symbol`、`name`、`market`、`type`、`source`；无行情数值。 |
| `data.sources` | 各来源状态，如 `eastmoney: "ok"`、`yahoo: "skipped: non-ASCII query..."`。 |

数据时效：调用时实时查询；中文查询只走 Eastmoney，Yahoo 会被跳过。实测 `南方精工` 返回 1 个候选 `002553.SZ`，`data.count=1`。

已知失败/限流：解析不到时预期 `count=0`（本次未构造该用例，未验证）；代理限流 40 次/分钟。

## 2. `cn_get_market_data`

A 股 OHLCV K 线。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `codes` | 是 | string[] | 规范代码数组，如 `["002553.SZ"]`。 |
| `start_date` | 是 | string | `YYYY-MM-DD`，含当日。 |
| `end_date` | 是 | string | `YYYY-MM-DD`，含当日。 |
| `interval` | 否 | string | `1m/5m/15m/30m/1H/4H/1D/1W/1M`，默认 `1D`。 |
| `source` | 否 | string | 默认 `auto`；A 股实测落到 `tencent`。 |
| `max_rows` | 否 | integer | 每标的上限，默认 250；`0` 表示不限。 |

已验证示例：

```json
{"codes": ["002553.SZ"], "start_date": "2026-10-26", "end_date": "2026-10-30", "interval": "1D"}
```

返回字段：

| 字段 | 单位 |
|---|---|
| 顶层键 `002553.SZ` | 该标的的行数组。 |
| `trade_date` | ISO 日期/时间字符串。 |
| `open` / `high` / `low` / `close` | CNY/股。 |
| `volume` | 手（lots，1 手 = 100 股）；`_provenance.volume_unit` 也会写 `lots`。 |
| `_provenance.<code>` | `source`、`requested_source`、`detected_source`、`fallback_used`、`currency_conversion`、`volume_unit`、`adjustment`。 |
| `meta.units` | 代理追加的单位标注，含 `volume: "lots (1 lot = 100 shares)"`。 |

数据时效：日线只到上一交易日。2026-11-02 收盘后请求 `end_date=2026-11-02`，只返回 2026-10-30 一根，当日日线尚未可用。`1m` 历史请求会被代理以 `date_range_mismatch` 拒绝，`1m` 只返回当天；`5m/15m/30m/1H` 约可回溯 31 个交易日（本次未重测，沿用 T11/T12 结论）。

已知失败/限流：历史 `1m` 会返回 `isError:true` 的 `date_range_mismatch`，带 `requested`、`returned_dates`、`returned_count`、`hint`；未知代码或上游失败可能返回 `ok:false`（本次未构造，未验证）。上游按 IP 限流，日线在 Eastmoney 失败时会回退腾讯。

## 3. `cn_get_financial_statements`

财务报表/每期关键指标。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `code` | 是 | string | 带市场后缀的单一代码，如 `002553.SZ`。 |
| `statement` | 否 | string | `balance` / `income` / `cashflow` / `indicators`，默认 `indicators`。 |
| `period` | 否 | string | `annual` / `quarter`，默认 `annual`。 |
| `offset` | 否 | integer | 从最新一期起的偏移，默认 0。 |

已验证示例：

```json
{"code": "002553.SZ", "statement": "indicators", "period": "annual"}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `paging.total` / `returned` / `offset` / `next_offset` / `complete` | 条数/偏移；`returned` 是本次返回的期数，不是总期数。 |
| `data.<code>.periods[]` | 以 `REPORT_DATE`、`REPORT_TYPE`、`REPORT_DATE_NAME`、`NOTICE_DATE`、`CURRENCY` 开头的扁平指标行。 |
| `CURRENCY` | 实测 `CNY`。 |
| 金额类（`TOTALOPERATEREVE`、`MLR`、`PARENTNETPROFIT`、`KCFJCXSYJLR`、`TOTAL_ASSETS_PK`、`OPERATE_INCOME_PK`、`NETCASH_*_PK`、`TOTAL_EQUITY_PK`、`LIABILITY`、`RDEXPEND`） | CNY。 |
| 每股类（`EPSJB`、`EPSKCJB`、`EPSXS`、`BPS`、`MGZBGJ`、`MGWFPLR`、`MGJYXJJE`） | CNY/股。 |
| 已核对的百分数列（`ROEJQ`、`ZZCJLL`、`XSJLL`、`XSMLL`、`ZCFZL`、`TOTALOPERATEREVETZ`、`PARENTNETPROFITTZ`） | 百分数（如 `26.54` = 26.54%）。 |
| 周转天数（`ZZCZZTS`、`CHZZTS`、`YSZKZZTS`、`PAYABLE_TDAYS` 等） | 天。 |
| 周转率（`TOAZZL`、`CHZZL`、`YSZKZZL`） | 次。 |
| `STAFF_NUM` / `RDPERSONNEL` | 人。 |
| `AVG_TOI` / `AVG_NET_PROFIT` | CNY/人。 |
| `TOTAL_SHARE` / `A_FREE_SHARE` / `B_FREE_SHARE` | 股。 |
| 其余数值列（如 `ROEKCJQ`、`TAXRATE`、`PER_TOI`、`PER_EBIT`、`TOTALOPER_RATIO`、`SS_OI` 等） | **未确认**：没有逐项与原始报表或 AKShare 对齐，不按名字猜。 |

数据时效：`period=annual` 最新为 2025 年报（`REPORT_DATE=2025-12-31`，`NOTICE_DATE=2026-04-15`）；`period=quarter` 最新为 2026 三季报（`REPORT_DATE=2026-09-30`）。每次只返回 2 期，需按 `paging.next_offset` 翻页。

已知失败/限流：忽略 `paging` 会把“本次 2 期”误当成全部；非法代码/不支持的市场预期 `ok:false`（本次未构造，未验证）。上游按 IP 限流。

## 4. `cn_get_fund_flow`

按单笔金额分档的资金净流入。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `codes` | 是 | string[] | 规范代码数组。 |
| `period` | 否 | string | `daily`（默认）或 `min`。 |
| `days` | 否 | integer | `daily` 保留的最近交易日数，默认 30。 |

已验证示例：

```json
{"codes": ["002553.SZ"], "days": 5}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `buckets` | `["main","small","medium","large","super_large"]`。 |
| `data.<code>.rows[].timestamp` | `daily` 为 `YYYY-MM-DD`；`min` 为带时分的字符串。 |
| `main` / `super_large` / `large` / `medium` / `small` | CNY 净流入，正数=流入、负数=流出。 |
| `fallback_sources` | 备用源列表，实测含 `tushare`（本次未实际回退）。 |

数据时效：`daily` 收盘后包含当日。2026-11-02 收盘后调用返回 2026-10-27 至 2026-11-02 共 5 行。盘中当日行是否完整，**未验证**。

已知失败/限流：一个无法解析的代码按标的单独报错、不中断整批（工具描述如此，本次未构造，未验证）；`period` 非法值的行为未验证。上游按 IP 限流。

## 5. `cn_get_dragon_tiger`

指定交易日的龙虎榜；给 `code` 时附买卖席位。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `date` | 是 | string | `YYYY-MM-DD`。 |
| `code` | 否 | string/null | 省略=全市场；给出则只保留该股并附席位。 |

已验证示例：

```json
{"date": "2026-10-30"}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `data.count` | `appearances` 的行数；给 `code` 时是 1。 |
| `appearances[].close` | CNY/股。 |
| `appearances[].change_pct` | 百分数（`10.0057` = 10.0057%）。 |
| `appearances[].net_buy` / `buy_amount` / `sell_amount` | CNY。 |
| `appearances[].turnover` | CNY（该股当日市场总成交额）。 |
| `appearances[].reason` | 上榜原因文本。 |
| `seats[].buy` / `sell` / `net` | CNY。 |
| `seats[].rank` | 席位在该侧、该上榜原因内的 1 基序号。 |
| `seats[].trade_id` | 上榜原因分组 id，不是金额。 |

数据时效：按指定历史日期查询，`2026-10-30` 可正常返回；全市场 `count=93`，带 `code=000568` 时返回该股 1 条 + 12 个席位。

已知失败/限流：非法日期不做本地校验，直接送上游；实测 `2026-13-99` 返回 `ok:false`，错误原文为 `eastmoney dragon-tiger fetch failed: Eastmoney rejected RPT_DAILYBILLBOARD_DETAILS (code=9501 message=日期格式有误); tushare fallback failed: TUSHARE_TOKEN is not configured`。非交易日大概率 `count=0`（未验证）。席位请求实测约 2.6 秒，上游按 IP 限流。

## 6. `cn_get_northbound_flow`

北向资金（沪股通/深股通）净流入。**本次不可用**。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `lookback_days` | 否 | integer | 日历史回看交易日数，默认 30，上限 250。 |

已验证示例（会失败）：

```json
{"lookback_days": 10}
```

实际返回（原文摘要）：

```json
{"ok": false, "error": "eastmoney northbound net-flow feed is dead (empty/all-zero since the 2024-08-30 HKEX disclosure change); tushare fallback failed: TUSHARE_TOKEN is not configured"}
```

返回字段（仅按上游源码，**未拿到成功响应**）：成功时 `data.unit` 为 `"10k CNY"`，另有 `lookback_days`、`realtime`、`history`；回退成功时 `source: "tushare"` 并带 `warnings`。单位按源码为 10k CNY，但因无数据，实际字段与单位**未验证**。

数据时效：上游称 Eastmoney 净流入端点自 2024-08-30 HKEX 披露规则变化后为空/全零。AKShare 同日 `stock_hsgt_fund_flow_summary_em()` 的北向“成交净买额/资金净流入”也显示 `0.0`，与该失败原因一致。

已知失败/限流：MCP 层 `isError=false`，业务错误在 `ok:false`；没有 `TUSHARE_TOKEN`，无法回退。代理限流 40 次/分钟。

## 7. `cn_get_margin_trading`

个股融资融券日序列。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `code` | 是 | string | 裸代码、带后缀或 `sh600519` 形式。 |
| `days` | 否 | integer | 最近交易日数，默认 30，上限 250。 |

已验证示例：

```json
{"code": "002553.SZ", "days": 5}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `data.code` | 裸 6 位代码。 |
| `trade_date` | `YYYY-MM-DD`。 |
| `financing_balance` | CNY（融资余额）。 |
| `financing_buy` | CNY（融资买入额）。 |
| `financing_repay` | CNY（融资偿还额）。 |
| `short_balance` | CNY（融券余额）。 |
| `short_volume` | 股（融券余量）。 |
| `margin_total_balance` | CNY（融资融券余额）。 |

数据时效：T+1。2026-11-02 收盘后最新只到 2026-10-30，当日两融数据尚未发布。

已知失败/限流：非 A 股代码返回 `ok:false`，实测 `AAPL.US` 原文 `Unsupported symbol: margin trading covers A-shares only (e.g. 600519.SH or 000001.SZ).`；上游按 IP 限流。

## 8. `cn_get_block_trades`

个股大宗交易逐笔明细。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `code` | 是 | string | 带 `.SH/.SZ/.BJ` 的代码。 |
| `days` | 否 | integer | 截止今天的日历日回看窗口，默认 30，范围 1–365。 |

已验证示例：

```json
{"code": "600519.SH", "days": 30}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `data.count` | 记录数；`0` 且 `records=[]` 是“窗口内无大宗交易”的正常结果，不是错误。 |
| `trade_date` | 可能是 `YYYY-MM-DD 00:00:00`。 |
| `close_price` / `deal_price` | CNY/股。 |
| `premium_ratio` | 相对收盘价的**小数**，不是百分数：`-0.2955` = 折价 29.55%。已用 `920083.BJ` 与 AKShare `折溢率=-0.295533` 对齐。 |
| `deal_volume` | 股。 |
| `deal_amount` | CNY。 |
| `buyer_seat` / `seller_seat` | 营业部名称文本。 |

数据时效：窗口截止今天，披露后可见。`600519.SH` 近 30 天 4 笔（最新 2026-10-29）；`920083.BJ` 在 2026-10-30 当天有 1 笔。

已知失败/限流：非法代码 `ok:false`（本次未构造，未验证）；`days` 会被夹到 1–365；上游按 IP 限流。

## 9. `cn_get_shareholder_count`

股东户数历史、相对上一披露期的变化、户均持股。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `code` | 是 | string | 带 `.SH/.SZ/.BJ` 后缀。 |
| `max_periods` | 否 | integer | 最近披露期数，默认 24，范围 1–24。 |

已验证示例：

```json
{"code": "002553.SZ", "max_periods": 8}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `end_date` / `prev_period_end` | 披露期截止日 / 上一披露期截止日。 |
| `holder_count` | 户（股东账户数）。 |
| `holder_count_change` | 户（相对上期增减）。 |
| `holder_count_change_pct` | 百分数（`12.304` = 12.304%）。 |
| `avg_hold_shares` | 股/户；**只有最新一期有值，历史期为 `null`**。 |
| `avg_hold_amount` | CNY/户；同样只有最新一期有值。 |
| `total_market_cap` | CNY；同样只有最新一期有值。 |

数据时效：最新披露期 `2026-09-30`（公告日 `2026-10-26`）；披露间隔不固定（季报 + 临时披露），每行自带 `prev_period_end`。

已知失败/限流：非 `.SH/.SZ/.BJ` 或无法解析的代码返回 `ok:false`（本次未构造，未验证）；上游按 IP 限流。

## 10. `cn_get_lockup_expiry`

限售股解禁时间表。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `code` | 否 | string | 给代码=该股全历史解禁；省略=全市场未来解禁日历。 |
| `horizon_days` | 否 | integer | 全市场日历窗口，默认 90，范围 1–365；给 `code` 时忽略。 |

已验证示例：

```json
{"code": "002553.SZ"}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `scope` | `single_code` 或 `market_calendar`。 |
| `count` | 记录数；全市场最多 200 条，达到上限时带 `truncated: true`。 |
| `free_date` | `YYYY-MM-DD`。 |
| `free_shares` / `able_free_shares` / `float_shares` | 万股（10k shares）。 |
| `lift_market_cap` | 万元（10k CNY）。 |
| `free_ratio` | 占流通股本的**小数**（`0.0211` = 2.11%）。 |
| `total_ratio` | 占总股本的**小数**（`0.0153` = 1.53%）。 |
| `share_type` | 限售股类型文本。 |
| `as_of` / `horizon_days` | 仅全市场日历有。 |

数据时效：给代码返回全历史（最新一条可能早于今天）；全市场日历 `as_of=2026-11-02`，`horizon_days=30` 时 158 条。

已知失败/限流：非法代码 `ok:false`，实测 `AAPL.US` 原文 `unrecognized A-share code 'AAPL.US'; expected a 6-digit code such as '600519' or '600519.SH'`；上游按 IP 限流。

## 11. `cn_get_sector_info`

个股所属行业/概念板块，或行业板块当日排名。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `code` | 否 | string | `mode=membership` 时必填；`mode=ranking` 时忽略。 |
| `mode` | 否 | string | `membership`（默认）或 `ranking`。 |
| `limit` | 否 | integer | `ranking` 返回的板块数，默认 30。 |

已验证示例：

```json
{"code": "002553.SZ"}
```

返回字段：

| 字段 | 单位 |
|---|---|
| `boards[].board_code` / `board_name` | 板块代码/名称。 |
| `boards[].change_pct` | 百分数（`1.84` = 1.84%）。 |
| `boards[].price` | **板块指数点**，不是个股价格（membership 模式）。 |
| `boards[].index` | 板块指数点（ranking 模式）。 |
| `boards[].up_count` / `down_count` | 板块内上涨/下跌家数。 |
| `boards[].leader` | 领涨股**代码**（不是名称）。 |

数据时效：调用时当日快照。`002553.SZ` 返回 17 个板块；`ranking` 模式返回当日涨幅排名，实测前二为 `BK1296 视频媒体 +20.00%`、`BK1556 教育运营及其他 +13.51%`。

已知失败/限流：`mode=membership` 不给 `code` 的行为未验证；`mode` 非法值未验证；上游按 IP 限流。

## 12. `cn_get_cn_announcements`

中文公告检索。**本次不可用**。

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `query` | 是 | string | 自然语言公告请求，如“南方精工 2025年年度报告”。 |
| `limit` | 否 | integer | 最大返回行数，默认 50。 |

已验证示例（会失败）：

```json
{"query": "南方精工 2025年年度报告", "limit": 5}
```

实际返回：

```json
{"ok": false, "error": "GILDATA_TOKEN is not configured"}
```

返回字段：本次没有成功响应，字段与单位**未验证**；按工具描述应含标题、发布日期、高亮摘录。

数据时效：**未验证**（没有 token，无法取数）。

已知失败/限流：未配置 `GILDATA_TOKEN` 时上游直接返回 `ok:false`，MCP 层 `isError=false`；`gateways/cn-data/README.md:37-38` 也说明该工具需要该 token。

