# Chives 可选 OpenBB 数据接口

## 1. OpenBB MCP 的工作方式

`openbb-mcp-server 2.0.1` 把已安装的 OpenBB 扩展的每条 REST 路由映射为一个 MCP 工具。默认**不是**发现模式：本环境不限制分类时 `tools/list` 返回 **1150** 个工具（`packages/openbb-gateway/probe.py list` 实测输出首行 `1150`）。它另有 `--tool-discovery` 模式，只暴露 14 个元工具（`available_categories`、`available_tools`、`search_tools`、`call_tool`、`openbb_dispatch` 等），但调用要两步、且具体参数 schema 不可见。

`--allowed-categories` 可以在注册阶段按分类裁剪路由。本网关用 `equity,sec,news,yfinance,technical,nasdaq,federal_reserve,famafrench` 八个分类，`mcp-filter-proxy --check` 实测 `upstream_total: 393`；再由代理 `allow` 白名单只放出 **59** 个具体工具。也就是说：智能体看到的是 59 个带 schema 的直连工具，不是 393，也不是 1150。没有使用发现模式，因为直连工具对智能体更友好，且白名单已经保证不会“暴露几百个”。

## 2. 实测数据域

表中标 **2026-11-02** 的是本次经代理复测的结果；未标日期的结论来自 T62。复测时 Yahoo 持续限流，凡本次拿不到非空结果的 Yahoo 行数一律不保留。

| 数据域 | 结论 | 实测工具与提供方 | 实测结果摘要 |
|---|---|---|---|
| 行情/历史价格 | 可用 | `equity_price_historical`（nasdaq） | 2026-11-02：AAPL 单标的 43 行，OHLCV 正常；多标的沿用 T62 结论（本次未复测） |
| 实时报价 | 可用 | `equity_price_quote`（nasdaq） | 2026-11-02：AAPL 1 行，含名称、交易所、最新价 |
| 公司资料 | 可用 | `equity_profile`（nasdaq） | 2026-11-02：AAPL 1 行，`name=Apple Inc.`，含简介、行业、市值 |
| 财务报表 | 可用 | `equity_fundamental_income/balance/cash`（sec） | 2026-11-02：AAPL FY2025 `total_revenue=416161000000`，三表各 1 行 |
| 财务比率 | 可用（仅 nasdaq） | `equity_fundamental_ratios` | `provider=yfinance` 报 422；2026-11-02 `provider=nasdaq` 返回 1 行 |
| 成长指标 | 可用 | `equity_fundamental_income_growth`（sec） | 2026-11-02：AAPL 1 行；资产/现金流成长本次未复测 |
| 估值 | 部分可用 | `equity_historical_market_cap` | 只有市值历史，没有 P/E、EV/EBITDA 历史序列；2026-11-02 `provider=yfinance` 返回 429 |
| 分析师预期 | 本次不可复现 | `equity_estimates_price_target`、`yfinance_estimates_*` | 2026-11-02：`price_target`、EPS/营收/成长/评级估计均返回 `empty_result` 或 429；T62 的“有数据”无法复现 |
| 盈利日历 | 本次不可复现 | `yfinance_company_calendar`、`equity_calendar_earnings` | 2026-11-02：前者 `empty_result`；后者 `isError: true` 且错误消息为空 |
| 分红/拆股 | 可用 | `equity_fundamental_dividends`（nasdaq）、`equity_fundamental_historical_splits` | 2026-11-02：AAPL 83 条分红；拆股在无拆股区间返回空（已列入 `allow_empty`） |
| 内部交易 | 可用 | `equity_ownership_insider_trading`（sec）、`yfinance_ownership_insider_purchases` | 2026-11-02：前者 71 行；后者 `empty_result`（Yahoo 限流） |
| 机构持仓 | 可用 | `equity_ownership_institutional`（nasdaq） | 2026-11-02：AAPL 10 行 |
| 股本/流通股 | 本次不可复现 | `equity_ownership_share_statistics`（yfinance） | 2026-11-02：上游 429，未取得非空结果 |
| 做空数据 | 可用 | `equity_shorts_short_interest`（nasdaq） | 2026-11-02：AAPL 25 行 |
| SEC 文件 | 可用 | `sec_company_filings`（sec） | 2026-11-02：AAPL 最近 5 条 filing 元数据与链接 |
| SEC 公司概览/报表 | 部分复测 | `sec_company_overview`、`sec_financial_statements` | 前者返回 Item 1 文本；后者为 as-reported XBRL（本次未复测） |
| 行业/板块 | 本次不可复现 | `yfinance_sectors_overview`、`yfinance_sectors_industries`、`yfinance_industry_overview` | 2026-11-02：均 `empty_result`（Yahoo 限流）；行业概览需同时给 `sector` 与 `industry`（T62） |
| 市场状态 | 可用 | `nasdaq_markets_status` | 2026-11-02：返回 U.S. `Closed` 与下一次开闭市时间 |
| 新闻 | 本次不可复现 | `yfinance_news` | 2026-11-02：上游 429，未取得非空结果 |
| 股票筛选 | 本次不可复现 | `equity_screener`（yfinance） | 2026-11-02：上游 429，未取得非空结果 |
| 标的检索 | 本次不可复现 | `yfinance_search`、`equity_search`（sec） | 2026-11-02：`yfinance_search` 返回 `empty_result`；`equity_search` 本次未复测 |
| 经济日历 | 本次不可复现 | `yfinance_economy_calendar` | 2026-11-02：上游 429，未取得非空结果 |
| 经济指标 | 需密钥 | `fred_economy_cpi`（fred） | 报 `Missing credential 'fred_api_key'`，未暴露 |
| 国债收益率 | 可用 | `federal_reserve_treasury_rates` | 2026-11-02：248 行；数值为小数（0.0406 = 4.06%） |
| 市场风险溢价 | 部分可用 | `famafrench_factors` | 2026-11-02：1203 行 5 因子，含 `mkt_rf`、`rf`；无独立“风险溢价”端点 |
| 期权 | 可用 | `nasdaq_options_chains` | 2026-11-02：传 `expiration=2026-11-20` 返回 188 行；不传 expiration 的 T62 结果本次未复测 |
| 技术指标 | 部分可用 | `technical_rsi/sma/macd` | 必须传入价格序列 `data`，不能只给代码；2026-11-02 用 24 行 `data` 得到 RSI 23 行 |
| X/推特 | 不可用 | — | OpenBB 无对应工具 |

### 空数据与静默失败（实测）

- Yahoo 限流时，`equity_price_historical`、`equity_profile` 等会返回 `isError: false` 但 `results: []`，有时带 `warnings`。T64 起 OpenBB 网关启用了 `non_empty_result`，经代理调用会得到 `isError: true`、`error.code=empty_result`；直连上游（不经代理）仍需自己检查 `results` 长度与 `warnings`。
- `equity_ownership_form_13f`、`yfinance_industry_overview`（只给 industry 时）实测返回 `isError: false` 且文本为空；同样由 `non_empty_result` 拦截。
- `equity_calendar_dividend`（nasdaq）返回 `isError: true` 但错误消息为空；这类响应已经是错误，检查不会改写它。

## 4. 稳定性分级

分级口径：**高** = 官方或半官方来源、有稳定接口和明确更新节奏；**中** = 官方来源但延迟发布或按会话限频；**低** = 页面/接口抓取、无 SLA，限流时可能返回空；**取决于输入** = 本地计算，结果只和调用方传入的数据有关。

下表按 `recommended_call.backing` 汇总每个工具的数据来源。2026-11-02 复测时 Yahoo 持续限流，依赖 Yahoo 的工具已降级或保持为 `partial`，并在文末 JSON 的 `notes` 里逐条写明；本表不保留无法复现的行数。

| backing | 工具 | 数据来源 | 稳定性 |
|---|---|---|---|
| `nasdaq` | `equity_price_historical`、`equity_price_quote`、`equity_profile`、`equity_fundamental_ratios`、`equity_fundamental_historical_eps`、`equity_shorts_short_interest`、`equity_ownership_institutional`、`equity_fundamental_dividends`、`nasdaq_markets_status`、`nasdaq_options_chains` | Nasdaq 官方接口；报价与期权为延迟数据 | 高（官方；期权延迟，需传 `expiration` 控制体量） |
| `sec` | `equity_fundamental_income`、`equity_fundamental_balance`、`equity_fundamental_cash`、`equity_fundamental_income_growth`、`equity_ownership_insider_trading`、`equity_compare_company_facts`、`sec_company_filings` | SEC EDGAR、as-reported XBRL | 高（官方申报数据；XBRL 口径随 tag 变化） |
| `federal_reserve` | `federal_reserve_treasury_rates` | 美联储 H.15 国债收益率 | 高（官方；数值为小数，0.0406 = 4.06%） |
| `famafrench` | `famafrench_factors` | Kenneth French 学术因子数据集 | 高（学术官方；更新频率低） |
| `yahoo` | `yfinance_sectors_overview`、`yfinance_industry_overview`、`equity_historical_market_cap`、`yfinance_estimates_growth/revenue/earnings/eps_revisions/recommendations`、`yfinance_company_calendar`、`equity_estimates_price_target`、`equity_ownership_share_statistics`、`yfinance_ownership_insider_purchases`、`equity_fundamental_management`、`yfinance_news`、`yfinance_economy_calendar`、`equity_screener`、`yfinance_search` | Yahoo Finance 抓取 | 低（无 SLA；限流时返回 `empty_result` 或上游 429，绝不静默成功） |
| `other` | `technical_rsi`（以及同类的 `technical_sma/macd`） | 本地指标计算，`data` 由调用方提供 | 取决于输入（应先取官方价格序列） |

**判断**：生产用途优先选 `nasdaq`/`sec`/`federal_reserve`/`famafrench`。Yahoo 类工具只适合补充，调用方必须把 `empty_result` 当作“暂时拿不到”，不要当作“没有数据”；等限流恢复后按 JSON 里的 `recommended_call` 重试。`allow_empty` 只给 `equity_calendar_splits`：日期区间内没有拆股本来就是合法的空结果（已用周末区间实测）。
