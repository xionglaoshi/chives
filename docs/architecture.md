# Chives 数据与规则架构（目标架构）

> 2026-11-17 与用户确认。新任务、重构与评审都以本文为准；与现状不一致的地方列在第 6 节，按第 7 节逐步迁移。

## 1. 分层

```
agent（bot）
  │ 调用 MCP                                   ▲ 唤醒 / 通知
  ▼                                            │
[数据 MCP]      [盯盘 MCP]          [策略 MCP（strategy_id）]
   │                │                       │
   │        Chives 服务端：归属、权限（bot 配置）、触发唤醒、通知、面板 API
   │                │                       │
   │        规则层 1 盯盘  ◄──价位/条件──  规则层 2 策略（主升浪 …）
   │                │ 实时                  │ 收盘后 + 历史
   ▼                ▼                       ▼
数据层：实时快照（网关 cn-market-gateway，缓存）  +  历史库（cn-daily-store，全 A 日线）
   │
外部数据源（限流、熔断、多源合并、字段统一；不使用东财 push2 / push2his / push2ex）
```

## 2. 各层职责与边界

| 层 | 组件 | 只做 | 不做 |
|---|---|---|---|
| 外部源 | 腾讯、新浪、同花顺、交易所、巨潮等公开接口 | — | — |
| 数据层·实时 | `packages/cn-market-gateway`（127.0.0.1:8868 + `cn-market-mcp`） | 唯一对外取数的地方：限流、熔断、单飞、缓存、多源回退、字段统一、口径说明（envelope） | 业务规则、告警判断 |
| 数据层·历史 | `packages/cn-daily-store`（`runtime/marketdata/daily.sqlite`） | 全 A 日线（未复权 + 复权因子）、交易日历、名称历史、涨停判定；每日增量；质量检查 | 业务规则 |
| 规则层 1 盯盘 | `packages/cn-watch`（个股条件，8865）、`packages/market-watch` 的规则部分（大盘/板块/情绪 R1–R6） | 确定性条件评估、状态、去重、冷却；产生触发事件 | 自己对外取数（只读数据层） |
| 规则层 2 策略 | `packages/surge-engine`（主升浪），以后的策略同构 | 确定性状态机：池、轮次、事件、分数；回测与实盘同一套代码；只用当日及之前数据 | 自己对外取数；调用模型 |
| 编排 | `apps/server`（Chives 服务端） | bot 归属与权限（`bot.yaml`：`mcp`、`skills`、`panels`）、把规则层事件变成 bot 任务（唤醒）、通知、面板数据接口 | 计算规则 |
| MCP | `cn-market-mcp`（数据）、`chives-mcp` 的 `watch_plan_*`（盯盘，经服务端）、策略 MCP（统一接口，参数带 `strategy_id`） | 把下层能力暴露给 agent；工具描述与错误信息为中文口径语言 | 业务逻辑 |
| agent | `bots/*` | 解读、复核、合成、与用户对话；需要确定结论时调用规则 MCP | 自己算规则分数 |

## 3. 硬性规则

1. **只有数据层访问外部数据源。** 规则层、服务端、MCP、bot 一律经数据层取数（bot 的网页搜索/抓取类工具除外，它们不是行情数据）。
2. **不使用东财 push2 / push2his / push2ex**（含 AKShare `_spot_em` 一类函数）。
3. 规则层是确定性代码：同样输入得到同样输出；可回放、可单测；不调用模型。
4. 策略不使用未来数据：任一日的结果只依赖当日及之前的数据，用"截断回放 = 全量回放"测试保证。
5. 事件向上走服务端：规则层产生的触发/策略事件由 Chives 服务端决定唤醒哪个 bot；bot 再决定是否 `notify_user`。规则层不直接通知用户。
6. 权限按 bot 配置：bot 能用哪些 MCP、skill、面板、策略，由 `bot.yaml` 决定，服务端与 MCP 两边都校验。

## 4. 策略层统一接口（规则层 2）

每个策略实现同一组读取接口，策略 MCP 只做一个、按 `strategy_id` 路由：

| 接口 | 说明 |
|---|---|
| `pools(strategy_id, date?)` | 当日各池排序（含分项与状态） |
| `round(strategy_id, code, date?)` | 某股当前/最近轮次的全部事件与分项 |
| `events(strategy_id, start, end, kinds?)` | 事件流 |
| `annotate(strategy_id, code, round_id)` | K 线标注数据/图 |
| `levels(strategy_id, code)` | 可交给盯盘的价位（突破线、支撑、MA10 等） |
| `backtest(strategy_id, params)` | 回测任务（异步）与结果 |

策略事件（例如"新进优先级一""主升浪池移出"）以统一格式推给服务端，服务端按 bot 配置唤醒订阅了该策略的 bot。

## 5. 面板与界面
右侧面板由 `bot.yaml` 的 `panels` 决定（`market`、`portfolio`、`watches`，策略面板为 `strategy:<id>`），数据经服务端面板 API 取自数据层/规则层。

## 6. 现状与目标的差距（2026-11-17）

| # | 现状 | 目标 |
|---|---|---|
| 1 | `cn-watch` 直接请求腾讯行情 `qt.gtimg.cn` | 只经网关 `market_quote` 取行情 |
| 2 | `market-watch` 既对外取数（含东财 push2 主机）又做规则；网关把它当首选数据源（引擎路径），层次倒置 | 取数并入数据层（只保留非 push2 源）；`market-watch` 只保留 R1–R6 规则，经网关取数；网关不再依赖 `market-watch` |
| 3 | `portfolio-mcp` 直接请求腾讯日 K 与行情 | 经数据层（网关或历史库） |
| 4 | 历史日线库在建（T154） | 作为数据层·历史部分，规则层 2 只从这里读 |
| 5 | 策略层与策略 MCP 未建 | 主升浪按第 4 节接口实现，并接入服务端唤醒与面板 |

## 7. 迁移顺序
1. T154 历史库 → T155 主升浪引擎（规则层 2）。
2. T156：差距 1、3（cn-watch、portfolio-mcp 改经网关取数）。
3. T157：差距 2（网关去掉对 market-watch 的依赖；market-watch 去掉东财源与 push2、经网关取数，只保留规则）。
4. T158：策略 MCP + 服务端策略事件 + 主升浪 bot 与面板（依赖 T155）。
