---
name: okx-market
description: 用 web_fetch 直接 GET OKX V5 公开行情接口的索引：现货、合约、指数、资金费率、持仓量等端点路径、参数、已核对返回字段与可直接使用的完整 URL。仅作研究与信息整理，不需要也不使用任何密钥。
metadata:
  maintainer: Chives
---

# OKX 公开行情接口（web_fetch 索引）

## 使用边界

- 本 skill 仅用于研究与信息整理，**不构成投资建议**。
- **中国大陆境内禁止虚拟货币交易与相关金融服务**。2021-09-24 十部门通知明确：虚拟货币相关业务活动属于非法金融活动；境外虚拟货币交易所通过互联网向境内居民提供服务同样属于非法金融活动。来源见文末。
- 智能体不得为中国大陆用户提供加密资产交易建议或操作指引；不得调用任何下单、转账接口。
- 本 skill 只使用 OKX 的 **public / market data** 端点，全部无需认证、无需 API Key。不要在这里配置密钥，也不要把密钥写进 URL。
- 所有数值必须带抓取时间（`as_of`，UTC）。行情变化快，未标时间的数字不能当当前值。

## 怎么用：让 `web_fetch` 直接打开完整 URL

本项目的 `web_fetch` 接受一个 HTTP(S) URL，返回响应正文。OKX 这些端点都是 `GET`，参数直接拼在 query string 里，所以**不需要 Python、不需要安装依赖**：

```
web_fetch(url="https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT")
```

返回是 JSON 文本。判断成功看 `code`：`"0"` 为成功，`data` 是数组；非 `"0"` 时读 `msg`，不要猜数值。

```
{"code":"0","data":[{"instType":"SPOT","instId":"BTC-USDT","last":"78186.7",
 "open24h":"78141","high24h":"78866.5","low24h":"77600.5",
 "vol24h":"4301.84328439","volCcy24h":"336154440.232936149",
 "ts":"1793608603564","sodUtc0":"78342.6","sodUtc8":"77982.6", ...}],"msg":""}
```

HTTP 状态、限频与字段缺失都要如实记录；失败就写"未取得"，不要用上一次的缓存值替代。

## 参数格式

- **产品 ID（`instId`）**
  - 现货：`BTC-USDT`、`ETH-USDT`
  - 永续：`BTC-USDT-SWAP`、`ETH-USDT-SWAP`
  - 交割：`BTC-USDT-260327`（到期日 `YYMMDD`，以 `public/instruments` 返回的 `expTime` 为准）
  - 期权：`BTC-USD-260327-95000-C`（到期-行权价-C/P）
  - 指数：`BTC-USD`、`ETH-USD`
- **K 线周期（`bar`）**：`1m`、`3m`、`5m`、`15m`、`30m`、`1H`、`2H`、`4H`、`6H`、`12H`、`1D`、`1W`、`1M`（大小写敏感；以官方文档当前列表为准）
- **产品类型（`instType`）**：`SPOT`、`SWAP`、`FUTURES`、`OPTION`
- **时间戳**：毫秒 Unix 时间，字符串形式（例如 `1793608603564`）
- **数值类型**：价格、数量、费率在 JSON 里都是**字符串**，计算前要显式转 `float`/`Decimal`

## 端点索引

下表 13 个端点均已核对路径与参数；除全量 `/market/tickers`（响应过大，仅按文档与同结构端点核对）外，其余 12 个都用真实公开接口核对过返回字段（核对时间 2026-11-02T08:36Z）。每个端点的详细参数、字段与 `web_fetch` 示例见对应的 reference 文件。

| ID | 端点 | 用途 | 关键参数 | 详细文档 |
| ---: | :--- | :--- | :--- | :--- |
| 1 | `/market/ticker` | 单个产品最新行情 | `instId` | [单个行情](references/现货行情/单个行情.md) |
| 2 | `/market/tickers` | 某类产品全部行情 | `instType` | [批量行情](references/现货行情/批量行情.md) |
| 3 | `/market/candles` | K 线（OHLCV） | `instId`、`bar`、`after`/`before`、`limit` | [K线数据](references/现货行情/K线数据.md) |
| 4 | `/market/trades` | 最近成交明细 | `instId`、`limit` | [最近成交](references/现货行情/最近成交.md) |
| 5 | `/public/instruments` | 产品元数据（精度、面值） | `instType`、`instId` | [交易产品列表](references/现货行情/交易产品列表.md) |
| 6 | `/market/books` | 盘口深度 | `instId`、`sz` | [深度数据](references/现货行情/深度数据.md) |
| 7 | `/public/funding-rate` | 当前资金费率与结算时间 | `instId` | [资金费率](references/合约行情/资金费率.md) |
| 8 | `/public/funding-rate-history` | 历史资金费率 | `instId`、`after`/`before`、`limit` | [历史资金费率](references/合约行情/历史资金费率.md) |
| 9 | `/public/mark-price` | 标记价格 | `instType`、`instId` | [标记价格](references/合约行情/标记价格.md) |
| 10 | `/public/open-interest` | 持仓量 | `instType`、`instId` | [持仓量](references/合约行情/持仓量.md) |
| 11 | `/public/price-limit` | 合约限价 | `instId` | [限价](references/合约行情/限价.md) |
| 12 | `/market/index-tickers` | 指数行情 | `instId` 或 `quoteCcy` | [指数行情](references/指数行情/指数行情.md) |
| 13 | `/market/index-candles` | 指数 K 线 | `instId`、`bar`、`after`/`before`、`limit` | [指数K线](references/指数行情/指数K线.md) |

基础地址统一为 `https://www.okx.com/api/v5`。

## 已核对的限频与上限（避免无效请求）

以下为 2026-11-02 实测/官方文档口径，调用前仍应以官方文档为准：

- `/market/ticker`、`/market/tickers`、`/public/instruments`、`/public/open-interest`、`/public/mark-price`、`/public/price-limit`、`/market/index-tickers`：20 次/2s。
- `/market/candles`、`/market/books`：40 次/2s；`/market/candles` 单次 `limit` 最大 **300**，更早数据用 `after` 翻页。
- `/market/index-candles`：单次 `limit` 最大 **100**。
- `/market/trades`：单次 `limit` 最大 **500**。
- `/market/books`：`sz` 最大 **400**；实测 `sz=401` 返回 `{"code":"51000","msg":"Parameter sz error."}`。
- `/public/funding-rate-history`：10 次/2s，默认 `limit=100`。

## 资金费率的结算间隔

资金费率按**结算间隔**支付，间隔因合约而异，不是固定 8 小时。用当前费率响应里的 `fundingTime` 与 `prevFundingTime` 之差推导：

```
interval_ms = int(fundingTime) − int(prevFundingTime)
```

**不要**用 `rate × 3 × 365` 之类写死 3 次/日的年化；必须按实际间隔算 `rate × (365 × 24 × 3600 × 1000 / interval_ms)`。详见 `references/合约行情/资金费率.md`。

## Python 示例脚本（可选）

`scripts/` 下保留两个示例脚本：

- `scripts/market_data_example.py`：单产品行情、成交额排序、资金费率。
- `scripts/candle_data_example.py`：现货 K 线与指数 K 线。

**这两个脚本是可选的，只有本机已安装 Python 3 与 `requests` 时才可运行。** 在本项目里，优先使用上面的 `web_fetch` 直接 GET；脚本只用于本地批量拉取或离线复算，不作为 skill 的前置条件。脚本内的年化同样按接口间隔计算，不再写死 3 次/日。

## 数据日期与引用

- 每个结论写 `as_of`：例如 `2026-11-02T08:36Z`。
- 引用 OKX 数据时给出完整 URL 与字段名，便于复核。
- `ts` 是毫秒时间戳，转换时统一用 UTC，避免本地时区错位。

## 来源

- OKX V5 API 文档总入口：<https://www.okx.com/docs-v5/en/>
- 行情（Ticker/Tickers/Candles/Trades/Order book）：<https://www.okx.com/docs-v5/en/#order-book-trading-market-data>
- 公共数据（Instruments/Funding rate/Open interest/Mark price/Price limit）：<https://www.okx.com/docs-v5/en/#public-data-rest-api>
- 指数行情与指数 K 线：<https://www.okx.com/docs-v5/en/#public-data-rest-api-get-index-tickers>
- 境内监管依据（2021-09-24 十部门通知）：<https://www.spp.gov.cn/zdgz/202109/t20210924_530777.shtml>
