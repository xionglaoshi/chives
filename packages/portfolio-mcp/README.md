# portfolio-mcp

本地 A 股持仓簿 MCP 服务器（stdio），暴露十一个工具：`portfolio_get`、`portfolio_parse_csv`、`portfolio_import_preview`、`portfolio_import_commit`、`portfolio_add_position`、`portfolio_update_position`、`portfolio_remove_position`、`portfolio_set_cash`、`portfolio_clear`、`portfolio_valuation`、`portfolio_risk`。

**不对接券商账号**：国内券商基本没有对个人开放的官方只读接口。用户从券商 App 导出持仓表（CSV/Excel 文本）、或截图（由智能体读图后给出行数据）、或口述，智能体整理成行数据；用户自己要求记录持仓时，请求本身就是同意，**单笔买入直接用 `portfolio_add_position` 写入**，整表导入 preview 后只要没有警告、也不删除已有持仓，就直接 commit 落盘。只有 preview 有警告或会覆盖/删除已有持仓时，才先把这些点告诉用户。

- 入口：`python -m portfolio_mcp`（stdio MCP 服务器），或安装后的 `portfolio-mcp`
- Python 3.12；依赖只有 `mcp`（行情用标准库 `urllib`）
- 日志只写 stderr，stdout 只承载 MCP 协议
- 不读密钥、不执行子进程、不做任何交易

## 安装与运行

```bash
cd packages/portfolio-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m portfolio_mcp
```

## 目录与权限

| 用途 | 环境变量（按优先级） | 缺省 |
|---|---|---|
| 持仓 JSON | `DSH_FINANCE_PROFILE_DIR` → `DSH_HOME` | `~/.dsh` |

- 文件：`<profile_dir>/finance-portfolio.json`，权限 `0600`，同目录临时文件 + `os.replace()` 原子写入。
- 每个 `DSH_HOME` 一份，访客实例读不到。
- 文件损坏或形状不对时按空持仓处理，返回 `portfolio_corrupt` 警告，不覆盖原文件。
- 最多 100 个持仓；超过则拒绝（`too_many_positions`）。

## 导入流程（文字）

```
用户粘贴券商表格 / 截图文字 / 口述整表
        │
        ▼
portfolio_parse_csv(text)            ← 只解析，不落盘；坏行进 rejected
        │  rows
        ▼
portfolio_import_preview(rows, mode) ← 校验 + 与现有持仓 diff；返回 confirm_token（10 分钟、一次性）
        │  added / changed / removed / warnings
        ├─ 无警告、且不删除/覆盖已有持仓 → 直接 commit
        └─ 有警告，或会删除/覆盖已有持仓 → 先把这几点告诉用户，再 commit
        │
        ▼
portfolio_import_commit(confirm_token) ← 仅此处写盘；token 不匹配/过期/复用 → invalid_token
```

- 用户口头说“买了 / 加仓”时不必走整表导入：直接用 `portfolio_add_position` 写入（代码已存在则默认合并）。
- `mode="replace"`：整簿替换，未出现的代码进 `removed`。
- `mode="merge"`：按代码合并，表中未出现的持仓保留。
- preview **不写盘**；commit 成功后 `as_of` 更新为导入日期。

## 字段与单位

持仓字段（存储与工具入参同名）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 规范为 `NNNNNN.SH/.SZ/.BJ`；6 位以下裸码左补零后按前缀推断；A 股股票与沪 5/深 159、16 开头的 ETF/LOF 基金可入库，港股/美股/B 股拒绝 |
| `name` | string | ≤20 字，清洗换行/控制字符/`<>`/反引号 |
| `qty` | integer | 单位**股**，正整数；允许零股，不要求整百 |
| `available_qty` | integer? | 单位**股**，0 ≤ 可用 ≤ `qty` |
| `cost_price` | number | 单位**元/股**，正数 |
| `opened_date` | string? | `YYYY-MM-DD`，不得晚于今天；等于今天时 T+1 不可卖 |
| `industry` | string? | ≤20 字 |
| `note` | string? | ≤60 字 |

账户字段：`cash`（元，≥0，可选）、`as_of`（最近一次导入日期）。

所有工具输出：**金额单位元、数量单位股**。规范化字段名带单位后缀（`*_cny`、`*_shares`），同时保留任务书里的短名别名（`market_value`、`qty` 等），两者数值相同。`change_pct` / `pnl_pct` / 权重 / HHI 均为百分数或 0–1 小数（权重与 HHI 是 0–1）。

## 工具

### `portfolio_get()`

返回 `positions`、`count`、`cash`、`as_of`、`updated_at`、`empty`；空簿带 `hint`。返回带 `"private": true` 与 `"untrusted_text": false`。

### `portfolio_parse_csv(text)`

识别常见券商表头同义词（代码/证券代码/股票代码，名称/证券名称/股票名称，数量/股票余额/持仓数量/当前持仓/持股数量/证券数量，可用/可用余额/可卖数量/可用数量，成本价/参考成本价/买入均价/摊薄成本价/持仓成本，行业，建仓日期，备注）；分隔符支持逗号、制表符、两个以上空格；处理 BOM、千分位逗号、`="000001"` Excel 文本前缀、`--` 空值、Excel 去掉前导零。市值、盈亏、手续费、现价等列**忽略**，估值一律自己算。解析不了的行进 `rejected` 并给 `line` / `reason` / `field`。

### `portfolio_import_preview(rows, mode="replace")`

校验并规范化 rows，返回：

- `added`（完整行）、`changed`（`{code, before, after, fields}`）、`removed`（完整行）、`unchanged`（代码列表）
- `summary`：四类计数 + `total_after`
- `confirm_token`、`expires_in_seconds=600`、`plan_hash`（rows+mode 的 SHA-256 前 16 位）
- 警告：`quote_missing`（代码可能不存在/退市）、`name_mismatch`、`cost_deviation_high`（成本偏离现价 >80%）、`qty_suspected_lots`（qty<100 且 6 开头）、`quote_unavailable`

### `portfolio_import_commit(confirm_token)`

只有有效 token 才写盘；token 绑定 preview 时的 rows 与 mode，一次性，10 分钟过期。用户要求导入时，preview 后可直接 commit，不必再让用户二次确认；**仅当 preview 有警告，或会删除/覆盖已有持仓时**，先把这些点告诉用户再提交。

### `portfolio_add_position(code, quantity, cost, name?, available?, opened_at?, industry?, note?, merge=true)`

用户口头要求记录一笔买入时直接写盘，不再二次确认。

- 代码不存在：新增，返回 `before: null`、`after`、`count`（持仓笔数）与 `action: "added"`；`as_of` 更新为今天。
- 代码已存在且 `merge=true`（默认）：数量相加，成本按数量加权平均并保留 4 位小数，返回 `before` / `after` / `action: "merged"`，`formula` 给出合并算式，例如 `1000 × 9.5000 + 500 × 10.5000 = 14750.0000；14750.0000 ÷ 1500 = 9.8333`。未传的可选字段保留原值；`available` 若传入按合并后的总可用数量写入。
- `merge=false` 且代码已存在：返回 `invalid`，提示改用 `portfolio_update_position`。
- 校验与导入一致：代码规范化、`quantity` 正整数、`cost` > 0、拒绝账号/密钥形态文本；名称与行情不符时给 `name_mismatch` 警告但仍写入。`name` 省略时用行情名称，取不到行情则用规范代码。

### `portfolio_update_position(code, fields)` / `portfolio_remove_position(code)`

单只修改/删除，用于“我卖了 X / 成本改成 Y / 清仓了某只”。用户说了就直接调用，不再要求用户二次确认。返回 `before` / `after` 或 `removed`。修改时 `code` 不可变。

### `portfolio_set_cash(cash)` / `portfolio_clear(confirm=true)`

`set_cash` 用户说了就直接调用并汇报 `cash_before_cny` → `cash_after_cny`。`clear` 仍必须显式 `confirm=true`，且只在用户明确要求“清空”时调用，否则 `confirmation_required`。

### `portfolio_valuation()`

经本机数据网关 `market_quote` 取全部持仓（≤100）的快照：每批最多 20 只，超过则串行分批（100 只 = 5 批），不跟随重定向，网关不可达时不回退直连。每只返回：

`price_cny`、`prev_close_cny`、`change_pct`、`market_value_cny`、`cost_value_cny`、`pnl_cny`、`pnl_pct`、`weight`、`weight_incl_cash`、`limit_up_cny`、`limit_down_cny`、`at_limit_up`、`at_limit_down`、`sellable_today`、`sellable_qty_shares`、`price_unavailable`、`quote_time`。

- 取不到/停牌的标 `price_unavailable: true`，不中断，也不计入汇总。
- 有 `available_qty` 以它为准；否则 `opened_date == 今天` 判 T+1 不可卖。
- 汇总：`total_market_value_cny`、`total_cost_cny`、`total_pnl_cny`、`total_pnl_pct`、`cash_cny`、`total_assets_cny`、`top1_weight`、`top5_weight`、`hhi`、`effective_n`（只计持仓）；含现金版本 `*_incl_cash`；`quote_time`、`fetched_at`。
- 非交易时段/非当日行情在 `warnings` 里给 `stale_quote`，说明价格是上一时段最后值。
- 返回带 `"private": true`。

### `portfolio_risk(window_days=250, benchmark="000300.SH")`

只读的历史风险计算（**只在用户要求诊断持仓时调用**），日 K 经本机数据网关 `market_bars`（`interval=1d`）取，一次一只、串行请求、间隔 ≥0.15 秒、单次最多 101 只（持仓 ≤100 + 基准），不跟随重定向、响应上限 4 MB。

- `window_days`：整数 60–500，默认 250；`benchmark` 白名单：`000300.SH`、`000001.SH`、`000905.SH`、`000852.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`，其他返回 `invalid_benchmark`。
- 股票/ETF 用 `adjust=qfq`（前复权），基准指数用 `adjust=none`（与旧实现取 `day` 的口径一致）；N = `window_days+5`。
- 权重 = 各持仓**最近收盘价 × 数量**，只计持仓、不含现金；取不到 K 线或有效 K 线 <60 根的持仓进入 `excluded`（带 `reason`），不参与任何风险数字，剩余持仓权重重新归一，并在 `warnings` 里给 `excluded_positions`。
- 组合日收益：以基准交易日为日历，按当前权重**固定回放**；持仓在自身无 K 线的交易日按前值填充（当日收益 0）；`annualized_vol_ratio` = 日收益样本标准差 × √252，`beta` = cov(组合, 基准)/var(基准)，`max_drawdown_ratio` = 回放净值的最大峰谷回撤（正数）。
- 基准同口径：`benchmark_annualized_vol_ratio`、`benchmark_max_drawdown_ratio`；`observations` 为实际收益日数。
- 集中度：`top1_weight_ratio`、`top5_weight_ratio`、`hhi`、`effective_n`（只计持仓）；宽基 ETF 另在 `broad_index_etfs` 列出并标 `broad_index_etf: true`。
- 暴露：`exposure_by_board`（主板 / 创业板 300、301 / 科创板 688、689 / 北交所 4、8、92 / ETF 基金 5 开头沪与 159、16 开头深）、`exposure_by_industry`（持仓 `industry`，缺省 `未标注`）、`asset_class`（`etf`/`stock`）。
- 每只持仓：`weight_ratio`、`bars`（窗口内有效 K 线根数）、`annualized_vol_ratio`、`max_drawdown_ratio`、`beta`、`corr_to_portfolio`（与组合日收益的相关系数）。
- `largest_pair_correlations`：两两收益相关系数最高的 ≤3 对（持仓 ≥2 只才有）。
- 另返回 `cash_share_ratio`（现金 / 含现金总资产，分母用参与风险计算的持仓市值 + 现金）、`as_of_bar_date`（最后一根共同 K 线的日期）、`window_days_requested`、`fetched_at`、`methodology`。所有比例字段为**小数**（0.2 = 20%）；输出浮点统一四舍五入到 8 位小数，避免出现长数字串。
- 空簿返回 `status: empty` 与提示；基准取不到返回 `benchmark_unavailable`，不给半个结果。返回带 `"private": true`。

## 隐私与安全

- 持仓是**敏感数据**，会进入模型上下文：只在用户主动要求时读取，**不常驻注入 `AGENTS.md`**，不写入其他任何地方，不外传给外部服务。
- 不存账号、资金账号、密码；不读凭据文件。
- 所有文本字段经过清洗，并拒绝：连续 ≥11 位数字（含 15 位资金账号）、`password/密码/token/api_key`、邮箱、身份证形态、`忽略以上指令` / `从现在起你必须…` / `ignore previous instructions` 等指令式短语。
- 网络只允许本机数据网关（`PORTFOLIO_GATEWAY_URL`，默认 `http://127.0.0.1:8768`，仅 loopback）；行情与日 K 都走 `POST /v1/call`，不回退直连上游。测试用本地假网关（`http.server`，随机端口）覆盖。不跟随重定向。
- 整个包不使用 `subprocess` / `exec` / `eval`。

## 已知限制

- 不含融资融券负债、不含多账户合并。
- 不含分红送转自动调整（成本与数量需用户按券商显示自行维护）。
- 不判断港股/美股/B 股；非 A 股股票一律拒绝；A 股 ETF/LOF 基金（沪 5 开头、深 159/16 开头）可作为持仓记录，但不做逐只成分穿透。
- 行情来自网关快照，停牌/退市/新股可能缺字段。
- 持仓上限 100 只；超过请拆分账户（本版本不支持多账户合并）。
- `portfolio_risk` 用的是**前复权日收盘价**，不是盘中价；不复权与复权口径可能产生差异。
- `portfolio_risk` 不含融资融券负债、不含分红再投资的单独现金流；停牌日按前值填充（当日收益 0），长期停牌会低估波动。
- 有效 K 线短于 60 根或取不到的持仓被排除，权重在剩余持仓上重新归一；风险数字**不计现金**的波动，现金只体现在 `cash_share_ratio`。
- 基准只支持任务书白名单里的 7 个 A 股指数；港股/美股指数不能作为基准。
- 宽基 ETF 的识别是代码清单 + 名称关键词的启发式，可能漏标或误标；不改变集中度计算，只额外列出。

## 手工成交记录

在现有持仓文件中以 UUID 记录已成交的买卖。用 portfolio_record_trade（默认预览）复核股数、价格、费用及成交后的余额，确认后用同一编号提交。用 portfolio_trade_history 分页读回记录。重复提交、同号冲突及超卖有回归测试。
