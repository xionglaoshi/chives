# A 股财报点评工作流

`earnings-analysis` 的展开参考。按阶段加载，不要求一次读完。证据合同（可定位引用、来源分层、四个缺席词、卖方预测声明）写在 `SKILL.md`，本文件只写每一步怎么落。

四个缺席词：**未发布**（公司尚未发布）、**未披露**（公司不披露）、**未提供**（材料里没有）、**取不到**（检索后仍无）。任何一格空着都换成一个词并说明原因。

## 第 1 步：固定报告期与披露状态

1. 写下今天日期，用 `company_earnings(kind="schedule", period, code="600519.SH")` 取该报告期的首次预约日、改期与实际披露日。报告期只接受 `YYYY-03-31`、`YYYY-06-30`、`YYYY-09-30`、`YYYY-12-31`。
2. 用 `company_announcements(code, start, end, category="年报")` 找报告；半年报、一季报、三季报分别换类别。`count` 是区间内总数，`truncated:true` 说明还有更多，缩小日期范围或类别。
3. 同一事件在公告列表里可能有“摘要”“正文”“更正”多条。**以更正后的正文为准**，把原公告日期写在旁边。
4. 预告与快报是独立公告：`company_announcements(code=..., category="业绩预告")` 找预告，`company_earnings(period, kind="express", code=...)` 找快报。不要用预告代替正式报告。

**红旗**：报告期是从今天日期推出来的；公告日与预约日对不上却没有解释；两篇公告写不同报告期；只有媒体转述、没有原文链接。

## 第 2 步：读原文，建立可定位的事实

| 材料 | 取法 | 记录什么 |
|---|---|---|
| 年度/半年度/季度报告 | `company_announcements` → `company_announcements(url=..., start_page, end_page, layout=True)` | 页码；三张表的表名；董事会报告里的经营讨论 |
| 业绩预告 | `company_announcements(code=..., category="业绩预告")` + `company_earnings(period=..., kind="forecast", code=...)` | 预告类型、变动区间、公告日、原文链接 |
| 业绩快报 | `company_earnings(kind="express", period=..., code=...)` | 营收、归母净利润、同比；标注“未经审计” |
| 交易所问询/回复 | `company_announcements(code=..., start=..., end=...)` 全类别，按标题关键词筛“问询/回复” | 问询日期、问题、回复口径；读不到原文就写“未读原文” |
| 互动易问答 | `news(kind="irm", code, limit)` | 提问与回复时间；第三方文本，只作线索 |

`company_announcements(url=...)` 是文字版 PDF 读取：`layout=True` 保留财务表格列对齐，读大表时用 `start_page`/`end_page` 分段，`max_chars` 控制返回量。扫描件没有文本层时返回 `unavailable` 并说明不支持 OCR；这是来源缺口，写清楚缺哪一页。

引用写法：`2026 年三季度报告，第 12 页，“合并利润表”`。只写“三季报”不算定位。

## 第 3 步：三表与指标

调用：`company_financials(code, statement="income"|"balance"|"cashflow"|"indicators", periods=8)`。

- `periods` 默认 8、最多 40；按报告期倒序返回，不要自己假设只返回 2 期。
- 金额字段是 `_yuan`（元），比率字段是 `_pct`（百分数），每股字段是 `_yuan`/股。未逐项确认的列不按名字猜单位。
- 归母净利润 `net_profit_yuan`；扣非归母净利润 `net_profit_deducted_yuan`；营业收入 `revenue_yuan`；经营现金流净额 `operating_cash_flow_yuan`；总股本与流通股用 `company_valuation(scope="stock").current.total_shares`/`float_shares`，单位为股。
- 单季值由累计值相减得到时，写明“本期累计 − 上期累计”，并检查相减后不为负或跳变。

## 第 4 步：实际 vs 预告 vs 一致预期

### 预告区间

`company_earnings(period, kind="forecast", code=...)` 返回每只股票一行。取 `change_pct_min`/`change_pct_max`/`change_pct_mid` 与 `forecast_mid_yuan` 或 `forecast_mid_eps_yuan`；原文在 `summary`/`reason`，标 `untrusted_text`。实际值落在区间内写“落在区间”，高于上限写“超上限”，低于下限写“低于下限”。预告类型（预增、扭亏、首亏等）只说明方向，不等于超预期。

### 一致预期

`company_consensus(code)`：

- `eps_forecast` 是按年份的每股收益预测（元/股），不是未来四个季度之和；引用时写“2026E EPS 一致预期”。
- `rating_counts` 是近六个月买入/增持/中性/减持/卖出家数；`report_count` 是研报数。两者口径不同，不互相替代。
- `eps_cross_check` 是另一套口径的年度最小/均值/最大值；与主口径相差超过 5% 时工具会在 `basis` 说明，**两个值都写，不取平均**。
- 无覆盖时返回 `unavailable` 或空列表：写“无卖方覆盖”，不写“预期为零”。

### 对照表

```
指标              实际      预告区间        一致预期      差异
营业收入          1,234.5亿  —              1,210.0亿     +2.0%
归母净利润        210.3亿    200–215亿       208.0亿       落在区间
扣非归母净利润    205.1亿    未发布          无覆盖        仅列实际
EPS（基本）       16.82元    —               16.64元       +0.18元
```

- 水平值差异用金额或百分比；比率差异用百分点或 bp。
- 预期为零、接近零或为负时不算百分比，只给绝对差。
- 一致预期是**卖方预测汇总，不是事实**：写覆盖机构数、预测年份、数据时间。

## 第 5 步：经营驱动与分部

1. 读报告“主营业务分行业、分产品、分地区情况”表，记录营业收入、营业成本、毛利率、同比与占比。
2. 挑 2–3 个承重驱动：收入增量主要来自哪里、毛利率变化由价格/成本/结构中的哪一项解释、下一期会不会延续。
3. 原文只有定性描述时保持定性，不把“稳健增长”翻译成具体百分比。
4. `company_profile(code, by="product", period)` 可作结构化交叉核对，但以报告原文为准。
5. 分部之和与合并报表不一致时，先说明“分部间抵销/其他”口径，再决定是否引用。

## 第 6 步：现金流质量

| 检查 | 算法 | 结论 |
|---|---|---|
| 经营现金流/归母净利润 | `operating_cash_flow_yuan` ÷ `net_profit_yuan` | 长期显著低于 1 要解释应收、存货或预收变化 |
| 收现比 | 销售商品、提供劳务收到的现金 ÷ 营业收入 | 与营收增速背离时查票据、预收与并表 |
| 应收与存货 | 期末余额与期初比，或同比 | 增速高于营收增速要写明原因 |
| 资本开支 | 购建固定资产等支付的现金 ÷ 折旧 | 扩张期与维护期的口径不同，分别说明 |

结论必须落到“印证”或“背离”，并指出具体科目与报告期；不写“现金流一般”这类无法复核的判断。

## 第 7 步：估值位置

1. `company_valuation(scope="stock", code, years=3)`：`current.pe_ttm`、`current.pb_mrq`、`current.total_mv_yuan`、`percentile.pe_ttm_pctile`、`percentile.pb_mrq_pctile`、`percentile.samples`、`percentile.window_years`。
2. 分位定义是“窗口内 ≤ 当前值的样本占比”。非正 PE 不计入；样本不足 60 个时返回 `null` 并在 `percentile.reasons` 给原因，照写。
3. 行业对照 `company_valuation(scope="industry", date=None, limit=40)`：只有静态 PE（加权/中位数/算术平均），与个股 TTM 不是同一口径，写入表头。
4. 指数对照 `company_valuation(scope="index", index="沪深300")`：10 年窗口，分位是本地计算。
5. 估值结论只能写“处于自身窗口的什么位置、相对行业是什么状态”，**不能写“低估所以买入”**。

## 第 8 步：公告后的评级、目标价与市场反应

- `company_consensus(code, limit=20)`：按日期倒序返回评级与目标价明细，字段含机构、评级、目标价（元）。同一机构本期与上期比较才写“上调/下调”；跨机构只写分布。
- `company_reports(code, limit=20)`：只有标题、机构、评级、日期与年度预测，**不读正文**；需要正文观点时写“研报正文取不到”。
- 股价反应：`market_bars(code="600519.SH", start, end, interval="1d")`。先看 `adjust` 复权口径；`volume_shares` 是股、`amount_yuan` 是元。基准用 `market_bars(code="000300.SH", start, end, interval="1d")`，取所有标的共同的首个交易日为基准日，超额收益 = 个股区间收益 − 基准区间收益。
- 资金：`market_fund_flow(scope="stock", code, days=20)` 的 `main_net_yuan` 是元、口径不同时看 `basis`；`market_trading_activity(kind="dragon_tiger", date, code)` 取上榜原因、净买与席位；`market_trading_activity(kind="margin", code, days=30)` 是 T+1 数据，融券余额只作风险信息。
- 公告日当天的涨跌受涨跌停限制影响时，写“受涨跌幅限制，价格未充分反映”，不用次日走势倒推当天信息。

## 交付前

按 `best-practices.md` 的三层门槛逐项过：硬失败、交付清单、判断门。任一项不过就改，不把“基本符合”写成交付。
