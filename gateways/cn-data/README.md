# cn-data：A 股数据网关 v0

Chives 通过 `mcp-filter-proxy` 暴露 10 个只读数据工具。[适配器](provider.py)使用本地的 Python 数据组件，入口、缓存策略和限流参数见[网关配置](config.yaml)。恢复时，在 Chives 根目录执行以下命令，从已检出的数据组件源码重建。将示例路径换成该 Git 仓库在本机的位置。[源码与固定版本](../../skills/RESEARCH-LICENSES.md)安装器校验固定提交，只提取十项工具及其依赖，日常取数直接使用本地运行目录。

```bash
~/.agents/venv/bin/python3 gateways/cn-data/install-sdk.py "/实际路径/数据组件源码"
```

## 启动

```bash
# 在仓库根目录
packages/mcp-filter-proxy/.venv/bin/python -m mcp_filter_proxy \
  --config gateways/cn-data/config.yaml
```

stdout 走 MCP 协议，日志全部在 stderr。

不进入服务循环、只检查上游连通性与白名单：

```bash
packages/mcp-filter-proxy/.venv/bin/python -m mcp_filter_proxy \
  --config gateways/cn-data/config.yaml --check
```

期望最后一行 JSON 的 `exposed` 恰好是 10 个 `cn_*` 工具，`missing` 为空。

## 在 dsh 里启用

补丁文件是 `overlays/cn-data.cordis.yml`，只有一个顶层 `- insert:`，行 id 为 `fin-cn-data`。
它把代理注册成 serverName `cn_data` 的 stdio MCP 服务。建议用绝对路径：

```bash
dsh web --patch /Users/xiong/.chives/overlays/cn-data.cordis.yml
```

启用后模型看到的工具名是 `mcp__cn_data__cn_<upstream_name>`，例如
`mcp__cn_data__cn_get_market_data`。

补丁通过 `env` 显式转发 `GILDATA_TOKEN`（dsh 会过滤名字含 `TOKEN` 的环境变量）。
该变量只在需要 `cn_get_cn_announcements` 时必需，**不要把值写进任何文件**。

## 10 个工具

| 工具 | 说明 |
|---|---|
| `cn_search_symbol` | 用公司名或代码片段解析候选交易标的（返回 `002553.SZ` 这类规范代码）。 |
| `cn_get_market_data` | A 股 OHLCV K 线，支持 `1m/5m/15m/30m/1H/1D` 等周期。 |
| `cn_get_financial_statements` | 资产负债表、利润表、现金流量表或每期关键指标。 |
| `cn_get_fund_flow` | 按单笔金额分档（main/super_large/large/medium/small）的资金净流入。 |
| `cn_get_dragon_tiger` | 指定交易日的龙虎榜；给 `code` 时附买卖席位。 |
| `cn_get_margin_trading` | 个股融资融券余额与融资买入/偿还的日序列。 |
| `cn_get_block_trades` | 个股大宗交易逐笔明细（价格、数量、溢价、买卖营业部）。 |
| `cn_get_shareholder_count` | 股东户数历史及相对上一披露期的变化、户均持股。 |
| `cn_get_lockup_expiry` | 限售股解禁时间表；不给 `code` 时返回全市场未来解禁日历。 |
| `cn_get_sector_info` | 个股所属行业/概念板块，或按当日涨跌幅给行业板块排名。 |
| ~~`cn_get_northbound_flow`~~ | **已从白名单移除**：自 2024-08-30 起上游无数据，2026-11-16 复测仍为空，故移除。 |
| ~~`cn_get_cn_announcements`~~ | **已从白名单移除**：上游需要 `GILDATA_TOKEN`，我们没有；公告请用 cn_extra 的 `cn_get_announcements`（巨潮，免密钥）。 |

## 缓存与限流

- 缓存 TTL：`cn_get_market_data` 30 秒、`cn_get_fund_flow` 120 秒、
  `cn_get_financial_statements` 3600 秒，其余 300 秒。
- 限流：每个代理进程每分钟最多 40 次上游调用；缓存命中不占额度。

## 单位与时效（2026-11-02 实测）

完整的字段/单位/时效/失败方式见 `docs/cn-data-tool-matrix.md`；这里只列最容易读错的几条。

| 工具 | 关键单位/时效 |
|---|---|
| `cn_get_market_data` | 价格 CNY/股，`volume` 手；日线只到上一交易日（11-02 收盘后请求 `end_date=11-02` 只返回 10-30）。 |
| `cn_get_fund_flow` | 五档均为 CNY 净流入；`daily` 收盘后含当日。 |
| `cn_get_margin_trading` | 余额/买入/偿还/融券余额 CNY，`short_volume` 股；数据 T+1。 |
| `cn_get_block_trades` | 价格 CNY/股，`deal_volume` 股，`deal_amount` CNY；`premium_ratio` 是**小数**（`-0.2955` = -29.55%），不是百分数。 |
| `cn_get_shareholder_count` | 户数/增减为户，比例百分数；`avg_hold_*` 与 `total_market_cap` 仅最新一期有值。 |
| `cn_get_lockup_expiry` | 数量万股、市值万元；`free_ratio`/`total_ratio` 是**小数**（`0.0211` = 2.11%）。 |
| `cn_get_sector_info` | `change_pct` 百分数；`price`/`index` 是板块指数点，不是个股价格；`leader` 是代码。 |

## 校验失败提示（`hint`）

代理的响应校验失败时，可以把一句可执行的提示写在该 check 的 `hint` 字段里，它会原样出现在
错误对象中；不配置时错误对象里没有 `hint`。`hint` 必须是非空字符串，最长 300 字符。

本网关给 `get_market_data` 配了中文提示，历史 `1m` 请求被 `date_range_mismatch` 拒绝时会返回：

```json
{"error": {"code": "date_range_mismatch", "requested": ["2026-10-30", "2026-10-30"], "returned_dates": ["2026-10-30", "2026-11-02"], "returned_count": 2, "hint": "本接口 1m 只返回当天数据，无法回溯历史；请改用 cn_extra 的 cn_get_minute_bars 或 cn_intraday_summary 获取分钟级数据。"}}
```

`returned_count` 是上游本次返回的、带可用日期字段的行数，便于判断上游实际给了多少行。
提示文字只存在于本目录的 `config.yaml`，代理代码不含任何具体工具名。

## 已知限制

- **非实时**：数据来自上游的网页接口快照，存在分钟级延迟；`1m` 周期尤其明显。
- **`1m` 只有当天**：请求历史日期时上游会悄悄返回当天数据；网关配置了
  `bars_within_requested_dates` 校验，会以 `date_range_mismatch` 拒绝，不再把错误日期的
  数据交给调用者。
- **分钟线回溯窗口**：`5m/15m/30m/1H` 可回溯约 31 个交易日（2026-11-02 实测），
  更早的分钟线不可用。
- **日线 `volume` 单位是手**：1 手 = 100 股，换算成股数需乘以 100。
- **依赖东方财富网页接口**：多数工具走 Eastmoney 的免费公开端点，接口字段或限流策略
  随时可能变化；`cn_get_market_data` 的日线在 Eastmoney 失败时会回退到腾讯。
- **可能限流**：上游按来源 IP 限流，代理的 40 次/分钟只约束本进程，不能避免被上游拒绝。
- **未做多源回退**：除上游自身已有的单点回退外，网关不提供第二个数据源、重试或熔断。
- **被移除的工具当前不可用**：`cn_get_northbound_flow`（上游无数据）与 `cn_get_cn_announcements`（需要
  `GILDATA_TOKEN`）都已移出白名单，不会暴露给智能体。
- **业务错误不是协议错误**：上游把失败包在 `{"ok": false, "error": "..."}` 里，MCP 层
  `isError` 通常仍是 `false`；调用方必须先看 `ok`，不能只看 `isError`。
- **龙虎榜与 AKShare 行数口径不同**：同一交易日 `2026-10-30`，本工具 93 行、AKShare 96 行；
  多出的 3 行是可转债（`118027`、`118058`、`123267`），A 股股票行完全一致。
- **只读**：10 个工具全部不涉及交易、下单或写操作。
