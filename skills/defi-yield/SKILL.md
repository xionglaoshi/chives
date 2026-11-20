---
name: defi-yield
description: DeFi 收益的研究框架：借贷利率与利用率、LP 手续费收益、无常损失的 LP-vs-HODL 计算、质押与再质押、真实收益与排放依赖、脱锚/预言机/跨链桥风险，以及必须标注的数据日期。仅用于研究与信息整理，不构成投资建议。
---

# DeFi 收益分析（研究框架）

## 使用边界

- 本 skill 仅用于研究与信息整理，**不构成投资建议**。它提供计算口径与风险清单，不提供"该投哪个池子"的结论。
- **中国大陆境内禁止虚拟货币交易与相关金融服务**。2021-09-24 十部门通知明确：虚拟货币相关业务活动属于非法金融活动；境外虚拟货币交易所通过互联网向境内居民提供服务同样属于非法金融活动。来源见文末。
- 智能体不得为中国大陆用户提供加密资产交易建议或操作指引，不得输出"稳健/进取"配置建议或收益承诺。
- 本 skill 不得调用任何下单、转账接口；不得用于实盘交易、资金划转或代客操作。
- 所有 APY/TVL/价格必须带数据日期（`as_of`）与来源。DeFi 数据变化以小时计，过期快照不能当当前值。

## 1. 收益来源与口径

| 来源 | 机制 | 收益归谁 | 主要风险 |
|---|---|---|---|
| 借贷供给 | 借款人付息，按利用率定价 | 存款人 | 智能合约、清算、脱锚 |
| 借款成本 | 借款人付息 | 协议/存款人 | 利率曲线、流动性 |
| LP 手续费 | DEX 交易费按份额分配 | LP | 无常损失、MEV、被套利 |
| 质押 | 验证者/委托奖励 | 质押人 | 罚没、停机、流动性锁定 |
| 流动性挖矿 | 协议代币排放 | LP/存款人 | 排放稀释、代币价格下跌 |
| 再质押 | 共享安全服务（AVS）奖励 | 再质押人 | 额外罚没、合约叠加 |
| 积分 farming | 未来空投预期 | 参与者 | 完全投机、规则可变 |

**年化（APY）只在给定期限与复利假设下成立。** 报告必须写：数据日期、期限、是否复利、是否含代币激励、是否扣费。把不同口径的 APY 放在一张表里排序，是最常见的误导。

## 2. 借贷利率：先看利用率，不要用情绪阈值

浮动利率借贷的借款利率是**利用率**的函数，通常分段线性并带一个 kink：kink 以下斜率小，以上斜率大。Compound III 文档给出的形式是

```
Utilization = TotalBorrows / TotalSupply
BorrowRate = Base + SlopeLow × utilization                    (utilization ≤ kink)
BorrowRate = Base + SlopeLow × kink + SlopeHigh × (utilization − kink)   (utilization > kink)
```

来源见文末。因此"借款利率超过某个固定值就代表杠杆需求极端"这类阈值没有依据：同样高的利率可能来自高利用率，也可能来自协议参数调整。正确的做法是同时报告利用率、kink、以及利率曲线的当前参数。

```python
def lending_snapshot(total_borrows: float, total_supply: float,
                     base: float, slope_low: float, slope_high: float,
                     kink: float) -> dict:
    """只做快照与公式复算，不做多空判断。"""
    u = total_borrows / total_supply if total_supply else None
    if u is None:
        return {"utilization": None, "borrow_rate": None}
    if u <= kink:
        rate = base + slope_low * u
    else:
        rate = base + slope_low * kink + slope_high * (u - kink)
    return {"utilization": u, "borrow_rate": rate, "kink": kink}
```

协议层面只需列"机制"，不要写静态 TVL 区间。TVL 必须实时取：

| 协议 | 主要部署 | 机制 |
|---|---|---|
| Aave | 多链 | 池化借贷，按资产设置利率曲线 |
| Compound | 多链 | 池化借贷，利用率 + kink |
| Morpho | 多链 | 借贷匹配/金库，利率由市场与策展人参数决定 |
| MakerDAO / Sky | Ethereum 等 | CDP 铸造稳定币，稳定性费率治理 |
| Spark | Ethereum 等 | 借贷模块，参数由治理设定 |
| Kamino | Solana | 集中流动性 LP + 借贷 |

## 3. LP 收益与无常损失

### 3.1 无常损失公式（50/50 恒定乘积池）

```python
def impermanent_loss(price_ratio_change: float) -> float:
    """r = 新价格 / 旧价格；返回相对 HODL 的比值变化（小数）。"""
    r = price_ratio_change
    return 2 * (r ** 0.5) / (1 + r) - 1


# 算例（公式自检，不是行情；下列数值按百分比显示）：
# r = 1.25 (+25%) → -0.62%
# r = 1.50 (+50%) → -2.02%
# r = 2.00 (+100%) → -5.72%
# r = 3.00 (+200%) → -13.40%
# r = 0.50 (-50%) → -5.72%
# r = 0.25 (-75%) → -20.00%
```

这六个数是公式的直接结果，可用 `impermanent_loss()` 复算。注意 IL 是**相对 HODL 的路径结果**，不是"年化率"；价格回到原点时 IL 归零，但手续费与激励已经实现。

### 3.2 用 LP-vs-HODL 替代"年化无常损失"

```python
def lp_vs_hodl(entry_price: float, exit_price: float,
               eth_amount: float, usdc_amount: float) -> dict:
    """50/50 池：按恒定乘积重算退出时的 LP 组成，再与 HODL 比较。"""
    k = eth_amount * usdc_amount
    eth_lp = (k / exit_price) ** 0.5
    usdc_lp = (k * exit_price) ** 0.5
    lp_value = eth_lp * exit_price + usdc_lp
    hodl_value = eth_amount * exit_price + usdc_amount
    return {"lp_value": lp_value, "hodl_value": hodl_value,
            "lp_vs_hodl": lp_value / hodl_value - 1}


# 例：入场 ETH=2,000，1 ETH + 2,000 USDC；出场 ETH=3,000
# k = 2,000；ETH_lp = 0.8165，USDC_lp = 2,449.49
# LP = 4,898.98；HODL = 5,000.00；LP/HODL − 1 = −2.02%
```

持有期净结果（不再编造"年化 IL"）：

```
period_return = (LP 期末价值 + 期间手续费收入 + 期间激励收入 − 期初投入) / 期初投入
```

只有当期限明确（例如 30 天）时才做年化，并注明 "simple annualized, path-dependent, not a forecast"；跨不同价格路径的"年化 IL"没有定义，不应出现。

### 3.3 手续费收益率：分母必须是 TVL

"Fee APY / TVL" 是概念错误：APY 已经是"每单位 TVL 的收益率"，再除以 TVL 会得到没有量纲意义的数。正确指标是**手续费收入 / TVL**，并统一期限：

```
fee_yield_period = fees_usd_period / tvl_usd
fee_apr_simple  = fee_yield_period × (365 / period_days)
```

其中 `fees_usd_period` 是该池在同一期间分给 LP 的手续费（不是协议总收入，也不是交易量）。若只有 24 小时手续费，就写"按 24 小时外推，未年化验证"，并给出 TVL 的同日快照。交易量/TVL 只能作为活跃度参考，不能替代手续费收入。

### 3.4 LP 评估清单（不设"好/中/差"硬阈值）

- 手续费收益率与 TVL 的分子分母是否同期、同币种计价。
- 激励占毛收益的比例；激励按当前币价折算还是按 30 日均价。
- 交易量中有多少来自激励驱动的刷量。
- 价格区间与再平衡频率；集中流动性池的 IL 与 50/50 不同，不能套用上面的公式。
- 池子是否有暂停提现、预言机、管理密钥、升级权限。

## 4. 质押与再质押

ETH 质押收益率不是"网络越活跃越高"这么简单。协议的基础奖励按 `base_reward ∝ effective_balance / sqrt(total_staked)` 计算：总质押量越大，单位 ETH 的基础奖励越低（ethereum.org 的奖励与惩罚文档，来源见文末）。因此：

- 看到质押 APR 上升，先分清是**总质押量下降**、**MEV/优先费上升**、**客户端/relay 变化**，还是**统计口径变化**。
- 流动性质押代币（LST）的 APY 还要扣协议佣金，并承担 LST 与 ETH 的价差（脱锚）风险。
- 再质押收益 = 基础质押收益 + AVS 奖励 − 额外罚没风险 − 流动性折价；AVS 奖励随项目排放变化，不能外推。
- 不写具体 APY 数字。需要时实时取，并标注 `as_of`、是否含 MEV、是否扣佣金。

## 5. 收益可持续性：看资金来源，不贴标签

```python
def yield_sustainability(fee_revenue_usd: float, token_emission_usd: float,
                         total_yield_usd: float) -> dict:
    """拆成'费用支撑'与'排放支撑'两部分；不做单点结论。"""
    if total_yield_usd <= 0:
        return {"fee_share": None, "emission_share": None}
    return {
        "fee_share": fee_revenue_usd / total_yield_usd,
        "emission_share": token_emission_usd / total_yield_usd,
        "note": "费用口径可能含回购/一次性收入，需看协议披露",
    }
```

读数规则：

- `fee_share` 高不代表安全：费用可能来自一次性事件、回购、或关联方刷量。
- `emission_share` 高不代表欺诈：早期协议用排放换流动性是常见设计，但收益率会随排放下调而下降。
- 若费用与排放相加明显超过 100%，说明分子分母口径不一致（例如费用按协议口径、收益按池口径），应先统一口径而不是下结论。
- 不采用"庞氏"等定性标签；只报告"费用支撑比例"与"排放依赖比例"。

**不可持续收益的观察清单**（定性）：

1. 收益率远高于同类，但没有可解释的费用来源。
2. TVL 增长而协议收入不增长，代币价格下跌。
3. 排放持续下调，收益率逐月下降。
4. 治理提案频繁调整排放参数。
5. 多层收益叠加（借贷 + LP + 质押 + 积分），风险被复杂度掩盖。

## 6. 风险比较：展示原始分量，不做"调整后 APY"排名

用任意折扣系数（未审计、小 TVL、非以太坊各扣若干百分点）相加减，会制造假精度，并且重复计算风险。改为并排列出原始分量，由读者判断：

| 维度 | 要记录的事实 | 为什么重要 |
|---|---|---|
| 智能合约 | 是否审计、审计方与时间、是否可升级、管理密钥/多签阈值 | 审计不等于安全，升级权限可能改规则 |
| 脱锚 | 稳定币/ LST 的历史最低价、当前价差、赎回机制 | 脱锚会同时打击本金与抵押率 |
| 预言机 | 价格源、更新频率、异常处理、是否单点 | 预言机操纵可直接抽干池子 |
| 跨链桥 | 桥的类型（原生/第三方/多签）、历史事故 | 桥是常见攻击面 |
| 流动性 | TVL、24h 量、进出场滑点、提现限制 | TVL 小而 APY 高通常不可持续 |
| 治理 | 参数变更频率、时间锁、紧急权限 | 治理可改变收益与提现规则 |
| 对手方 | 托管方、策展人、RWA 发行方 | 链下信用风险无法用代码消除 |

输出时保留 `apy_gross`、`fee_apr`、`incentive_apr`、`il_period`、`tvl_usd`、`as_of` 等原始字段；不要合成单一"adjusted_apy"再排序。

## 7. 数据来源与取数纪律

| 来源 | 地址 | 用途 | 注意 |
|---|---|---|---|
| DeFiLlama 免费 API | <https://api-docs.defillama.com/>（`/pools`、`/chart/{pool}`） | 池子 APY/TVL、历史序列 | 必须记录请求时间与字段口径 |
| DeFiLlama 网站 | <https://defillama.com/yields> | 人工核对 | 站点有反爬，自动化访问可能被拒绝 |
| Compound 利率文档 | <https://docs.compound.xyz/interest-rates/> | 利用率与 kink 公式 | 参数以链上合约当前值为准 |
| ethereum.org 质押奖励 | <https://ethereum.org/developers/docs/consensus-mechanisms/pos/rewards-and-penalties/> | 基础奖励公式 | 总质押量变化会稀释 APR |
| 协议官方 dashboard/治理论坛 | 各协议官网 | 参数、审计、事件 | 一手来源优先 |

取数纪律：

- 每个数字带 `as_of`（UTC，精确到分钟）与来源 URL。
- API 返回失败、字段缺失、或口径不明时，写"未取得/未验证"，不要用旧值补齐。
- 同一张表里的 APY 必须同口径（是否含激励、是否复利、期限）。
- 历史回测用历史 TVL/APY 序列，不能用今天的 APY 乘一年。

## 8. 输出模板

```
## DeFi 收益快照 — [协议/池子]

- 数据日期（as_of）：YYYY-MM-DDTHH:MMZ
- 来源：DeFiLlama / 协议官网（URL）
- 口径：APY 是否含激励、是否复利、期限

### 原始分量
| 指标 | 数值 | 口径/来源 |
|---|---|---|
| TVL | | |
| 24h 手续费 / TVL | | |
| 毛 APY | | |
| 激励占比 | | |
| 期间 IL（若为 LP） | | 按实际价格路径计算 |

### 借贷市场（如适用）
| 资产 | 利用率 | kink | 借款利率 | 供给利率 |
|---|---|---|---|---|

### 风险事实
- 审计：
- 脱锚/价差：
- 预言机：
- 跨链桥：
- 提现限制：

### 情景概览（不是配置建议）
- 若排放下调 X%，毛 APY 约变为 Y%（写明假设）。
- 若标的价格变动 Z%，LP 相对 HODL 的差额约 W%（用第 3.2 节公式）。
- 主要不确定性：...

本分析仅用于研究与信息整理，不构成投资建议。
```

原文的"Conservative / Balanced / Aggressive"三档配置建议已删除：给档位就是给建议，而且"DeFi 借贷 = 稳健"忽略了智能合约、脱锚与预言机风险。

## 9. 来源

- 境内监管依据（2021-09-24 十部门通知）：<https://www.spp.gov.cn/zdgz/202109/t20210924_530777.shtml>
- Compound III 利率与利用率：<https://docs.compound.xyz/interest-rates/>
- Ethereum PoS 奖励与惩罚（`base_reward` 公式）：<https://ethereum.org/developers/docs/consensus-mechanisms/pos/rewards-and-penalties/>
- Ethereum 质押概览：<https://ethereum.org/en/staking/>
- DeFiLlama 免费 API 文档：<https://api-docs.defillama.com/>
