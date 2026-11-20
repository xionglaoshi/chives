---
name: perp-funding-basis
description: 永续合约资金费率与现货-期货基差的研究框架：费率机制、从接口字段推导结算间隔、年化换算、基差与现金套利现金流、跨所价差、持仓量×资金费率矩阵，以及手续费与保证金占用成本口径。仅用于研究与信息整理，不构成投资建议。
---

# 永续资金费率与基差（研究框架）

## 使用边界

- 本 skill 仅用于研究与信息整理，**不构成投资建议**。输出是"如何读数据、哪些假设需要披露"，不是交易结论。
- **中国大陆境内禁止虚拟货币交易与相关金融服务**。2021-09-24 十部门通知明确：虚拟货币相关业务活动属于非法金融活动；境外虚拟货币交易所通过互联网向境内居民提供服务同样属于非法金融活动。来源见文末。
- 智能体不得为中国大陆用户提供加密资产交易建议或操作指引，不得把本框架包装成策略推荐。
- 本 skill 不得调用任何下单、转账接口；不得用于实盘交易、资金划转或代客操作。
- 所有结论性数字必须带数据日期（`as_of`，精确到抓取时间）。接口取不到就写"取不到"，不得用旧值冒充当前值。

## 1. 资金费率机制

永续合约没有到期日，通过多空之间定期支付的**资金费率**把永续价格锚定到现货：

```
永续价格 > 现货价格 → 费率为正 → 多头付给空头
永续价格 < 现货价格 → 费率为负 → 空头付给多头
```

费率按**结算间隔**支付。间隔由交易所按合约设定，**不是固定 8 小时**：同一交易所的不同合约也可能不同（Binance 的 `/fapi/v1/fundingInfo` 明确返回 `fundingIntervalHours`，实测该列表中存在 1、4、8 三种取值）。因此任何"每 8 小时 × 3 × 365"的写法都只能用于特定合约的举例，不能当默认值。

OKX 的 `GET /api/v5/public/funding-rate` 返回 `fundingTime`（下次结算时间）与 `prevFundingTime`（上次结算时间），两者之差就是该合约当前的结算间隔；`nextFundingTime` 可用于交叉核对。实测 2026-11-02T08:36Z 抓取 BTC-USDT-SWAP：

```
fundingTime     = 1793635200000  (2026-11-02T16:00:00Z)
prevFundingTime = 1793606400000  (2026-11-02T08:00:00Z)
nextFundingTime = 1793664000000  (2026-11-03T00:00:00Z)
→ interval = 28,800,000 ms = 8 小时
```

同一响应里的 `interestRate` 为 `0.0001`（即 0.01%），可作为该合约的利率基准参照；读数时不要把 0.01% 当成"零"。费率与溢价的具体合成公式以 OKX 官方文档为准（见文末），本 skill 不复制公式细节，避免过期。

### 结算间隔与年化（代码）

```python
YEAR_MS = 365 * 24 * 60 * 60 * 1000


def settlement_interval_ms(funding: dict, history: list[dict] | None = None) -> int:
    """从接口字段推导结算间隔，不写死 8 小时。"""
    prev = funding.get("prevFundingTime")
    if prev not in (None, ""):
        return int(funding["fundingTime"]) - int(prev)
    nxt = funding.get("nextFundingTime")
    if nxt not in (None, ""):
        return int(nxt) - int(funding["fundingTime"])
    if history and len(history) >= 2:
        times = sorted(int(h["fundingTime"]) for h in history)
        return times[-1] - times[-2]
    raise ValueError("接口未返回可推导结算间隔的字段，需查交易所文档或合约说明")


def annualize(rate_per_interval: float, interval_ms: int) -> float:
    """把每期费率换算为简单年化（不复利）。rate 用小数，0.0001 = 0.01%。"""
    return rate_per_interval * (YEAR_MS / interval_ms)


# 例：0.0001/期，间隔 8 小时 → 0.0001 × (8760/8) = 0.1095 → 10.95%
```

年化口径必须写明是**简单年化**；若用复利，公式与结果都会不同，不能混用。

## 2. 费率读数分档

下表是**默认研究分档，未经实证校准**，只用于把原始费率翻译成文字，不是交易信号。年化列按 8 小时间隔计算（3 次/日）；换合约时必须用上一节的 `annualize()` 重算，不能沿用该列。

| 每期费率 | 8 小时间隔下的简单年化 | 读数 |
|---|---|---|
| > +0.05% | > +54.75% | 多头拥挤极端 |
| +0.02% ~ +0.05% | +21.9% ~ +54.75% | 多头偏拥挤 |
| +0.01% ~ +0.02% | +10.95% ~ +21.9% | 高于利率基准 |
| +0.005% ~ +0.01% | +5.5% ~ +10.95% | 接近基准 |
| -0.005% ~ +0.005% | -5.5% ~ +5.5% | 均衡 |
| -0.02% ~ -0.005% | -21.9% ~ -5.5% | 空头偏拥挤 |
| < -0.02% | < -21.9% | 空头拥挤，挤空风险上升 |

分档与代码共用同一组阈值（0.0005 / 0.0002 / 0.0001 / 0.00005 / -0.0002），避免"表里一个数、代码里另一个数"：

```python
def funding_regime(rates: list[float], interval_ms: int) -> dict:
    """rates 为最近若干期费率（小数），从旧到新。"""
    avg = sum(rates) / len(rates)
    last3 = rates[-3:]
    consecutive_positive = all(r > 0 for r in last3)
    consecutive_negative = all(r < 0 for r in last3)
    ann = annualize(avg, interval_ms)

    if avg > 0.0005:
        regime = "overheated_long"
    elif avg > 0.0002:
        regime = "elevated_long"
    elif avg > 0.0001:
        regime = "above_baseline"
    elif avg > 0.00005:
        regime = "near_baseline"
    elif avg >= -0.00005:
        regime = "balanced"
    elif avg >= -0.0002:
        regime = "mild_short"
    else:
        regime = "overheated_short"

    return {"regime": regime, "avg_rate": avg, "annualized": ann,
            "interval_ms": interval_ms,
            "consecutive_positive": consecutive_positive,
            "consecutive_negative": consecutive_negative,
            "note": "分档为待校准默认参数，不是交易信号"}
```

## 3. 现货-期货基差

**基差 = 期货价格 − 现货价格**；基差率 = 基差 / 现货价格。

```python
def annualized_basis(futures_price: float, spot_price: float, days_to_expiry: float) -> float:
    basis_pct = (futures_price - spot_price) / spot_price
    return basis_pct * (365 / days_to_expiry)


# 仅演示公式：现货 65,000、季度期货 66,500、剩余 45 天
# basis_pct = 2.3077%，annualized = 2.3077% × (365/45) = 18.72%
```

上述数字是**公式示例，不是行情**；真实分析必须用同一时点的现货与期货报价，并标注 `as_of`。

怎么读基差（不设硬阈值）：

- 正基差（contango）说明期货相对现货有溢价；把它与资金费率隐含的年化收益、无风险利率、以及套利成本放在一起比较，才有意义。
- 负基差（backwardation）说明期货折价；先排查交割/合约规则、借贷挤兑、交易所风险，再谈"情绪"。
- 季末、交割周、资金费率切换前后，基差会跳变；跨期比较必须用相同剩余期限或做期限调整。
- 具体分档（例如"年化超过某个固定值就算极端"）没有可靠来源，本 skill 不提供；要分档就用该资产自身历史分布的分位数，并写明样本期。

## 4. 现金套利（delta-neutral）的现金流

文献中描述的现金套利结构是：现货多头 + 等名义本金的永续空头，净方向敞口接近零，现金流主要来自资金费率。**这里只做现金流拆解，不提供任何开仓、平仓或调仓步骤。**

资金费率的计息名义本金会随标记价格漂移，且费率可能翻转，所以收益必须写成"毛收入 − 全部成本"：

```
net_pnl = Σ(funding_rate_i × notional_i)          # 毛资金费
        − spot_fees − perp_fees                    # 交易手续费
        − slippage                                 # 滑点
        − margin_cost                              # 保证金占用机会成本
        − borrow_cost                              # 如有借币/融资
        − other_costs                              # 提币/充币时间、税费、托管等

net_return = net_pnl / capital_deployed
net_annualized = net_return × (365 / holding_days)
```

`capital_deployed` 必须定义清楚：是"现货本金 + 保证金"，还是只看名义本金。两种口径的年化差很多，混用会虚高。

### 计入成本后的算例（假设值，需替换为真实费率）

假设：单腿名义本金 100,000；平均费率 +0.015%/期；间隔 8 小时（90 期/30 天）；现货 taker 0.10%/边；永续 taker 0.05%/边；滑点合计 0.02%/腿/边；保证金 33,333；保证金机会成本 4%/年。

```
毛资金费 = 0.00015 × 100,000 × 90            = 1,350.00
现货手续费 = 0.0010 × 100,000 × 2            =   200.00
永续手续费 = 0.0005 × 100,000 × 2            =   100.00
滑点 = 0.0002 × 100,000 × 4                  =    80.00
保证金占用 = 33,333 × 4% × 30/365            =   109.59
净收益 = 1,350 − 200 − 100 − 80 − 109.59     =   860.41
占用资本 = 100,000 + 33,333                  = 133,333
30 天净收益率 = 860.41 / 133,333             = 0.645%
简单年化 = 0.645% × 365/30                   = 7.85%
```

若费率均值降到 0，同样成本下净收益为 −489.59，30 天约 −0.367%。所以只看毛收入的年化数字会高估一倍以上；引用时必须说明是否扣费。

保证金需求不用固定杠杆倍数描述，而用**给定冲击下的强平距离**反推：

```
min_margin ≈ notional × (shock_pct + maintenance_margin_rate) + buffer
```

`shock_pct` 是假设的逆向价格冲击（例如 10%），`maintenance_margin_rate` 取交易所当前档位，`buffer` 是追加保证金缓冲。冲击假设必须写出来；未写冲击假设的固定杠杆倍数没有信息量。

**本算例未计入**（需要在真实分析中补）：标记价格与最新价差异、资金费名义本金随价格漂移、跨所充提时间与费用、税费、托管/借贷成本、极端行情下的强平滑点。

## 5. 跨所资金费率价差

同一资产在不同交易所的费率不同，价差本身是一个研究对象：

```python
rates = {"OKX": 0.00015, "Binance": 0.00020, "Bybit": 0.00025}  # 假设值，每期小数
spread = max(rates.values()) - min(rates.values())              # 0.00010
ann = annualize(spread, interval_ms=8 * 3600 * 1000)            # 10.95%（简单年化）
```

这 10.95% 是**毛价差**。净价差还要扣：四条腿的手续费与滑点、两个账户的保证金占用、跨所划转的时间与费用、以及价差收敛/翻转。不同交易所的结算间隔可能不同，必须分别用各自的 `interval_ms` 年化后再比较，不能把"每期"直接相减。

## 6. 资金费率作为情绪读数

| 价格行为 | 资金费率 | 常见解读 |
|---|---|---|
| 创新高 | 费率下降 | 多头未追高，上涨动能减弱 |
| 创新低 | 费率回升（负得少） | 空头未加码，下跌动能减弱 |
| 横盘 | 费率快速转正 | 杠杆在积累，波动风险上升 |
| 横盘 | 费率深度为负 | 空头持仓成本高，挤空风险上升 |

这些是**待检验的假设**，不是结论。原文中"连续 N 期后 70%/65%"的说法没有任何出处，已删除。要验证类似说法，按事件研究做：

1. 定义事件：连续 N 期费率超过阈值（N、阈值、间隔都写清楚）。
2. 定义结果窗口：事件后 1/3/7/14 天的收益分布。
3. 报告样本期、样本量、基准率（无条件同窗口收益）、命中率与置信区间。
4. 做样本外或至少分年份稳健性；不显著就写"未发现稳定关系"。

## 7. 持仓量 × 资金费率矩阵

```python
def oi_funding_matrix(oi_change_24h_pct: float, funding_rate: float) -> str:
    """阈值与第 2 节一致：0.0005 / 0.0002 / -0.0002。"""
    if oi_change_24h_pct > 5 and funding_rate > 0.0005:
        return "leveraged_long_buildup"
    if oi_change_24h_pct > 5 and funding_rate < -0.0002:
        return "leveraged_short_buildup"
    if oi_change_24h_pct < -5 and funding_rate > 0:
        return "long_deleveraging"
    if oi_change_24h_pct < -5 and funding_rate < 0:
        return "short_deleveraging"
    if abs(oi_change_24h_pct) < 2 and abs(funding_rate) < 0.00005:
        return "quiet"
    return "mixed"
```

`oi_change_24h_pct` 与 `funding_rate` 必须同一时点、同一合约；OI 用 `oiCcy`（币本位）还是 `oiUsd` 要写明，两者变化率不同。

## 8. 数据获取（用 `web_fetch` 直接 GET 公开接口）

无需密钥。用 `web_fetch` 打开下列完整 URL，并记录抓取时间：

| 用途 | 完整 URL |
|---|---|
| 当前资金费率（含结算时间） | `https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP` |
| 历史资金费率 | `https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=100` |
| 持仓量 | `https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP` |
| 永续行情 | `https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP` |
| 现货行情 | `https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT` |
| 合约面值/最小下单量等 | `https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP` |
| 标记价格 | `https://www.okx.com/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP` |

核对过的返回字段（2026-11-02T08:36Z 实测）：

- `funding-rate`：`fundingRate`、`fundingTime`、`prevFundingTime`、`nextFundingTime`、`settFundingRate`、`settState`、`interestRate`、`premium`、`minFundingRate`、`maxFundingRate`、`ts`。
- `funding-rate-history`：`fundingRate`、`realizedRate`、`fundingTime`、`method`、`formulaType`。
- `open-interest`：`oi`、`oiCcy`、`oiUsd`、`ts`（`oiUsd` 为实测返回）。
- `mark-price`：`markPx`、`ts`。

`web_fetch` 返回的是文本；如果接口报错，会看到 `code` 非 `"0"` 与 `msg`，应如实报告，不得猜测数值。

## 9. 输出模板

```
## 资金费率与基差 — [资产/合约]

- 数据日期（as_of）：YYYY-MM-DDTHH:MMZ
- 数据来源：OKX 公开接口 + 抓取时间
- 结算间隔：X 小时（由 fundingTime − prevFundingTime 推导）
- 年化口径：简单年化，每年 X 期

### 当前费率与读数
| 合约 | 每期费率 | 年化 | 分档 | 备注 |
|---|---|---|---|---|

### 基差
- 现货 / 永续 / 季度：...（同一时点）
- 年化基差：X%（剩余期限 N 天）
- 与资金费率隐含年化的差：X

### 现金套利现金流（如适用）
- 毛资金费：X
- 手续费/滑点/保证金成本：X / X / X
- 净收益与占用资本口径：X / X
- 未计入项：...

### 待检验假设与不确定性
- ...

本分析仅用于研究与信息整理，不构成投资建议。
```

## 10. 来源

- OKX 资金费率接口与字段：<https://www.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate>
- OKX 历史资金费率：<https://www.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate-history>
- OKX 持仓量：<https://www.okx.com/docs-v5/en/#public-data-rest-api-get-open-interest>
- Binance 结算间隔字段（实测含 1/4/8 小时）：<https://fapi.binance.com/fapi/v1/fundingInfo>
- 境内监管依据（2021-09-24 十部门通知）：<https://www.spp.gov.cn/zdgz/202109/t20210924_530777.shtml>
