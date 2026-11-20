# 第 2 步：财务建模——详细流程

本文给出 `initiating-coverage` 第 2 步（财务建模）的分步做法。

## 步骤概览

**目的**：取历史财务数据，建一套可重跑的 Python 财务模型，含预测与情景。

**前置输入**：⚠️ 开工前验证
- **必需**：能取到公司财务数据
  - A 股：`company_financials` 的三表，配合 `company_announcements` 的年报/半年报/季报与 `company_reports`
  - 或：用户提供的 3–5 年历史三表
- **可选**：第 1 步的公司研究，提供业务背景

**输出**：`scripts/<主题>/model.py`（纯 Python，可重跑）+ `data/<主题>/model_*.csv`，覆盖 `SKILL.md` 模型清单里第 2 步的分区。

---

## 输入验证

**开工前检查：**

**方式 A：直接取数（最常见）**
- [ ] 能用 `company_financials` 取到三表（按报告期）？
- [ ] 或能拿到用户提供的三表？
- [ ] 已确认金额单位（元/万元/亿元）与合并口径？

**方式 B：用户已给历史财务**
- [ ] 提供了历史财务文件？（CSV/Excel/文本均可）
- [ ] 含 3–5 年利润表、现金流量表、资产负债表？
- [ ] 数据干净、可直接用？

**可选背景：**
- [ ] 第 1 步公司研究已完成，理解业务？

**验证失败时**：停下，先拿到财务报表（定期报告或等价数据）再继续。

---

## 模型结构与写法

### 分区与可读性（替代 Excel 配色）

Excel 的颜色约定在这里换成代码约定，目的相同：让人一眼分清“输入”与“计算”。

- **顶部参数字典**：所有可改假设集中在一个 `ASSUMPTIONS` 字典，等价于蓝色输入
- **纯函数**：每个计算一个函数，输入输出明确，等价于黑色公式
- **跨模块引用**：只从上游函数取数，不复制粘贴，等价于绿色链接
- **检查函数**：勾稽失败抛异常或返回差额，等价于红色错误标记

### 写法标准

- 函数有类型标注
- 清晰的分节注释（`# --- 收入模型 ---`）
- 关键中间量输出到 CSV，可追溯
- 公式里不出现魔法数字（常量如 12 个月、365 天除外）
- 单位明确（元/万元/亿元），全模型只用一个
- 不引入任务未要求的依赖

### 公式最佳实践

- 所有数字从假设流出
- 改一个假设 → 全模型与全部 CSV 重算
- 无循环引用
- 关键参数有名字，不用位置下标
- 公式简单、可审计
- 复杂计算加一行注释说明口径

---

## 分步建模流程

### 第 1 步：取历史财务

**三表来源。** A 股用 `company_financials` 取利润表、资产负债表、现金流量表（按报告期，单位元；记录是合并还是母公司口径）。财报原文用 `company_announcements` 检索定期报告、`company_reports` 读索引，PDF 用 `web_fetch` 打开巨潮/交易所页面。工具没有模型需要的科目时，从年报/半年报原文摘取，标注来源与页码。

**A 股科目口径：**

1. **利润表（3–5 年）**
   - 营业总收入、营业收入
   - 营业成本、税金及附加
   - 销售费用、管理费用、研发费用、财务费用
   - 其他收益、投资收益、公允价值变动收益
   - 信用减值损失、资产减值损失、资产处置收益
   - 营业利润、营业外收支、利润总额
   - 所得税费用、净利润
   - 归母净利润、少数股东损益
   - 基本 EPS、稀释 EPS
   - 总股本、流通股本

2. **现金流量表（3–5 年）**
   - 经营活动：净利润起算，加回折旧摊销、股份支付、减值，减营运资本变化
   - 投资活动：购建固定资产/无形资产、投资支付、并购
   - 筹资活动：取得借款、偿还债务、增发/配股、分红
   - 现金及现金等价物净增加额、期初期末余额

3. **资产负债表（3–5 年）**
   - 流动资产：货币资金、交易性金融资产、应收票据及应收账款、应收款项融资、预付款项、存货、合同资产
   - 非流动资产：固定资产、在建工程、使用权资产、无形资产、商誉、递延所得税资产
   - 流动负债：短期借款、应付票据及应付账款、合同负债、应付职工薪酬、应交税费、一年内到期非流动负债
   - 非流动负债：长期借款、应付债券、租赁负债、递延收益
   - 所有者权益：股本、资本公积、库存股、其他综合收益、盈余公积、未分配利润
   - 少数股东权益
   - 负债和所有者权益总计

4. **历史指标**
   - 营收增速（同比）
   - 毛利率、EBITDA 利润率、营业利润率、净利率
   - 自由现金流（经营现金流 − 资本开支）
   - FCF 利润率
   - ROIC（近似：NOPAT / 投入资本）
   - 资产负债率、有息负债/EBITDA
   - 流动比率、速动比率
   - 应收账款周转天数、存货周转天数

5. **记录来源与备注（`data/<主题>/notes.md`）**
   - 报告期与披露日期
   - 一次性项目与调整
   - 非经常性损益与扣非口径差异
   - 分产品/分地区收入拆分（如披露）
   - 数据质量与局限

**用 CSV 落盘：**
```
data/<主题>/
  hist_income.csv
  hist_cashflow.csv
  hist_balance.csv
  hist_metrics.csv
  notes.md
```

**验证：**
- [ ] 三表 3–5 年齐全
- [ ] 三表勾稽：净利润与现金流起点一致，资产=负债+权益
- [ ] 关键指标计算正确
- [ ] CSV 能重新读入
- [ ] 来源已记录（报告期、公告编号、页码）

**历史基础完成，进入第 2 步。**

---

### 第 2 步：收入模型

**关键：这是模型中最重要、最细的部分。**

#### A. 分产品/品类收入（20–30 行）

建明细表（输出 `revenue_product.csv`）：
```
                        2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E
品类 A
  子产品 A1            XX      XX      XX      XX      XX      XX      XX      XX      XX
  子产品 A2            XX      XX      XX      XX      XX      XX      XX      XX      XX
  子产品 A3            XX      XX      XX      XX      XX      XX      XX      XX      XX
  品类 A 合计          XX      XX      XX      XX      XX      XX      XX      XX      XX
  占总收入 %           X%      X%      X%      X%      X%      X%      X%      X%      X%
  同比增速 %           -       X%      X%      X%      X%      X%      X%      X%      X%

品类 B
  [同样结构]

[对所有品类继续]

服务收入               XX      XX      XX      XX      XX      XX      XX      XX      XX
其他收入               XX      XX      XX      XX      XX      XX      XX      XX      XX

营业收入合计           XX      XX      XX      XX      XX      XX      XX      XX      XX
营收同比增速 %         -       X%      X%      X%      X%      X%      X%      X%      X%
```

**关键要求：**
- 每个品类有绝对收入（亿元）
- 每个品类算占总收入比例
- 每个品类算同比增速
- 子品类要细（不能只有 3–5 个大类）
- 展示结构迁移
- 所有预测链接到 `ASSUMPTIONS` 的参数

#### B. 分地区收入（15–20 行）

建明细表（输出 `revenue_geo.csv`）：
```
                        2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E
华东
  江苏                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  浙江                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  上海                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  华东合计              XX      XX      XX      XX      XX      XX      XX      XX      XX
  占总收入 %           X%      X%      X%      X%      X%      X%      X%      X%      X%
  同比增速 %           -       X%      X%      X%      X%      X%      X%      X%      X%

华南
  广东                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  其他华南              XX      XX      XX      XX      XX      XX      XX      XX      XX
  华南合计              XX      XX      XX      XX      XX      XX      XX      XX      XX
  占总收入 %           X%      X%      X%      X%      X%      X%      X%      X%      X%
  同比增速 %           -       X%      X%      X%      X%      X%      X%      X%      X%

华北
  [同样结构]

境外
  [同样结构]

营业收入合计           XX      XX      XX      XX      XX      XX      XX      XX      XX
```

**验证：**
- 分产品合计 = 分地区合计 = 营业收入合计
- 所有占比之和为 100%
- 增速计算正确

#### C. 分渠道收入（如适用）

```
                        2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E
直销                   XX      XX      XX      XX      XX      XX      XX      XX      XX
经销                   XX      XX      XX      XX      XX      XX      XX      XX      XX
电商/线上              XX      XX      XX      XX      XX      XX      XX      XX      XX
直营门店
  门店数               XX      XX      XX      XX      XX      XX      XX      XX      XX
  单店收入             XX      XX      XX      XX      XX      XX      XX      XX      XX
其他渠道               XX      XX      XX      XX      XX      XX      XX      XX      XX

营业收入合计           XX      XX      XX      XX      XX      XX      XX      XX      XX
```

### 第 3 步：经营费用建模

#### A. 营业成本
1. **拆成本构成**
   - 原材料
   - 人工
   - 制造费用/折旧
   - 运费与包装
   - 服务交付成本
   - 其他直接成本

2. **链接收入**
   - 成本占收入比
   - 逐年建模毛利率
   - 链接到 `ASSUMPTIONS`

#### B. 研发费用
```
研发费用              2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E
研发人数              XX      XX      XX      XX      XX      XX      XX      XX      XX
人均薪酬              XX      XX      XX      XX      XX      XX      XX      XX      XX
研发人工成本          XX      XX      XX      XX      XX      XX      XX      XX      XX
研发其他费用          XX      XX      XX      XX      XX      XX      XX      XX      XX
研发费用合计          XX      XX      XX      XX      XX      XX      XX      XX      XX
占收入 %              X%      X%      X%      X%      X%      X%      X%      X%      X%
```

#### C. 销售费用
```
销售费用              2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E
销售人员数            XX      XX      XX      XX      XX      XX      XX      XX      XX
人均薪酬              XX      XX      XX      XX      XX      XX      XX      XX      XX
销售人工成本          XX      XX      XX      XX      XX      XX      XX      XX      XX
市场推广费            XX      XX      XX      XX      XX      XX      XX      XX      XX
销售其他费用          XX      XX      XX      XX      XX      XX      XX      XX      XX
销售费用合计          XX      XX      XX      XX      XX      XX      XX      XX      XX
占收入 %              X%      X%      X%      X%      X%      X%      X%      X%      X%
```

#### D. 管理费用
```
管理费用              2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E
管理人数              XX      XX      XX      XX      XX      XX      XX      XX      XX
人均薪酬              XX      XX      XX      XX      XX      XX      XX      XX      XX
管理人工成本          XX      XX      XX      XX      XX      XX      XX      XX      XX
管理其他费用          XX      XX      XX      XX      XX      XX      XX      XX      XX
管理费用合计          XX      XX      XX      XX      XX      XX      XX      XX      XX
占收入 %              X%      X%      X%      X%      X%      X%      X%      X%      X%
```

#### E. 折旧摊销
- 链接资本开支计划
- 按 `ASSUMPTIONS` 的折旧率计算
- 算年度折旧摊销

### 第 4 步：建利润表

**建 40–50 行的完整利润表（输出 `income_statement.csv`）：**

```
利润表                  2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E

营业收入
[链接收入模型]
营业收入合计            XX      XX      XX      XX      XX      XX      XX      XX      XX
  同比增速 %            -       X%      X%      X%      X%      X%      X%      X%      X%

营业成本
[链接成本明细]
营业成本合计            XX      XX      XX      XX      XX      XX      XX      XX      XX

毛利                    XX      XX      XX      XX      XX      XX      XX      XX      XX
  毛利率 %              X%      X%      X%      X%      X%      X%      X%      X%      X%

税金及附加              XX      XX      XX      XX      XX      XX      XX      XX      XX
销售费用                XX      XX      XX      XX      XX      XX      XX      XX      XX
  占收入 %              X%      X%      X%      X%      X%      X%      X%      X%      X%
管理费用                XX      XX      XX      XX      XX      XX      XX      XX      XX
  占收入 %              X%      X%      X%      X%      X%      X%      X%      X%      X%
研发费用                XX      XX      XX      XX      XX      XX      XX      XX      XX
  占收入 %              X%      X%      X%      X%      X%      X%      X%      X%      X%
财务费用                XX      XX      XX      XX      XX      XX      XX      XX      XX

营业利润                XX      XX      XX      XX      XX      XX      XX      XX      XX
  营业利润率 %          X%      X%      X%      X%      X%      X%      X%      X%      X%

其他收益                XX      XX      XX      XX      XX      XX      XX      XX      XX
投资收益                XX      XX      XX      XX      XX      XX      XX      XX      XX
公允价值变动收益        XX      XX      XX      XX      XX      XX      XX      XX      XX
信用减值损失           (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
资产减值损失           (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
资产处置收益            XX      XX      XX      XX      XX      XX      XX      XX      XX
营业外收支              XX      XX      XX      XX      XX      XX      XX      XX      XX

利润总额                XX      XX      XX      XX      XX      XX      XX      XX      XX

所得税费用             (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
  实际税率 %            X%      X%      X%      X%      X%      X%      X%      X%      X%

净利润                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  净利率 %              X%      X%      X%      X%      X%      X%      X%      X%      X%
少数股东损益            XX      XX      XX      XX      XX      XX      XX      XX      XX
归母净利润              XX      XX      XX      XX      XX      XX      XX      XX      XX
  归母净利率 %          X%      X%      X%      X%      X%      X%      X%      X%      X%

EBITDA                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  EBITDA 利润率 %       X%      X%      X%      X%      X%      X%      X%      X%      X%

总股本（亿股）          XX      XX      XX      XX      XX      XX      XX      XX      XX
稀释股本（亿股）        XX      XX      XX      XX      XX      XX      XX      XX      XX

基本 EPS（元）          X.XX    X.XX    X.XX    X.XX    X.XX    X.XX    X.XX    X.XX    X.XX
稀释 EPS（元）          X.XX    X.XX    X.XX    X.XX    X.XX    X.XX    X.XX    X.XX    X.XX
```

### 第 5 步：建现金流量表

```
现金流量表              2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E

经营活动
净利润                  XX      XX      XX      XX      XX      XX      XX      XX      XX
调整项：
  折旧摊销              XX      XX      XX      XX      XX      XX      XX      XX      XX
  股份支付              XX      XX      XX      XX      XX      XX      XX      XX      XX
  减值损失              XX      XX      XX      XX      XX      XX      XX      XX      XX
  其他非现金项          XX      XX      XX      XX      XX      XX      XX      XX      XX

营运资本变化：
  应收账款              (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
  存货                  (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
  应付账款              XX      XX      XX      XX      XX      XX      XX      XX      XX
  合同负债              XX      XX      XX      XX      XX      XX      XX      XX      XX
  其他营运资本          (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)

经营活动现金流          XX      XX      XX      XX      XX      XX      XX      XX      XX

投资活动
资本开支               (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
并购支出               (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
其他投资               XX      XX      XX      XX      XX      XX      XX      XX      XX

投资活动现金流         (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)

自由现金流              XX      XX      XX      XX      XX      XX      XX      XX      XX
  FCF 利润率 %          X%      X%      X%      X%      X%      X%      X%      X%      X%

筹资活动
取得借款               XX      XX      XX      XX      XX      XX      XX      XX      XX
偿还债务               (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
增发/配股              XX      XX      XX      XX      XX      XX      XX      XX      XX
分红                   (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
其他筹资               XX      XX      XX      XX      XX      XX      XX      XX      XX

筹资活动现金流          XX      XX      XX      XX      XX      XX      XX      XX      XX

现金净增加额            XX      XX      XX      XX      XX      XX      XX      XX      XX

期初现金                XX      XX      XX      XX      XX      XX      XX      XX      XX
期末现金                XX      XX      XX      XX      XX      XX      XX      XX      XX
```

### 第 6 步：建资产负债表

建 35–45 行的完整资产负债表：

```
资产负债表              2021A   2022A   2023A   2024A   2025A   2026E   2027E   2028E   2029E

资产
流动资产：
  货币资金              XX      XX      XX      XX      XX      XX      XX      XX      XX
  交易性金融资产        XX      XX      XX      XX      XX      XX      XX      XX      XX
  应收票据及应收账款    XX      XX      XX      XX      XX      XX      XX      XX      XX
  预付款项              XX      XX      XX      XX      XX      XX      XX      XX      XX
  存货                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  合同资产              XX      XX      XX      XX      XX      XX      XX      XX      XX
  其他流动资产          XX      XX      XX      XX      XX      XX      XX      XX      XX
流动资产合计            XX      XX      XX      XX      XX      XX      XX      XX      XX

非流动资产：
  固定资产原值          XX      XX      XX      XX      XX      XX      XX      XX      XX
  累计折旧              (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
  固定资产净值          XX      XX      XX      XX      XX      XX      XX      XX      XX
  在建工程              XX      XX      XX      XX      XX      XX      XX      XX      XX
  使用权资产            XX      XX      XX      XX      XX      XX      XX      XX      XX
  无形资产              XX      XX      XX      XX      XX      XX      XX      XX      XX
  商誉                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  其他非流动资产        XX      XX      XX      XX      XX      XX      XX      XX      XX
非流动资产合计          XX      XX      XX      XX      XX      XX      XX      XX      XX

资产总计                XX      XX      XX      XX      XX      XX      XX      XX      XX

负债
流动负债：
  短期借款              XX      XX      XX      XX      XX      XX      XX      XX      XX
  应付票据及应付账款    XX      XX      XX      XX      XX      XX      XX      XX      XX
  合同负债              XX      XX      XX      XX      XX      XX      XX      XX      XX
  应付职工薪酬          XX      XX      XX      XX      XX      XX      XX      XX      XX
  应交税费              XX      XX      XX      XX      XX      XX      XX      XX      XX
  一年内到期非流动负债  XX      XX      XX      XX      XX      XX      XX      XX      XX
  其他流动负债          XX      XX      XX      XX      XX      XX      XX      XX      XX
流动负债合计            XX      XX      XX      XX      XX      XX      XX      XX      XX

非流动负债：
  长期借款              XX      XX      XX      XX      XX      XX      XX      XX      XX
  应付债券              XX      XX      XX      XX      XX      XX      XX      XX      XX
  租赁负债              XX      XX      XX      XX      XX      XX      XX      XX      XX
  递延所得税负债        XX      XX      XX      XX      XX      XX      XX      XX      XX
  其他非流动负债        XX      XX      XX      XX      XX      XX      XX      XX      XX
非流动负债合计          XX      XX      XX      XX      XX      XX      XX      XX      XX

负债合计                XX      XX      XX      XX      XX      XX      XX      XX      XX

所有者权益
  股本                  XX      XX      XX      XX      XX      XX      XX      XX      XX
  资本公积              XX      XX      XX      XX      XX      XX      XX      XX      XX
  库存股                (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)    (XX)
  其他综合收益          XX      XX      XX      XX      XX      XX      XX      XX      XX
  盈余公积              XX      XX      XX      XX      XX      XX      XX      XX      XX
  未分配利润            XX      XX      XX      XX      XX      XX      XX      XX      XX
归母所有者权益合计      XX      XX      XX      XX      XX      XX      XX      XX      XX
少数股东权益            XX      XX      XX      XX      XX      XX      XX      XX      XX
所有者权益合计          XX      XX      XX      XX      XX      XX      XX      XX      XX

负债和所有者权益总计    XX      XX      XX      XX      XX      XX      XX      XX      XX

勾稽检查                OK      OK      OK      OK      OK      OK      OK      OK      OK
```

**勾稽检查：**
- 每年资产总计 = 负债和所有者权益总计
- 不平时返回差额并高亮，不能静默通过

### 第 7 步：建 DCF 输入

为第 3 步准备输入：

```
DCF 输入                2026E   2027E   2028E   2029E   2030E

EBIT                    XX      XX      XX      XX      XX
税率                    X%      X%      X%      X%      X%
NOPAT                   XX      XX      XX      XX      XX

加：折旧摊销            XX      XX      XX      XX      XX
减：资本开支            (XX)    (XX)    (XX)    (XX)    (XX)
减：营运资本增加        (XX)    (XX)    (XX)    (XX)    (XX)

无杠杆自由现金流        XX      XX      XX      XX      XX

永续年指标：
  2030E 营业收入        X,XXX
  2030E EBITDA          XXX
  2030E EBIT            XXX
  2030E 无杠杆自由现金流 XXX
```

### 第 8 步：建情景

建三个参数不同的情景：

#### 情景假设表
```
假设                          乐观        基准        悲观
营收 CAGR（2026–2030）        XX%         XX%         XX%
2030E 毛利率                  XX%         XX%         XX%
2030E EBITDA 利润率           XX%         XX%         XX%
资本开支占收入                X%          X%          X%
[加入其他关键假设]
```

#### 情景输出表
```
指标                          乐观        基准        悲观
2030E 营业收入（亿元）        X,XXX       X,XXX       X,XXX
2030E EBITDA（亿元）          XXX         XXX         XXX
2030E EBITDA 利润率           XX%         XX%         XX%
2030E 归母净利润（亿元）      XXX         XXX         XXX
2030E EPS（元）               X.XX        X.XX        X.XX
2030E 自由现金流（亿元）      XXX         XXX         XXX
2030E FCF 利润率              XX%         XX%         XX%

2026–2030 累计自由现金流（亿元） XXX      XXX         XXX
```

**写清情景理由：**
- 乐观：描述乐观但可实现的假设
- 基准：描述最可能的情景
- 悲观：描述下行风险与触发条件

### 第 9 步：质量检查

**验证模型完整性：**
1. [ ] 抽查所有计算公式
2. [ ] 改一个假设 → 模型与 CSV 正确更新
3. [ ] 测试情景切换
4. [ ] 输入参数、计算、引用分区清晰
5. [ ] 每年的资产负债表都平
6. [ ] 无循环引用（脚本会报错）
7. [ ] 预测里没有临时硬编码数字
8. [ ] 所有跨模块引用可用
9. [ ] 收入合计在各表之间对得上
10. [ ] 检查输出格式与可读性

---

## 质量标准

### 模型完整性
- 所有公式在模块间正确链接
- 预测中没有硬编码数字（`ASSUMPTIONS` 除外）
- 无循环引用
- 每年资产负债表平
- 情景切换正常

### 完整性
- 覆盖 `SKILL.md` 模型清单第 2 步的全部分区
- 利润表 40–50 行
- 收入模型产品拆分 20–30 行
- 收入模型地区拆分 15–20 行
- 完整现金流量表与资产负债表
- 乐观/基准/悲观三情景齐全

### 可读与规范
- 输入、公式、引用分区一致
- 标题与标签清晰
- 关键参数有名字
- 单位标注清楚（元 vs 万元 vs 亿元）
- 函数有类型标注与文档字符串

### 文档
- 假设有理由（`ASSUMPTIONS` 旁的注释）
- 数据来源写在 `notes.md` 或函数注释
- 复杂计算有说明
- 方法有描述

---

## 文件命名

模型的保存位置：

`scripts/<主题>/model.py`

数据输出：

`data/<主题>/model_*.csv`

示例：`scripts/工程机械_柳工/model.py`、`data/工程机械_柳工/model_income_statement.csv`

---

## 成功判据

成功的财务模型应：
1. 覆盖 `SKILL.md` 模型清单第 2 步的全部分区
2. 完全动态（改假设 → 模型更新）
3. 预测中没有硬编码数字
4. 含详细收入拆分（产品 20–30 行、地区 15–20 行）
5. 利润表 40–50 行
6. 含乐观/基准/悲观三情景
7. 命名与分区清晰
8. 勾稽正确（资产负债表、现金流）
9. 可审计、易跟随
10. 用正确的 FCF 计算支撑估值分析

---

## 常见模型类型——特殊考虑

### 成长科技/软件服务
- 关注订阅收入增长与续费率
- 按产品线、地区建模
- 研发与销售费用投入大
- 盈利路径时间表
- 单位经济性（获客成本回收期）

### 消费/零售
- 按品类与渠道拆收入
- 门店数与同店增长（如适用）
- 存货周转与营运资本
- 履约成本
- 获客与复购

### 制造/工业
- 产能利用率
- 原材料成本与价格
- 毛利率桥（量/价/结构/成本）
- 资本开支重
- 营运资本周期

### 金融/地产（适用时）
- 净息差、不良率、拨备覆盖（银行）
- 合同负债与预收（地产）
- 杠杆与融资成本
- 监管指标约束

---

## 下一步

第 2 步完成后，模型将用于：
- **第 3 步（估值）**：DCF 输入、预测财务
- **第 4 步（图表）**：收入趋势、利润率图、情景对比的数据
- **第 5 步（报告成文）**：报告表格与分析用的财务数据

<!-- Chives 已适配本文件。来源及许可见项目根目录 THIRD_PARTY_NOTICES.md。 -->
