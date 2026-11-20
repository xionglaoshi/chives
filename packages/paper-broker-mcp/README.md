# paper-broker MCP（模拟盘）

一个**只做模拟**的中国 A 股模拟盘 MCP 服务器，用于在 dsh 中演练下单流程与交易治理（审批、熔断、账本对账）。它不连接任何真实券商、交易所或生产账户，也没有任何真实下单能力。

- 入口：`python -m paper_broker_mcp --state-dir DIR [--test-mode --quote-file FILE]`（stdio MCP）
- Python 3.12；依赖仅 `mcp`、`requests`
- 日志只写 stderr，stdout 只承载 MCP 协议
- 初始资金固定 1,000,000.00 CNY；状态全部来自 `DIR/ledger.jsonl` 重放

## 安装与运行

```bash
cd packages/paper-broker-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m paper_broker_mcp --state-dir ../../runtime/paper
```

在 dsh 中通过 `overlays/paper-broker.cordis.yml` 接入，MCP server 名为 `paper_broker`，工具公开名为 `mcp__paper_broker__paper_*`。**这层 MCP 本身不做审批**；审批由 `overlays/trading-guard.cordis.yml` 在 dsh 工具管线里强制执行。

测试模式用固定行情文件，便于确定性回放：

```bash
.venv/bin/python -m paper_broker_mcp --state-dir /path/to/state --test-mode --quote-file quotes.json
```

`quotes.json` 形状：

```json
{"600000.SH": {"price": 10.0, "prev_close": 10.0, "limit_up": 11.0, "limit_down": 9.0, "time": "2026-11-03T10:00:00+08:00"}}
```

每次下单前重新读取该文件。`--test-mode` 下 `paper_place_order(as_of=...)` 决定交易日与时段；生产模式忽略 `as_of`，用真实北京时间。

## 工具

所有工具在文本内容里返回同一个 JSON 信封：

```json
{
  "ok": true,
  "source": "paper-broker",
  "simulated": true,
  "as_of": "2026-11-03T10:00:00+08:00",
  "status": "ready",
  "data": {}
}
```

- `paper_get_account()` → `initial_cash, cash, positions[{code,quantity,sellable_quantity,avg_cost}], market_value, equity, currency`
- `paper_place_order(code, side, quantity, price=None, as_of=None)` → `data.order{id,status,code,side,quantity,fill_price,gross,fees{commission,transfer_fee,stamp_duty},net_cash_change,reason}`
- `paper_list_orders(limit=50)` → `data.orders[]`（新到旧）
- `paper_verify_ledger()` → `data{ok,recomputed_cash,recomputed_positions,mismatches[]}`

下单被业务规则拒绝时仍是 `ok:true`、`order.status:"rejected"`，并给出 `error.code`：

| 拒绝码 | 含义 |
|---|---|
| `kill_switch` | 状态目录存在 `STOP` 文件 |
| `invalid_code` / `invalid_side` / `invalid_quantity` | 参数不合法 |
| `market_closed` | 北京时间周一至周五 09:30–11:30、13:00–15:00 之外 |
| `lot_size` | 买入非 100 股整数倍；科创板买入少于 200 股；卖出零股但不是一次性清空可卖数量 |
| `no_quote` | 行情取不到或字段不可用 |
| `price_limit` | 成交价（或限价）不在 `[limit_down, limit_up]` |
| `not_marketable` | 限价单当前不可成交（不挂单） |
| `no_position` | 卖出时没有该标的持仓 |
| `t_plus_1` | 卖出数量超过当日可卖数量（当天买入不可卖） |
| `insufficient_cash` | 成交金额 + 全部费用 > 现金 |

## 规则与费用

- 买入：主板 100 股整数倍；科创板（`688` 开头）最少 200 股，之后可 1 股递增。
- 卖出：可卖零股，但只能一次性清空该标的全部可卖数量。
- T+1：按 `as_of` 的日期，当天买入的股数当天不可卖。
- 市价单按行情价立即成交；限价买单要求限价 ≥ 行情价、限价卖单要求限价 ≤ 行情价，成交价一律取行情价。不撮合、不挂单、不排队。
- 费用（各项四舍五入到分）：
  - 佣金 = `max(5.00, 成交金额 × 0.025%)`，买卖双边
  - 过户费 = `成交金额 × 0.001%`，买卖双边
  - 印花税 = `成交金额 × 0.05%`，仅卖出
- 熔断：状态目录出现 `STOP` 文件后，后续下单一律 `kill_switch`，无需重启；删除后恢复。
- 账本：`ledger.jsonl` 只追加，每个成交/拒绝一行，含成交后现金与持仓。进程重启时重放账本恢复；`paper_verify_ledger` 独立重放并与当前状态比对。

行情来源：`--quote-file`（`--test-mode` 专用）；否则腾讯快照 `https://qt.gtimg.cn/q=sh600000`，字段 `3` 现价、`4` 昨收、`47` 涨停价、`48` 跌停价。取不到即 `no_quote`。

## 已知限制

- **不识别法定节假日**，只按周一至周五与时段判断；节假日会被当作交易日。
- **不处理停牌、除权除息、配股、退市、ST 特殊涨跌幅**；涨跌停价直接取行情源字段。
- **不撮合、不挂单**：限价单不可成交就立即拒绝，没有订单簿与排队。
- **T+1 只按日期字符串判断**，不区分交易日/自然日，也不做日终结算。
- 行情为免费公开接口，可能延迟、限流或字段缺失；不保证可用性。
- 账户是单进程单账本模型，不做多账户、资金划转、融资融券、期权或期货。
- **没有真实交易能力**：代码中不存在真实券商/交易所的 URL、SDK、凭据读取或下单接口。

## 测试

```bash
.venv/bin/python -m pytest -q
```
