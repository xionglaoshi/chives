# 第 4 步：图表生成——详细流程

本文给出 `initiating-coverage` 第 4 步（图表生成）的分步做法。

## 步骤概览

**目的**：为报告生成 25–35 张专业财务图表。

**前置输入**：⚠️ 开工前验证
- **必需**：第 1 步的公司研究
  - 公司历史、里程碑（时间线图）
  - 管理层、组织架构（组织图）
  - 产品组合（产品图）
  - 客户分层（客户图）
  - 竞争格局（竞争定位图）
  - TAM 分析（市场空间图）
- **必需**：第 2 步的财务模型
  - 分产品/分地区收入数据
  - 利润率趋势
  - 情景对比数据
- **必需**：第 3 步的估值分析
  - DCF 敏感性表
  - 可比公司数据
  - 估值区间
- **必需**：行情数据
  - `market_bars` 取前复权日线（成交量单位手、价格单位元），先落 `data/<主题>/prices.csv`，图表脚本从 CSV 读，记录抓取日期。取全量日线，不要只取汇总窗口，保证 12–24 个月历史可用
  - 历史估值倍数：用 `market_bars` 的市值序列与 `company_financials` 的 EPS/每股净资产推导 PE/PB 带，或用 `company_valuation` 的当前分位做区间标注；推导方法写进图注

**⚠️ 关键：第 1、2、3 步未完成，不得开始本步**

本步依赖前三步的产出。缺任何一步，图表必然残缺。

**任一步未完成时**：立即停下，告知用户先完成哪一步。具体要求：
- 第 1 步：公司研究文档（供 9 张图）
- 第 2 步：覆盖 `SKILL.md` 模型清单第 2 步分区的财务模型（供 8 张图）
- 第 3 步：加入模型的估值分区（供 6 张图）
- 行情数据（供 2 张图）

不要用占位图，也不要因数据缺失跳过图表。

**输出**：25–35 张专业图表文件（PNG，300 DPI），放在 `charts/<主题>/`，附 `chart_index.txt`。

---

## 输入验证

**开工前逐项检查：**

### 第 1 步验证（公司研究）
- [ ] 第 1 步完成？（研究文档存在）
- [ ] 公司历史与里程碑已写？（供图 05、06）
- [ ] 管理层与组织架构已写？（供图 07）
- [ ] 产品组合已写细？（供图 08）
- [ ] 客户分层已分析？（供图 09）
- [ ] 竞争格局已画？（供图 16、17、18）
- [ ] TAM 测算完成？（供图 15）

### 第 2 步验证（财务模型）
- [ ] 第 2 步完成？（`model.py` 与 CSV 存在）
- [ ] 分产品收入可取？（供图 03 ⭐）
- [ ] 分地区收入可取？（供图 04 ⭐）
- [ ] 历史 + 预测财务完整？（供图 02、10、11、12）
- [ ] 情景分析（乐观/基准/悲观）完成？（供图 14）
- [ ] 经营指标可取？（供图 13）

### 第 3 步验证（估值）
- [ ] 第 3 步完成？（估值分区已加入模型）
- [ ] DCF 敏感性矩阵存在？（供图 28 ⭐）
- [ ] DCF 计算明细可取？（供图 29）
- [ ] 可比公司数据已收？（供图 30、31）
- [ ] 估值区间已算？（供图 32 ⭐）

### 行情数据验证
- [ ] 已用 `market_bars` 取日线并落 `data/<主题>/prices.csv`？（供图 01）
- [ ] 能取到历史估值数据？（可选，供图 34）

**任一验证失败时：**
- 缺第 1 步？→ 先完成第 1 步（公司研究）
- 缺第 2 步？→ 先完成第 2 步（财务建模）
- 缺第 3 步？→ 先完成第 3 步（估值分析）
- 缺行情？→ 用 `market_bars` 取价格序列、`company_valuation` 取估值分位，并记录抓取日期

---

## 图表要求：25 张必备 + 10 张可选

**重要**：第 5 步会把**所有已生成图**嵌入报告。报告需要高密度视觉内容（每 200–300 字一张图），所以图要覆盖全。

### 4 张必备图（不可省）⭐

这 4 张是关键可视化，必须存在：

1. **chart_03**：分产品/分部收入 - 堆叠面积图 ⭐
2. **chart_04**：分地区收入 - 堆叠柱状图 ⭐
3. **chart_28**：DCF 敏感性分析 - 双向热力图 ⭐
4. **chart_32**：估值足球场 - 横向条形图 ⭐

### 25 张必备图（完整集合）

25 张全部生成。每张在第 5 步都有明确用途：

**投资摘要（1 张）：**
- chart_01：股价表现（12–24 个月）

**财务表现（6 张）：**
- chart_02：营收增长轨迹
- chart_03：分产品收入 - 堆叠面积 ⭐ 必备
- chart_04：分地区收入 - 堆叠柱 ⭐ 必备
- chart_10：毛利率变化
- chart_11：EBITDA 利润率进展
- chart_12：自由现金流趋势

**公司 101（7 张）：**
- chart_05：公司概览/时间线
- chart_06：关键里程碑时间线
- chart_07：组织架构
- chart_08：产品组合概览
- chart_09：客户分层
- chart_15：市场空间演变（TAM）
- chart_16：竞争定位矩阵

**竞争与市场（2 张）：**
- chart_17：市场份额拆分
- chart_18：竞争对标

**情景分析（2 张）：**
- chart_13：经营指标面板
- chart_14：情景对比（乐观/基准/悲观）

**估值（7 张）：**
- chart_28：DCF 敏感性热力图 ⭐ 必备
- chart_29：DCF 估值瀑布
- chart_30：可比公司散点图
- chart_31：可比公司倍数对比
- chart_32：估值足球场 ⭐ 必备
- chart_33：目标价情景
- chart_34：历史估值倍数

初步覆盖或观察名单不出版目标价，因此省略需要目标价的估值图，首当其冲是 chart_33。

**合计：25 张必备**

### 10 张可选图（用于 30–35 张区间）

为更高视觉密度与叙事加这些（达到 26–35 张）：

- chart_19：获客趋势
- chart_20：单位经济性演变
- chart_21：产品路线图时间轴
- chart_22：地域扩张地图
- chart_23：研发投入趋势
- chart_24：销售费用效率
- chart_25：营运资本趋势
- chart_26：债务到期结构
- chart_27：股权结构
- chart_35：卖方目标价分布

**总数区间：25–35 张（25 必备 + 0–10 可选）**

---

## 必备图的数据来源映射

每张图的数据从哪来：

### 来自第 1 步（公司研究）——9 张
- chart_05：公司概览 → 第 1 步“公司概览”
- chart_06：关键里程碑 → 第 1 步“公司历史”
- chart_07：组织架构 → 第 1 步“管理层”
- chart_08：产品组合 → 第 1 步“产品与服务”
- chart_09：客户分层 → 第 1 步“客户与渠道”
- chart_15：市场空间演变 → 第 1 步“市场机会（TAM）”
- chart_16：竞争定位 → 第 1 步“竞争格局”
- chart_17：市场份额 → 第 1 步“竞争格局”
- chart_18：竞争对标 → 第 1 步“竞争格局”

### 来自第 2 步（财务模型）——8 张
- chart_02：营收增长 → `model_income_statement.csv` 营业收入行
- chart_03：分产品收入 ⭐ → `model_revenue_product.csv`
- chart_04：分地区收入 ⭐ → `model_revenue_geo.csv`
- chart_10：毛利率 → 利润表（毛利/营业收入）
- chart_11：EBITDA 利润率 → 利润表（EBITDA/营业收入）
- chart_12：自由现金流 → 现金流量表（经营现金流 − 资本开支）
- chart_13：经营指标 → 多份 CSV（利润表、现金流量表、经营数据）
- chart_14：情景对比 → `model_scenarios.csv`（乐观/基准/悲观）

### 来自第 3 步（估值）——6 张
- chart_28：DCF 敏感性 ⭐ → `model_sensitivity.csv`
- chart_29：DCF 瀑布 → `model_dcf.csv`（企业价值构成）
- chart_30：可比公司散点 → `model_comps.csv`
- chart_31：可比公司倍数 → `model_comps.csv`
- chart_32：估值足球场 ⭐ → `model_valuation_summary.csv`
- chart_33：目标价情景 → `model_valuation_summary.csv`（或从情景算）

### 来自行情——2 张
- chart_01：股价表现 → `market_bars`（前复权日线），字段 `date, open, high, low, close, volume`，按日期升序；基准指数同样取法
- chart_34：历史估值倍数 → `market_bars` + `company_financials` 推导 PE/PB 序列，或用 `company_valuation` 的当前分位；推导口径写进图注

**重要**：25 张必备图需要第 1、2、3 步全部完成，外加行情数据。

---

## 分步生成流程

### 第 1 步：准备环境

**依赖**（仓库已有则不装；不新增任务未要求的包）：
```bash
pip install matplotlib pandas numpy
```

**Python 脚本头：**
```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path

# 中文字体：按系统可用字体回退，负号正常显示
plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC",
    "Microsoft YaHei", "SimHei", "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

DPI = 300
FIGURE_WIDTH = 10
FIGURE_HEIGHT = 6
TITLE_FONT_SIZE = 14
AXIS_FONT_SIZE = 12
LABEL_FONT_SIZE = 10
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
           "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"]

THEME = "工程机械_柳工"          # 主题目录名
CHART_DIR = Path("charts") / THEME
DATA_DIR = Path("data") / THEME
CHART_DIR.mkdir(parents=True, exist_ok=True)
```

### 第 2 步：从模型与估值取数

#### A. 取收入数据
```python
def load_model(name: str) -> pd.DataFrame:
    """读取模型输出 CSV，第一列为科目名。"""
    return pd.read_csv(DATA_DIR / f"model_{name}.csv", index_col=0)

product = load_model("revenue_product")   # 行=产品/品类，列=年份
geo = load_model("revenue_geo")           # 行=地区，列=年份

year_labels = [str(column) for column in product.columns]
years = [int(label[:4]) for label in year_labels]
span = f"{year_labels[0]}-{year_labels[-1]}"

# 每个系列必须与年份列等长；各分项之和必须等于合计行
for frame in (product, geo):
    total = frame.loc["营业收入合计"]
    parts = frame.drop(index=[index for index in frame.index
                              if index.endswith("合计") or index.startswith("占总收入")
                              or index.startswith("同比")])
    for year in frame.columns:
        stacked = parts[year].sum()
        if abs(stacked - total[year]) > 0.005 * abs(total[year]):
            raise ValueError(f"{year}: 分项合计 {stacked:,.1f}，合计行 {total[year]:,.1f}")
```

#### B. 取利润率数据
```python
income = load_model("income_statement")
gross_margin = income.loc["毛利率 %"].astype(float)
ebitda_margin = income.loc["EBITDA 利润率 %"].astype(float)
cashflow = load_model("cashflow")
fcf_margin = cashflow.loc["FCF 利润率 %"].astype(float)
```

#### C. 取 DCF 敏感性数据
```python
sensitivity = load_model("sensitivity")           # 行=WACC，列=永续增长率
wacc_values = [float(index.rstrip("%")) for index in sensitivity.index]
terminal_growth = [float(column.rstrip("%")) for column in sensitivity.columns]
dcf_sensitivity = sensitivity.to_numpy(dtype=float)
```

#### D. 取估值区间
```python
summary = load_model("valuation_summary")
valuation_methods = ["DCF", "可比公司（NTM）", "可比交易"]
valuation_low = [float(summary.loc[method, "低"]) for method in valuation_methods]
valuation_high = [float(summary.loc[method, "高"]) for method in valuation_methods]
current_price = float(summary.loc["现价", "值"])
target_price = float(summary.loc["目标价", "值"])
```

### 第 3 步：生成必备图

#### 图 1：分产品收入 - 堆叠面积 ⭐ 必备

```python
def create_revenue_by_product_chart() -> None:
    """分产品收入堆叠面积图。"""
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT))

    series = product.drop(index=[index for index in product.index
                                 if index.endswith("合计") or index.startswith("占总收入")
                                 or index.startswith("同比")])
    ax.stackplot(years, *[series.loc[name].astype(float) for name in series.index],
                 labels=list(series.index),
                 colors=PALETTE[: len(series)],
                 alpha=0.85)

    ax.set_xlabel("年份", fontsize=AXIS_FONT_SIZE, fontweight="bold")
    ax.set_ylabel("营业收入（亿元）", fontsize=AXIS_FONT_SIZE, fontweight="bold")
    ax.set_title(f"图 3 - 分产品收入结构（{span}）",
                 fontsize=TITLE_FONT_SIZE, fontweight="bold", pad=20)
    ax.legend(loc="upper left", frameon=False, fontsize=LABEL_FONT_SIZE)
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    split_year = max(year for year in years if year <= 2025)
    ax.axvline(x=split_year, color="gray", linestyle="--", linewidth=1, alpha=0.5)
    ax.text(split_year + 0.1, ax.get_ylim()[1] * 0.95, "预测 →",
            fontsize=9, color="gray", ha="left")

    fig.text(0.12, 0.02, "来源：公司定期报告、我们的预测；数据日期 2026-11-17",
             fontsize=9, style="italic", color="gray")
    plt.tight_layout()
    plt.savefig(CHART_DIR / "chart_03_分产品收入_堆叠面积.png",
                dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close()
```

#### 图 2：分地区收入 - 堆叠柱 ⭐ 必备

```python
def create_revenue_by_geography_chart() -> None:
    """分地区收入堆叠柱状图。"""
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT))

    series = geo.drop(index=[index for index in geo.index
                             if index.endswith("合计") or index.startswith("占总收入")
                             or index.startswith("同比")])
    x = np.arange(len(year_labels))
    bottom = np.zeros(len(year_labels))
    for name, color in zip(series.index, PALETTE):
        values = series.loc[name].astype(float).to_numpy()
        ax.bar(x, values, 0.6, bottom=bottom, label=name, color=color)
        bottom = bottom + values

    ax.set_xlabel("年份", fontsize=AXIS_FONT_SIZE, fontweight="bold")
    ax.set_ylabel("营业收入（亿元）", fontsize=AXIS_FONT_SIZE, fontweight="bold")
    ax.set_title(f"图 4 - 分地区收入（{span}）",
                 fontsize=TITLE_FONT_SIZE, fontweight="bold", pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(year_labels, rotation=45, ha="right")
    ax.legend(loc="upper left", frameon=False, fontsize=LABEL_FONT_SIZE)
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.text(0.12, 0.02, "来源：公司定期报告、我们的预测；数据日期 2026-11-17",
             fontsize=9, style="italic", color="gray")
    plt.tight_layout()
    plt.savefig(CHART_DIR / "chart_04_分地区收入_堆叠柱.png",
                dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close()
```

#### 图 3：DCF 敏感性 - 热力图 ⭐ 必备

```python
def create_dcf_sensitivity_heatmap() -> None:
    """DCF 敏感性双向热力图。"""
    frame = pd.DataFrame(
        dcf_sensitivity,
        index=[f"{value}%" for value in wacc_values],
        columns=[f"{value}%" for value in terminal_growth],
    )
    fig, ax = plt.subplots(figsize=(8, 6))
    image = ax.imshow(dcf_sensitivity, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(terminal_growth)))
    ax.set_xticklabels(frame.columns)
    ax.set_yticks(range(len(wacc_values)))
    ax.set_yticklabels(frame.index)
    for row in range(dcf_sensitivity.shape[0]):
        for column in range(dcf_sensitivity.shape[1]):
            ax.text(column, row, f"{dcf_sensitivity[row, column]:.1f}",
                    ha="center", va="center", fontsize=9)
    fig.colorbar(image, ax=ax, label="每股价值（元）")

    ax.set_xlabel("永续增长率", fontsize=AXIS_FONT_SIZE, fontweight="bold")
    ax.set_ylabel("WACC", fontsize=AXIS_FONT_SIZE, fontweight="bold")
    ax.set_title("图 28 - DCF 敏感性分析（元/股）",
                 fontsize=TITLE_FONT_SIZE, fontweight="bold", pad=20)
    fig.text(0.12, 0.02, "来源：我们的预测；模型版本 2026-11-17",
             fontsize=9, style="italic", color="gray")
    plt.tight_layout()
    plt.savefig(CHART_DIR / "chart_28_dcf敏感性_热力图.png",
                dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close()
```

#### 图 4：估值足球场 ⭐ 必备

```python
def create_valuation_football_field() -> None:
    """估值足球场横向条形图。"""
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]

    for index, (method, low, high, color) in enumerate(
            zip(valuation_methods, valuation_low, valuation_high, colors)):
        ax.barh(index, high - low, left=low, height=0.6,
                color=color, alpha=0.75, label=method)
        ax.text(low - 0.2, index, f"{low:.1f}", va="center", ha="right", fontsize=10)
        ax.text(high + 0.2, index, f"{high:.1f}", va="center", ha="left", fontsize=10)

    ax.axvline(x=current_price, color="red", linestyle="--", linewidth=2,
               label=f"现价：{current_price:.1f} 元", alpha=0.7)
    ax.axvline(x=target_price, color="black", linestyle="-", linewidth=2,
               label=f"目标价：{target_price:.1f} 元")

    ax.set_yticks(np.arange(len(valuation_methods)))
    ax.set_yticklabels(valuation_methods, fontsize=11)
    ax.set_xlabel("每股价值（元）", fontsize=AXIS_FONT_SIZE, fontweight="bold")
    ax.set_title("图 32 - 估值足球场", fontsize=TITLE_FONT_SIZE,
                 fontweight="bold", pad=20)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", frameon=False, fontsize=9)

    fig.text(0.12, 0.02, "来源：我们的预测；数据日期 2026-11-17",
             fontsize=9, style="italic", color="gray")
    plt.tight_layout()
    plt.savefig(CHART_DIR / "chart_32_估值足球场.png",
                dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close()
```

### 第 4 步：生成其余必备图（25 张的其余 21 张）

**把必备清单里的其余图全部生成。** 每张在第 5 步都有明确用途。

#### 投资摘要（1 张）
```python
# chart_01：股价表现（12–24 个月）
# - 折线图：股价走势 vs 沪深 300 或所属行业指数
# - 数据来自 data/<主题>/prices.csv（由 market_bars 落盘，前复权）
# - 用于报告第 1 页
```

#### 财务表现（chart_03、chart_04 之外的 5 张）
```python
# chart_02：营收增长轨迹
# chart_10：毛利率变化
# chart_11：EBITDA 利润率进展
# chart_12：自由现金流趋势
# chart_14：情景对比（乐观/基准/悲观）
```

#### 公司 101（7 张）
```python
# chart_05：公司概览/时间线
# chart_06：关键里程碑时间线
# chart_07：组织架构
# chart_08：产品组合概览
# chart_09：客户分层
# chart_15：市场空间演变（TAM）
# chart_16：竞争定位矩阵
```

#### 竞争与市场（2 张）
```python
# chart_17：市场份额拆分
# chart_18：竞争对标
```

#### 情景分析（1 张）
```python
# chart_13：经营指标面板
```

#### 估值（chart_28、chart_32 之外的 5 张）
```python
# chart_29：DCF 估值瀑布
# chart_30：可比公司散点图
# chart_31：可比公司倍数对比
# chart_33：目标价情景
# chart_34：历史估值倍数
```

**所有图统一格式：**
- 300 DPI
- 统一配色（一套 3–5 个主色）
- 清晰标签、图例、中文标题
- 图号（如“图 5 - 公司时间线”）
- 底部来源与数据日期
- 单位写在轴标签或图注里

### 第 4B 步：生成可选图（26–35 张）

**可选**：从下列清单加 1–10 张，提高视觉密度：

```python
# chart_19：获客趋势
# chart_20：单位经济性演变
# chart_21：产品路线图时间轴
# chart_22：地域扩张地图
# chart_23：研发投入趋势
# chart_24：销售费用效率
# chart_25：营运资本趋势
# chart_26：债务到期结构
# chart_27：股权结构
# chart_35：卖方目标价分布
```

这些可选图提供额外叙事，帮助达到第 5 步“每 200–300 字一张图”的密度目标。

### 第 5 步：生成图索引

建一个文本文件登记全部图：

```python
def create_chart_index() -> None:
    """生成全部图的索引。"""
    required_charts = [
        ("chart_01_股价表现.png", "股价表现（12–24 个月）"),
        ("chart_02_营收增长轨迹.png", "营收增长轨迹"),
        ("chart_03_分产品收入_堆叠面积.png", "分产品收入 [必备]"),
        ("chart_04_分地区收入_堆叠柱.png", "分地区收入 [必备]"),
        ("chart_05_公司概览.png", "公司概览/时间线"),
        ("chart_06_关键里程碑.png", "关键里程碑时间线"),
        ("chart_07_组织架构.png", "组织架构"),
        ("chart_08_产品组合.png", "产品组合概览"),
        ("chart_09_客户分层.png", "客户分层"),
        ("chart_10_毛利率变化.png", "毛利率变化"),
        ("chart_11_EBITDA利润率.png", "EBITDA 利润率进展"),
        ("chart_12_自由现金流趋势.png", "自由现金流趋势"),
        ("chart_13_经营指标面板.png", "经营指标面板"),
        ("chart_14_情景对比.png", "情景对比（乐观/基准/悲观）"),
        ("chart_15_市场空间演变.png", "市场空间演变（TAM）"),
        ("chart_16_竞争定位.png", "竞争定位矩阵"),
        ("chart_17_市场份额.png", "市场份额拆分"),
        ("chart_18_竞争对标.png", "竞争对标"),
        ("chart_28_dcf敏感性_热力图.png", "DCF 敏感性热力图 [必备]"),
        ("chart_29_dcf估值瀑布.png", "DCF 估值瀑布"),
        ("chart_30_可比公司散点.png", "可比公司散点图"),
        ("chart_31_可比公司倍数.png", "可比公司倍数对比"),
        ("chart_32_估值足球场.png", "估值足球场 [必备]"),
        ("chart_33_目标价情景.png", "目标价情景"),
        ("chart_34_历史估值倍数.png", "历史估值倍数"),
    ]
    optional_charts = [
        ("chart_19_获客趋势.png", "获客趋势 [可选]"),
        ("chart_20_单位经济性.png", "单位经济性演变 [可选]"),
        ("chart_21_产品路线图.png", "产品路线图时间轴 [可选]"),
        ("chart_22_地域扩张.png", "地域扩张地图 [可选]"),
        ("chart_23_研发投入.png", "研发投入趋势 [可选]"),
        ("chart_24_销售费用效率.png", "销售费用效率 [可选]"),
        ("chart_25_营运资本.png", "营运资本趋势 [可选]"),
        ("chart_26_债务到期.png", "债务到期结构 [可选]"),
        ("chart_27_股权结构.png", "股权结构 [可选]"),
        ("chart_35_卖方目标价.png", "卖方目标价分布 [可选]"),
    ]

    lines = [
        "图表索引：[公司] 首次覆盖报告",
        "=" * 60,
        "",
        "4 张必备图（必须在）：",
        "- chart_03：分产品收入（堆叠面积）⭐",
        "- chart_04：分地区收入（堆叠柱）⭐",
        "- chart_28：DCF 敏感性（热力图）⭐",
        "- chart_32：估值足球场 ⭐",
        "",
        "25 张必备图：",
        *[f"  {name} - {title}" for name, title in required_charts],
        "",
        "10 张可选图（用于 26–35 张）：",
        *[f"  {name} - {title}" for name, title in optional_charts],
        "",
        "=" * 60,
        "注：第 5 步会嵌入全部已生成图（25–35 张），",
        "报告按每 200–300 字一张图的密度编排。",
    ]
    (CHART_DIR / "chart_index.txt").write_text("\n".join(lines), encoding="utf-8")
```

### 第 6 步：质量检查

**跑验证：**

```python
from pathlib import Path

def verify_charts() -> None:
    """验证全部图已生成。"""
    mandatory = [
        "chart_03_分产品收入_堆叠面积.png",
        "chart_04_分地区收入_堆叠柱.png",
        "chart_28_dcf敏感性_热力图.png",
        "chart_32_估值足球场.png",
    ]
    print("=" * 60)
    print("图表生成验证")
    print("=" * 60)

    print("\n1. 必备图：")
    all_present = True
    for name in mandatory:
        path = CHART_DIR / name
        if path.exists():
            print(f"   ✓ {name}（{path.stat().st_size / 1024:.1f} KB）")
        else:
            print(f"   ✗ 缺失：{name}")
            all_present = False

    chart_files = sorted(CHART_DIR.glob("chart_*.png"))
    print(f"\n2. 图总数：{len(chart_files)}（目标 25–35）")
    print(f"   状态：{'✓ 通过' if 25 <= len(chart_files) <= 35 else '⚠ 警告'}")

    print("\n3. 文件大小检查（300 DPI 通常 > 50KB）：")
    small = [path.name for path in chart_files[:5]
             if path.stat().st_size / 1024 < 50]
    for path in chart_files[:5]:
        print(f"   {path.name}：{path.stat().st_size / 1024:.1f} KB")
    print(f"   {'⚠ 可能有低分辨率文件' if small else '✓ 抽样文件大小正常'}")

    print("\n" + "=" * 60)
    if all_present and 25 <= len(chart_files) <= 35:
        print("✓ 验证通过，可进入第 5 步")
    else:
        print("✗ 验证失败，检查缺失的图")
    print("=" * 60)

verify_charts()
```

---

## 质量标准

### 视觉质量
- [ ] 高分辨率（至少 300 DPI）
- [ ] 专业配色（全套一致）
- [ ] 文字清晰可读（不小于 9pt）
- [ ] 比例正常，无拉伸变形
- [ ] 无像素化、无锯齿

### 数据准确性
- [ ] 数据与来源一致（模型 CSV、估值 CSV、行情）
- [ ] 单位与标签正确（亿元、%、元/股）
- [ ] 坐标轴范围合适
- [ ] 各图时间区间一致
- [ ] 计算已复核

### 格式质量
- [ ] 全套风格一致
- [ ] 图号连续
- [ ] 中文标题与图注清晰
- [ ] 每张图有来源与数据日期
- [ ] 外观专业

### 完整性
- [ ] 4 张必备图全部生成
- [ ] 总数 25–35 张
- [ ] 命名规范（chart_NN_描述.png）
- [ ] 图索引已生成
- [ ] 可直接嵌入 Markdown 报告

---

## 图表类型参考

### 什么时候用哪种图

**折线图**：时间序列趋势（收入、利润率、股价）

**堆叠面积**：分产品收入 ⭐、市场空间构成

**堆叠柱**：分地区收入 ⭐、季度拆分

**热力图**：DCF 敏感性 ⭐、相关性矩阵

**横向条形**：估值足球场 ⭐、同行排序

**瀑布图**：收入桥、利润率分析、DCF 构成

**散点/气泡**：增长 vs 估值、竞争定位

**2×2 矩阵**：竞争定位、产品组合

---

## 文件命名

**统一格式：**
```
chart_[编号]_[中文描述].png

示例：
chart_01_股价表现.png
chart_03_分产品收入_堆叠面积.png
chart_28_dcf敏感性_热力图.png
```

**按报告中的位置编号**，不按生成顺序。

---

## 常见问题

### 问题 1：分辨率低
**现象**：图有锯齿
**处理**：`plt.savefig()` 里确保 `dpi=300`

### 问题 2：文字被裁
**现象**：标签或标题超出边缘
**处理**：`plt.savefig()` 用 `bbox_inches="tight"`

### 问题 3：配色不专业
**现象**：颜色刺眼或难分辨
**处理**：用成熟调色板（Tableau10 或自定义企业色），全文一套

### 问题 4：标签重叠
**现象**：坐标轴标签挤在一起
**处理**：旋转标签（`rotation=45`）或减小字号

### 问题 5：留白过多
**现象**：图周围空白太大
**处理**：保存前 `plt.tight_layout()`

### 问题 6：中文变方块
**现象**：中文显示为方框
**处理**：设置 `font.sans-serif` 中文字体回退列表，并设 `axes.unicode_minus=False`

---

## 成功判据

成功的图表包应：
1. **含全部 4 张必备图**（已验证）⭐
   - chart_03：分产品收入
   - chart_04：分地区收入
   - chart_28：DCF 敏感性
   - chart_32：估值足球场
2. **至少 25 张必备图**（已验证）
3. **可选加 1–10 张**，总数 26–35
4. 全套专业风格一致
5. 高分辨率（300 DPI），可打印
6. 每张图有清晰标签、图例、中文标题
7. 图号与来源标注规范
8. 可直接嵌入 Markdown 报告
9. 覆盖全部关键财务指标与分析
10. 用视觉讲清文字分析的结论
11. 数据可追溯（模型/估值/行情）
12. 全部图与图索引放在 `charts/<主题>/`

**记住**：第 5 步会嵌入全部已生成图（25–35 张），按视觉密度编排。

---

## 输出文件

第 4 步完成后，交付物包括：

**25 张必备图（最低）：**
1. chart_01_股价表现.png
2. chart_02_营收增长轨迹.png
3. chart_03_分产品收入_堆叠面积.png ⭐ 必备
4. chart_04_分地区收入_堆叠柱.png ⭐ 必备
5. chart_05_公司概览.png
6. chart_06_关键里程碑.png
7. chart_07_组织架构.png
8. chart_08_产品组合.png
9. chart_09_客户分层.png
10. chart_10_毛利率变化.png
11. chart_11_EBITDA利润率.png
12. chart_12_自由现金流趋势.png
13. chart_13_经营指标面板.png
14. chart_14_情景对比.png
15. chart_15_市场空间演变.png
16. chart_16_竞争定位.png
17. chart_17_市场份额.png
18. chart_18_竞争对标.png
19–27. *可选图编号，如生成*
28. chart_28_dcf敏感性_热力图.png ⭐ 必备
29. chart_29_dcf估值瀑布.png
30. chart_30_可比公司散点.png
31. chart_31_可比公司倍数.png
32. chart_32_估值足球场.png ⭐ 必备
33. chart_33_目标价情景.png
34. chart_34_历史估值倍数.png
35. *可选图编号，如生成*

**10 张可选图（26–35 张）：**
- chart_19 至 chart_27、chart_35（如生成）

**图索引**（1 个文本文件）：
- `chart_index.txt`（列出全部图、描述与类别）

**全部图必须：**
- 300 DPI（打印质量）
- 宽 6–10 英寸（Markdown 嵌入的常用宽度）
- 白色背景
- PNG 格式（无损）
- 可直接嵌入 Markdown 报告

**最后一步：整理图表目录**

```
charts/<主题>/
├── chart_01_股价表现.png
├── chart_02_营收增长轨迹.png
├── chart_03_分产品收入_堆叠面积.png ⭐
├── chart_04_分地区收入_堆叠柱.png ⭐
├── chart_05_公司概览.png
├── ...（25–35 张）
├── chart_28_dcf敏感性_热力图.png ⭐
├── chart_32_估值足球场.png ⭐
├── chart_34_历史估值倍数.png
└── chart_index.txt
```

示例：`charts/工程机械_柳工/`

**为什么重要**：第 5 步会嵌入全部图（25–35 张）。报告需要视觉密度（每 200–300 字一张图），每张图要么服务某个分析章节，要么承担叙事与版面密度。
- 确认 25–35 张图都在
- 第 5 步从该目录取图

---

## 下一步

第 4 步完成后，图表目录将用于：
- **第 5 步（报告成文）**：从 `charts/<主题>/` 取图，按位置嵌入 Markdown 报告

4 张必备图对报告的估值与财务分析章节至关重要。

<!-- Chives 已适配本文件。来源及许可见skills/NOTICE.md。 -->
