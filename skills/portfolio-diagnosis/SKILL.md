---
name: portfolio-diagnosis
description: "A 股持仓组合健康检查：对照用户画像看集中度、板块/行业/资产类别暴露、现金与风险匹配（年化波动率、Beta、最大回撤对宽基基准），最后给 2–3 个具体后续任务。Triggers on 诊断我的持仓、仓位是不是太集中、组合风险、portfolio diagnosis、portfolio review、am I too concentrated、how risky is my portfolio."
---

# 持仓诊断（Portfolio Diagnosis）

一分钟读完：用户持有什么，对照他自己说过的目标，差在哪里。每条发现都带数字和对照物；不讲课。

## 1. 输入

- **持仓**：`portfolio_get`。只在用户要求诊断持仓时读；返回带 `private: true`，是敏感数据。非空就用它，并记下 `as_of`、`updated_at`、`cash`（未录入不等于 0）。
- **空簿**：说明诊断需要持仓，请用户给券商导出的 CSV/表格文本、截图或口述（代码 + 数量即可）。用户只口头给一两只时，直接用 `portfolio_add_position(code, quantity, cost)` 写入，不必走整表导入。给整表时按 `portfolio_parse_csv` → `portfolio_import_preview` → 看 `added`/`changed`/`removed`/`warnings`：无警告且不删除已有持仓就直接 `portfolio_import_commit(confirm_token)` 并展示结果表；有警告或会删除/覆盖已有持仓时，先把这几点告诉用户再提交。不要替用户猜数量；`rejected` 行逐条说明。
- **画像**：新会话开头自动加载的 `AGENTS.md` 画像区块；需要最新值时用 `profile_get`（字段以 `packages/profile-mcp/README.md` 为准，不要编造字段）：`risk_level`、`investor_type`、`experience_years`、`horizon`、`markets`、`sectors`、`styles`、`asset_classes`、`constraints`、`output_format`、`language` 等。与当前对话冲突时以当前对话为准。缺项写明假设；**没有 `risk_level` 就只报风险数字，不给匹配结论**。
- **范围**：本簿只覆盖 A 股。遇到美股/港股持仓，直接说明**不支持**、不估算、不折算；B 股/基金代码同样说明不在簿内。
- **行业**：持仓的 `industry` 是用户导入时填的，可能为空。缺行业的重仓可用 `company_profile(code)` 核对所属行业与概念，在正文里说明，**不要写回持仓簿**。

## 2. 取数与计算（不要自己算）

先 `portfolio_valuation`：取现价、市值、权重、盈亏、集中度、涨跌停/停牌标记、`sellable_today` 与 `quote_time`；`warnings` 里 `stale_quote` 说明价格是上一时段最后值。`price_unavailable` 的持仓不计入汇总，必须在数据行点名，不得估一个价格补上。权重看 `weight`，含现金权重看 `weight_incl_cash`。

再 `portfolio_risk(window_days=250, benchmark="000300.SH")`（`window_days` 取 60–500，默认 250）：组合年化波动率 `annualized_vol_ratio`、`beta`、`max_drawdown_ratio`、基准同口径 `benchmark_annualized_vol_ratio`/`benchmark_max_drawdown_ratio`、`observations`、集中度 `top1_weight_ratio`/`top5_weight_ratio`/`hhi`/`effective_n`、`exposure_by_board`、`exposure_by_industry`、`asset_class`、`cash_share_ratio`，以及每只的 `weight_ratio, bars, annualized_vol_ratio, max_drawdown_ratio, beta, corr_to_portfolio`、`largest_pair_correlations`、`excluded`、`as_of_bar_date`、`methodology`。

- **小数口径**：所有比例字段都是小数（`0.2 = 20%`），展示时乘 100；不要把 0.2 再写成 0.2%。年化按 252 个交易日。
- **基准**：默认 `000300.SH`（沪深 300）；按组合主要暴露换用白名单里的指数：上证综指 `000001.SH`，中盘 `000905.SH`（中证 500），小盘 `000852.SH`（中证 1000），深市 `399001.SZ`（深证成指），创业板 `399006.SZ`，科创板 `000688.SH`（科创 50）。北交所没有对应基准，用 `000852.SH` 作小盘代理并在数据行说明这是代理。
- **excluded 逐条交代**：取不到 K 线或有效 K 线不足 60 根的持仓，逐条写代码、原因和它被排除后权重如何归一；不得用估计值补，不得把它算进风险数字。风险结论只覆盖剩余持仓，数据行写明覆盖率。
- **集中度两个口径**：都只计持仓、不含现金。全簿用 `portfolio_valuation` 的 `top1_weight`/`top5_weight`/`effective_n`；风险口径用 `portfolio_risk` 的 `*_ratio`/`effective_n`（已剔除 excluded 并归一）。两者不一致时先讲全簿，再说明风险口径剔除了谁；`price_unavailable` 的持仓也要点名。
- **不自己算**：不要用 K 线手算波动率、Beta、回撤或相关系数；工具失败或字段为 `null`/缺失时就说这项不可用，不拿近似值替代，也不把缺失当成 0。基准取不到（`benchmark_unavailable`）时不给半个结果。
- **不写文件**：持仓明细、成本价、数量只留在对话里；不把持仓内容发给搜索、抓取或其他外部服务。只有用户要求保存快照时，才在工作区写一份汇总（只写比例、日期、基准、排除项，不写代码、数量、成本价）；有上一份快照时先讲变化。

A 股特有：

- 涨停/跌停/停牌是流动性信息：`at_limit_up` 买不到、`at_limit_down` 卖不掉；涨跌停的持仓权重仍按市值计，但要提示“想调也调不动”。停牌持仓在 `portfolio_valuation` 里标 `price_unavailable`、不计入汇总，必须在数据行点名；风险工具若仍有停牌前 K 线，会把那段历史算进去，数据行要写停牌日期和这个口径差异。
- `sellable_today: false` 表示 T+1 当日不可卖；不要把它当成风险指标，只在需要调仓时提示。
- 涨跌幅按板块不同：主板 10%，科创板/创业板 20%，北交所 30%；ST 的涨跌幅另按板块规则，遇到名称带 ST 的持仓先核对当日 `limit_up_cny`/`limit_down_cny`，不凭记忆。科创板、北交所流动性与波动通常更大，给这两类持仓单列波动数字和板块权重，不拿主板口径安慰自己。
- ETF 按 ETF 本身计，不逐只穿透成分股；宽基指数 ETF（如跟踪沪深 300、中证 500、中证 1000 的 ETF）内部已分散，不参与“单票 >20%”判定；行业暴露仍按持仓 `industry` 或 `未标注` 计，不拆成成分股。

## 3. 判断匹配度

粗略分档，不是规则：

| 风险等级 | 年化波动率 | 可承受回撤 |
|---|---|---|
| conservative（保守） | 10% 以下 | 约 10% |
| moderate（稳健，对应画像 `balanced`） | 10%–15% | 约 20% |
| growth（成长） | 15%–22% | 约 30% |
| aggressive（进取） | 22% 以上 | 40% 或更多 |

画像的 `risk_level` 只有 `conservative`/`balanced`/`aggressive` 三个取值；上表的 moderate 对应 `balanced`，growth 是介于 `balanced` 与 `aggressive` 之间的读法。回撤按“一年实际回撤”和“波动率 ×2”两者中较大的读，因为平静的一年会低估坏年份。

值得写成发现的：单仓超过约 20%（宽基指数 ETF 除外）；有效 N 低于约 8；单行业超过约 40%（`未标注` 本身超过 40% 时按数据缺口说，不当作行业集中）；落在画像声明的 `markets`/`asset_classes` 之外的权重超过约 10%（按语义对照，不要求字面一致）；波动率或回撤超出档位；Beta 明显偏离 1（例如 0.7 以下或 1.3 以上）而画像没有要求；现金超过约 20%（仅在现金已录入时判断）。画像 `styles` 含 `income` 时，本簿没有股息率数据，把加权股息率标为缺口，不估算。

## 4. 写出

- **标题句**：一句话，说最重要的事，带数字。
- **发现**：3–5 条，最重要的在前；每条一个数字加对照物（画像、基准、或上面的阈值）。可以有一条说“没问题”，前提是它真的让人安心。
- **数据行**：价格与 `quote_time` 截至日期、K 线 `as_of_bar_date`、基准与 `observations`、`excluded` 逐条原因、`price_unavailable`、以及画像缺项时用的假设。说不支持或没取到的东西，绝不用估计值补。
- **下一步**：2–3 个具体后续任务，贴合画像的 `styles`、`horizon`、`sectors`。例如“压力测试占比 31% 的某重仓，假设回撤 40%”“在电力设备里找与现有持仓相关性低的替代”。可以附上你的看法和调整思路（例如把某仓从 32% 降到 20% 以下、用低相关资产替换），说清依据和反向情景；用户选中一个就当成新请求处理。

**输出控制**：约 250 字，一屏读完；最多一张小表；只打印发现需要的数字，不打印收益率序列；不贴成本价明细。投资者类型/经验用于措辞：`practitioner` 或 `experience_years ≥ 10` 直接给数字；`beginner` 或 `experience_years < 1` 每个术语解释一次。

## Chives 本地工具

已持仓、拟交易与模拟盘分开。portfolio_get 读取用户已确认持仓。新增或修订持仓沿用现有 portfolio 审批；记录成交日、股数、手续费和原始成交标识，重复导入时先核对该标识。研究关注理由和证据编号写入 Bot 记忆，交易记录沿用既有持仓/模拟盘接口。

用户要补录券商已经成交的交易时，通过 portfolio_record_trade 先预览，再携同一成交编号与确认参数提交；用 portfolio_trade_history 复核日期、方向、股数、成交价和手续费。成交日早于当前持仓快照时，先核对期初，避免把历史交易叠加到今天的余额。
