# fmp-mcp

只读的 Financial Modeling Prep（FMP）MCP，stdio 传输，暴露 17 个美股基本面/预期/内部人/日历工具。
没有写操作，不接触券商账户，不做交易。

## 工具

| 工具 | 上游（`https://financialmodelingprep.com`） | 参数 |
|---|---|---|
| `fmp_search_symbol` | `/stable/search-symbol` | `query`（代码或代码片段）, `limit`(1–50, 默认 10) |
| `fmp_search_name` | `/stable/search-name` | `query`（公司名，如 `apple`）, `limit`(1–50, 默认 10) |
| `fmp_get_quote` | `/stable/quote` | `symbol` |
| `fmp_get_profile` | `/stable/profile` | `symbol` |
| `fmp_get_income_statement` | `/stable/income-statement` | `symbol`, `period`(annual\|quarter), `limit`(1–40, 默认 5) |
| `fmp_get_balance_sheet` | `/stable/balance-sheet-statement` | 同上 |
| `fmp_get_cash_flow` | `/stable/cash-flow-statement` | 同上 |
| `fmp_get_ratios` | `/stable/ratios` | 同上 |
| `fmp_get_key_metrics` | `/stable/key-metrics` | 同上 |
| `fmp_get_analyst_estimates` | `/stable/analyst-estimates` | 同上 |
| `fmp_get_price_target` | `/stable/price-target-summary` | `symbol` |
| `fmp_get_analyst_grades` | `/stable/grades` | `symbol`, `limit`(1–100, 默认 5) |
| `fmp_get_insider_trades` | `/stable/insider-trading/search` | `symbol`, `limit`(1–100, 默认 5) |
| `fmp_get_earnings_calendar` | `/stable/earnings-calendar` | `from_date`, `to_date`（≤90 天） |
| `fmp_get_historical_prices` | `/stable/historical-price-eod/full` | `symbol`, `from_date`, `to_date`（≤5 年） |
| `fmp_get_shares_float` | `/stable/shares-float` | `symbol` |
| `fmp_get_stock_peers` | `/stable/stock-peers` | `symbol` |

`fmp_search_symbol` 按代码或代码片段搜索，**按公司名请用 `fmp_search_name`**。
`symbol` 必须匹配 `^[A-Za-z0-9.\-^]{1,15}$`，自动转大写；参数不合法直接返回
`invalid_argument`，不会请求上游。日期必须是 `YYYY-MM-DD`。

## 返回信封

每个工具返回一段文本，内容是一个 JSON 对象：

```json
{"ok": true, "source": "fmp", "market": "us", "as_of": "<ISO8601>", "status": "ready|empty",
 "data": {"endpoint": "fmp_get_quote", "count": 1, "rows": [], "available": 1,
          "truncated": false, "notes": []}}
```

`limit` 在客户端强制执行：即使上游忽略 `limit`（真实 `/stable/grades` 会这样），
`rows` 也会被截断到 `limit`，`count` 是截断后的行数；`data.available` 是上游实际返回的行数，
`data.truncated` 表示是否发生截断。没有 `limit` 参数的工具硬上限为 200 行（同样披露
`available`/`truncated`）。

出错时 `ok=false`、`status="error"`，并带 `error.code` / `error.message`：
`invalid_argument`、`missing_key`、`unauthorized`、`plan_restricted`、`rate_limited`、
`upstream_unreachable`、`upstream_error`。错误不会变成 MCP 协议错误。

`notes` 说明口径：财务报表金额是 `reportedCurrency` 的原始值（非美元不换算）；
`period` 是请求的年度/季度频率；`fiscalYear` 是财年标签而 `date` 是期末日期；
历史价格的复权口径以 `historical-price-eod/full` 上游字段为准，本包不改写数值
（复权口径未做独立确认）。

## 密钥规则

运行时按顺序取 `FMP_API_KEY`：

1. 进程环境变量 `FMP_API_KEY`；
2. `DSH_FINANCE_SECRETS` 指向的 dotenv 文件（`NAME=value` 逐行，只取 `FMP_API_KEY`）；
3. 默认 `<仓库根>/config/secrets.env`（相对本包位置解析）。

只读该文件、不读取其他变量。不要用 `FMP_API_KEY` 之外的方式传密钥。
安装密钥请自己运行 `python3 scripts/install-keys.py /path/to/keys.txt`。

没有密钥时服务器**仍能启动并列出 17 个工具**，调用返回 `missing_key`。

密钥不会出现在工具返回、`error.message`、stderr 或异常文本里：所有对外文本在输出前
都会把密钥值及 `apikey=…` 片段替换为 `***`。

## 上游地址与安全

- 生产只允许 `https://financialmodelingprep.com`，路径前缀 `/stable/`。
- 仅当 `FMP_TEST_MODE=1` 时，`FMP_BASE_URL` 才允许指向 `http://127.0.0.1:<端口>`（测试用）；
  其他任何值（包括 https 伪装域名）都会在启动时报错退出。
- 不跟随重定向。超时 10 秒。

## 限流与缓存

- 进程内缓存：行情类（`fmp_get_quote`）15 秒，其余 300 秒；**空结果与错误不缓存**。
- 客户端限流：每分钟最多 20 次上游请求，超出在本地返回 `rate_limited`。
- FMP 免费套餐每日约 250 次请求；套餐也可能限制某些端点（返回 `plan_restricted`）。
  批量研究时请优先用缓存、控制调用次数。

## 安装与运行

```bash
cd packages/fmp-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m fmp_mcp
```

MCP 客户端配置见 `overlays/fmp.cordis.yml`。

## 测试

```bash
.venv/bin/python -m pytest -q          # 离线，使用本包自带的假上游
.venv/bin/python -m pytest -q -m network  # 需要真实 FMP_API_KEY，默认不跑
```

## 已知限制

- 只覆盖美股（`market: "us"`），不支持其他市场。
- 套餐限制**以你的套餐为准**，常见受限：**内部人交易、非美交易所行情**（如 `002553.SZ`）。
  这些调用会返回 `plan_restricted`，不是网络错误。
- 上游字段原样返回，本包不做单位换算、不复权、不填补缺失值。
- 免费套餐的端点/历史窗口可能受限，错误码会如实映射。
- 缓存是进程内的，重启即失效；多进程之间不共享。
