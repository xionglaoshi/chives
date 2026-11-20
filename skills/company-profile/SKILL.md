---
name: company-profile
description: "公司一页速览（A 股）：用一页 Markdown 说清公司做什么、怎么赚钱、财务与估值位置、股东与筹码、近期变化，配一张 matplotlib 股价图。触发词：一页速览、公司简介、公司快照、tear sheet、快速了解一家公司、profile。只做事实基线，不给评级或交易建议。"
---

# A 股公司一页速览（company-profile）

给只有三十秒的读者一页“这家公司是什么”。**四个板块都要满**：公司概览、业务与地位、财务摘要、股价与关键事实；再加来源与缺口。这是事实基线，不是观点：一旦开始论证 thesis、估值、买不买，就已经不是 profile，先交付基线，再交给 `stock-analysis`/`initiating-coverage`。

证据标签、来源分层、新鲜度与就绪姿态遵循 `research-conventions`。Excel/PPT 模板不再使用：交付 **Markdown 报告 + matplotlib 图**，路径遵守 T149 约定。

## 边界

- 不给评级、目标价、买卖建议、情景概率；只写“是什么”。
- 每个数字带报告期/抓取日期；金额单位统一（元/亿元，二选一），比例写百分数。
- 分部、市占率、员工数等公司自述标 `company claim`；第三方测算标 `street estimate`。
- 取不到就写“取不到”，不凭记忆补；缺口单独一段，不散落在正文。

## 第 1 步：锁定主体与用途

- 先用 `company_search(query)` 解析标准代码；同名、母子公司、A/H 多地上市要确认是哪一条上市线。
- 用途决定取舍：long-only（ durability、资本配置）、覆盖起步（先看什么）、指数成分（权重与被动资金）、尽调（合同、客户、流动性）。用户没说就按“覆盖起步”，并在交付时说明这是默认。
- 交付格式默认一页 Markdown；用户要两三页，就在一页基础上加“业务拆解/财务细节/股东与治理”附录，**不改变一页的结构**。

**完成判据**：代码、市场、上市线、报告期、用途五项写清；没有把同名公司搞混。

## 第 2 步：取数

| 需要 | 工具 | 口径/缺口 |
|---|---|---|
| 主营构成（产品/地区/行业） | `company_profile(code, by="product"/"region"/"industry", period)` | 收入、成本、毛利、占比；上游只给收入成本时代码计算并标 `computed` |
| 所属行业与概念 | `company_profile(code)` | 行业三级路径；概念说明是原文，`untrusted_text:true` |
| 指数成分 | `company_profile(index="沪深300", limit)` | 深证成指/创业板指无公开成分名单，返回 `unavailable` 时照写 |
| 三表与指标 | `company_financials(code, statement="indicators"/"income"/"balance"/"cashflow", periods=8)` | 金额元、比例百分数；至少取 3 年营收/归母/扣非/经营现金流/ROE/毛利率/资产负债率 |
| 估值 | `company_valuation(scope="stock", code, years=3)` | `current` 的 PE TTM/PB/PS/市值与 `percentile`；分位样本不足为 `null` |
| 行业估值 | `company_valuation(scope="industry", date)` | 只有静态 PE；口径不同，单列 |
| 一致预期 | `company_consensus(code)` | 卖方汇总，不是事实；写机构数与抓取日期 |
| 股价图 | `market_bars(code, interval="1d", adjust="qfq", limit=250)` | 前复权日线；存 `data/<主题>/prices.csv` 再画图 |
| 股东与筹码 | `company_holders(code, kind="top10"/"count"/"lockup")` | 十大流通股东按流通股本；户数按披露期；解禁股数与占比 |
| 北向 | `market_northbound(kind="holdings", code)` | 季度口径；没有每日持股 |
| 公告/新闻 | `company_announcements(code, start, end, limit)`、`news(kind="stock")` | 只取标题与日期；读原文用 `company_announcements(url=...)` |
| 公司自述/官网 | `web_fetch` 公开页面 | 只读公开页；引用写抓取日期 |

**冲突处理**：两个来源不一致时按“公告原文 > 交易所/巨潮 > 数据工具 > 卖方 > 媒体”选一个，并在来源行写明用了哪个、另一个是多少。用户给的文件与工具不一致时，先核对用户文件的日期与口径。

**完成判据**：四个板块所需字段都有来源或明确缺口；同一指标在全页只有一个值。

## 第 3 步：先写大纲，再画图

用真实数字把四块写成纯文本，**不留占位符**；填不出的条目就不写，进缺口段。确认后再生成 Markdown 与图。

### 四个板块

| 板块 | 内容 | 目标密度 |
|---|---|---|
| 1 公司概览 | 总部、成立年份、员工数、董事长/总经理、上市地与代码、总市值、所属行业、一个定义性数字 | 6–8 条 |
| 2 业务与地位 | 收入驱动、产品/分部占比、市占率（有来源才写）、护城河一句话、客户集中度、地区结构 | 6–8 条 |
| 3 财务摘要 | 营收、增速、归母、扣非、毛利率、ROE、经营现金流、资产负债率；最近 3 个年度 + 最近报告期 | 一张表，6–8 行 |
| 4 股价与关键事实 | 一年股价图、估值分位、股东户数变化、未来 90 天解禁、北向季度持股 | 图 + 5–7 条 |

**每条都要带数字**：“行业领先”改成“XX 市占率 18%（来源，日期）”；没有数字就不写这个形容词。

### 股价图（matplotlib）

```python
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

dates, closes = [], []
with open("data/000528-柳工/prices.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        dates.append(row["time"])
        closes.append(float(row["close"]))

fig, ax = plt.subplots(figsize=(7.2, 2.8), dpi=150)
ax.plot(range(len(closes)), closes, color="#1f4e79", linewidth=1.2)
ax.set_title("柳工（000528.SZ）前复权收盘价，近一年", fontsize=10)
ax.set_ylabel("元（前复权）", fontsize=9)
step = max(len(dates) // 6, 1)
ax.set_xticks(range(0, len(dates), step))
ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=0, fontsize=8)
ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
for side in ("top", "right"):
    ax.spines[side].set_visible(False)
fig.text(0.01, 0.01, "数据：market_bars，前复权；截至 " + dates[-1], fontsize=7, color="#666666")
fig.tight_layout()
fig.savefig("charts/000528-柳工/20261117_股价.png", bbox_inches="tight")
```

- 数据必须先落盘再画；不允许在脚本里手打价格。
- 图注写：标的、复权方式、时间范围、数据截止日、来源工具。
- 生成后用 `read_image` 打开检查标题、坐标轴、图例、首尾点；打不开就按失败处理，改用数据校验（最大值/最小值/样本数/首尾日期）并声明未经视觉检查。
- 图中若要标支撑/压力/目标价，必须写明“这是判断及其依据”，不能和数据点混在一起。

## 第 4 步：写 Markdown

```markdown
# <简称>（<代码>）一页速览
- 数据时间：行情 <日期>；财务 <报告期>；股东 <披露期>；北向 <季度末>
- 用途：覆盖起步（默认）；就绪姿态：screen-grade

## 1. 公司概览
## 2. 业务与地位
## 3. 财务摘要
| 指标 | FY-2 | FY-1 | 最新报告期 | 口径 |
|---|---|---|---|---|
## 4. 股价与关键事实
![股价](charts/<主题>/<日期>_股价.png)
- 估值：PE TTM X（3 年分位 Y%）；PB Z（分位 W%）
- 股东户数：…；未来 90 天解禁：…
## 5. 来源与缺口
- 来源：<工具/公告/日期>；口径：…
- 缺口：<项目>：试过 `<工具(参数)>`，返回 `status=…`；没有就写“无”
```

- 来源行写清工具名与日期，不写内部主机名或 URL。
- 估值标题按证据能支持的口径写：只有历史财务与 LTM 倍数时写“估值位置”，不要写“前瞻估值”。
- 一页放不下时，先删最不意外的条目，**不缩字号**；可以拆附录，但一页本身保持四块。

**完成判据**：四块都有内容；每个形容词有数字；图有来源与截止日；缺口是一段而不是空白表格；没有评级/目标价/买卖建议。

## 第 5 步：自检

- [ ] 主体、代码、上市线、报告期、用途确认。
- [ ] 四块密度达标，没有一块明显偏空。
- [ ] 每个数字有报告期或抓取日期，全页单位一致。
- [ ] 图由落盘数据生成，已 `read_image` 检查或声明未检查。
- [ ] 冲突已记录选择， prelim/调整后数字已标注。
- [ ] 缺口段列出试过的工具与返回状态。
- [ ] 没有评级、目标价、情景概率或交易建议。
- [ ] 文件在 `reports/<主题>/`，图在 `charts/<主题>/`，引用用相对工作目录路径。

## 紧凑版

要塞进备忘录或对话时，压成一段（≤200 字）：做什么与怎么赚钱、规模（营收/增速/毛利，带报告期）、影响判断的资产负债表与地位事实、估值位置与日期、最可能改变图景的一件事。同样遵守“没有来源的数字不写”。

以上为事实整理，不构成投资建议。<!-- Chives 已适配本文件。来源及许可见项目根目录 THIRD_PARTY_NOTICES.md。 -->
