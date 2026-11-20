# watch-panel

dsh 的 A 股**盯盘页**（T100）与**「我的」页**（T101）。Host 半在**已认证**的 `/api` 下注册路由：`/api/watch/*` 转发给本机的 [cn-watch](../cn-watch/README.md) 引擎并读取本地告警分析文件；`/api/market/*` 按 [`docs/market-watch-api.md`](../../docs/market-watch-api.md) 的 v1.4 契约转发给本机的 `market-watch` 引擎；`/api/hub/*` 按 [`docs/hub-api.md`](../../docs/hub-api.md) 转发给本机的 `chives-hub`：12 条公开读路由（信号列表/详情、计划列表、分时迷你线 `/spark`，以及 v1.1 的 `settings`/`discipline`/`reviews`/`review`/`cards`/`card`/`candidates-stats`/`guidance`）、2 条**私有只读**路由（`portfolio-overview`、`portfolio-history`）与 5 条受限写路由（信号状态、计划确认、设置、纪律、作战卡）。私有持仓读与 v1.1 的 `settings`/`discipline`/`reviews`/`review`/`cards`/`card`/`candidates-stats`/`guidance` 的响应（含 400/502）一律 `Cache-Control: no-store`；hub v1.1 的 `/review-data`、`POST /reviews`、`POST /cards`、`/settings/*/suggest`、`/triggers*` **不开放**。Client 半只向 `main` 注册 `chives-workbench`（盯盘页），**不注册 `sidebar.panellist`、也不注册「我的」页**；「我的」页与两个侧栏入口由 [chives-ui](../chives-ui/README.md) 提供，本包只提供它依赖的 Host 代理。

- 目标 dsh 版本：`0.2.1-rc.5`（`@deepseek-ai/dsh-*` 与 react/typescript/tsdown 全部精确钉死，**不要改成 `^` 或 `latest`**）。
- 没有运行时依赖，也不引入新的 devDependency。
- 页面**只读**：不提供加自选、移除、改规则或任何下单入口；这些动作由智能体在对话里完成。

## 构建

```bash
cd packages/watch-panel
npm ci
npm run -s typecheck
npm run -s build
npm test
```

产物：

- `lib/index.js`：Host 半（ESM），`main` 指向它。
- `lib/client.js`：Client 半（CJS，带 `window.__ModuleLoader__.load({ id: "watch-panel", ... })` 包装），`exports["./client"]` 指向它。

`npm test` 用 `node:test` 直接加载纯 TS 视图模型/Host 模块（Node 24 类型擦除）。DOM 渲染测试用已有的 `typescript` devDependency 把 `src/client` 临时转译成 JS 再交给 `react-dom/server`（`tests/tsx.ts`），不新增依赖、不改生产构建。当前 **520** 个用例。

## 装进 profile

```bash
dsh plugin --profile <profile> add "link:$PWD"
```

然后手动把 `watch-panel` 加进该 profile `package.json` 的 `dsh.profile.bundles`（CLI 只转发给包管理器，不会写这个列表），重启 dsh。侧栏"我的"（order 5）与"盯盘"（order 10）入口由 chives-ui 提供；`chives-mypage` 主面板也在 chives-ui，`chives-workbench` 主面板在本包。两个包需同时安装（「我的」页的数据仍走本包的 Host 代理）。

## 环境变量

| 变量 | 缺省 | 说明 |
|---|---|---|
| `WATCH_PANEL_ENGINE` | `http://127.0.0.1:8765` | cn-watch 引擎地址。**主机名必须是回环地址**（`127.0.0.1`、`localhost`、`[::1]`），否则 Host 半在 `apply` 时抛错、拒绝加载。 |
| `WATCH_PANEL_MARKET_ENGINE` | `http://127.0.0.1:8766` | `market-watch` 引擎地址。同样只接受回环主机名。 |
| `WATCH_PANEL_HUB_ENGINE` | `http://127.0.0.1:8767` | `chives-hub` 地址。同样只接受回环主机名；`/api/hub/*` 只连这个回环服务，**只代理固定的 19 条路由**（含两条 `/portfolio/*` 私有读、一条 `/spark` 公开读与 v1.1 白名单读/写；不生成通用 `/portfolio/*`、`/triggers*` 或开放代理）。 |
| `WATCH_PANEL_ANALYSES_DIR` | `<仓库根>/runtime/watch/analyses` | 告警分析目录。必须是**绝对路径**，否则 Host 半在 `apply` 时抛错、拒绝加载。缺省值由 `import.meta.url` 从本包位置解析，源码与 `lib/` 两种布局都指向同一个仓库根。 |

浏览器永远看不到这两个地址：页面只请求同源的 `/api/watch/*` 与 `/api/market/*`，Host 半自己拼接上游。

## 数据流

```text
浏览器（同源 fetch，自动带 dsh 的认证 cookie）
  GET /api/watch/health | /state | /alerts | /rules | /rules/history   ← cn-watch 代理
  GET /api/watch/analyses | /analysis                                   ← 本地分析文件
  GET /api/market/health | /overview | /sectors[?level=sw1|industry] | /alerts | /rules
  GET /api/market/movers?kind=&limit=&include_st=&include_new=&include_bj= ← 榜单
  GET /api/market/summary                                               ← 引擎摘要
  GET /api/market/flows?kind=&limit=&include_st=&include_new=&include_bj= ← 资金流向
  GET /api/market/flows-northbound                                      ← 北向（可能 available:false）
  GET /api/market/sector?code=<BKxxxx>                                  ← 行业详情
  GET /api/market/sector-members?code=<BKxxxx>                          ← 行业成分
  GET /api/market/pool?kind=&date=&limit=                               ← 涨停/炸板/跌停池（v1.4）
  GET /api/market/pool-ladder?date=                                     ← 连板梯队
  GET /api/market/pool-history?days=10..30                              ← 池历史与晋级率
  GET /api/market/pool-yesterday                                        ← 昨日涨停今日表现
  GET /api/market/pool-by-industry?date=                                ← 涨停行业分布
  GET /api/market/breadth-series?date=                                  ← 宽度分钟序列
  GET /api/market/themes?kind=concept&limit=&sort=                      ← 概念榜
  GET /api/hub/signals?status=&decide=&object=&limit=&since_id=         ← 信号列表
  GET /api/hub/signal?id=<int>                                          ← 信号详情
  GET /api/hub/plans?status=                                            ← 计划列表
  GET /api/hub/spark?codes=600519.SH,300750.SZ                          ← 分时迷你线（公开，no-store）
  GET /api/hub/settings                                                 ← 设置与建议（no-store）
  GET /api/hub/discipline                                               ← 纪律状态（no-store）
  GET /api/hub/reviews?limit=1..50&kind=                                ← 复盘列表（no-store）
  GET /api/hub/review?date=&kind=                                       ← 单份复盘（no-store）
  GET /api/hub/cards?status=&date=                                      ← 作战卡列表（no-store）
  GET /api/hub/card?id=<int>                                            ← 作战卡详情（no-store）
  GET /api/hub/candidates-stats?days=5..60                              ← 候选统计（no-store）
  GET /api/hub/guidance?date=                                           ← 盘中指引
  GET /api/hub/portfolio-overview                                       ← 持仓总览（私有，no-store）
  GET /api/hub/portfolio-history?days=7..365                            ← 收益快照（私有，no-store）
  POST /api/hub/signal-action  {id, action, until?}                     ← 信号状态（受限写）
  POST /api/hub/plan-action    {id, action, expires_at?}                ← 计划状态（受限写）
  POST /api/hub/setting-action {key, action, value?}                    ← 设置（受限写）
  POST /api/hub/discipline-action {kind, action|slot/level/note}         ← 纪律（受限写）
  POST /api/hub/card-action    {id, action, stop?|state?}                ← 作战卡（受限写）
        │
        ▼
dsh Connection（先过 Host/Origin/cookie 校验，再进 exact Fetch 路由）
        │
        ▼
watch-panel Host 半
  · /api/watch：6 条原有路由 + 1 条只读规则变更历史路由；
    查询串只允许 /alerts 的 after_id/limit、/rules/history 的 limit、
    /analyses 的 limit、/analysis 的 id；其余路径不允许查询参数
  · /api/market：18 条固定精确路由（health/overview/sectors/alerts/rules +
    movers/summary + flows/flows-northbound + sector/sector-members + v1.4 的
    pool/pool-ladder/pool-history/pool-yesterday/pool-by-industry/breadth-series/themes）；
    行业代码走 `code` 查询参数，不生成代码路由表；v1.4 的 `date` 必须是严格的真实日历日期
  · /api/hub：19 条固定精确路由（signals/signal/plans/spark + v1.1 的
    settings/discipline/reviews/review/cards/card/candidates-stats/guidance +
    signal-action/plan-action/setting-action/discipline-action/card-action +
    portfolio-overview/portfolio-history）；写路由要求 `x-chives-action: 1` + `application/json`，
    请求体 ≤ 4 KB，按类型白名单重新序列化后发给上游，不转发原始体、cookie 或任何浏览器请求头
  · spark 读路由只接受唯一参数 `codes`：逗号分隔、去重后 ≤30 个严格匹配
    `^[0-9]{6}\\.(SH|SZ)$` 的规范代码；空值/非法码/重复参数/多余参数一律 400 且不发上游，
    转发时按校验后的代码重新拼接查询串，响应带 `Cache-Control: no-store`
  · 两条 portfolio 读路由只接受固定路径：overview 不允许任何查询参数，history 只允许
    规范十进制 `days`（7–365，缺省 90；重复/前导零/小数/多余参数一律 400 且不发上游）；
    所有响应（含 400/502）都带 `Cache-Control: no-store`，错误信息不包含持仓内容
  · /api/market 查询串只允许 /sectors 的 level=sw1|industry、/alerts 的 since_id/limit、
    /movers 的 kind∈gainers|losers|active、limit∈5–20 整数、include_st|include_new|include_bj∈0|1
    （缺省由代理补全：gainers/10/0/0/0），以及 /sector、/sector-members 的 code；
    summary 不接受任何参数。v1.4：/pool 的 kind∈zt|zb|dt（缺省 zt）、date、limit∈1–200（缺省 200）；
    /pool-ladder、/pool-by-industry、/breadth-series 只接受 date；/pool-history 的 days∈10–30（缺省 20）；
    /pool-yesterday 不接受参数；/themes 的 kind=concept、limit∈5–30（缺省 20）、sort∈change|amount
    （缺省 change）。重复参数、未知参数、非法值一律 400 且不发上游请求；
    date 必须是 YYYY-MM-DD 且真实存在（闰年按日历校验）；
    code 必须恰好出现一次、是唯一参数，且严格匹配 ^BK[0-9]{4}$（大小写敏感）
  · /api/hub v1.1 读路由的参数白名单：settings/discipline 无参数；reviews 的 limit∈1–50（缺省 20）、
    kind∈evening|premarket；review 的 date+kind 均必填；cards 的 status∈proposed|active|closed|all、
    date 可选；card 的 id 为规范正整数（≤ HUB_MAX_ID）；candidates-stats 的 days∈5–60（缺省 20）；
    guidance 的 date 可选。settings/discipline/reviews/review/cards/card/candidates-stats/guidance
    的成功、400、502 响应都带 Cache-Control: no-store
  · /api/hub v1.1 写路由：setting-action 的 key 必须是契约 11 项之一，action∈adopt|set|clear|dismiss，
    仅 set 带有限数值 value，key 只进上游路径；discipline-action 只接受
    {kind:"loss-streak",action:"add"|"reset"} 或 {kind:"mood",slot,level,note?≤60}；
    card-action 的 action∈confirm|cancel|tighten_stop|set_state，仅 tighten_stop 带有限正数 stop、
    仅 set_state 带 abandon|exit；多余字段一律拒绝
  · 上游路径只用校验后的 code 拼接，绝不转发原始查询串
  · 出站只发 GET + accept=application/json，不带任何浏览器请求头（cookie/authorization 等）
  · cn-watch 3 秒超时；market-watch 5 秒超时、响应上限 2 MB
  · 上游不可达/超时 → 502 {"ok":false,"error":{"code":"engine_unreachable",...}}
  · 响应头只回 content-type: application/json; charset=utf-8（set-cookie 等一律丢弃）
        │
        ▼
cn-watch（127.0.0.1:8765，个股/ETF）      market-watch（127.0.0.1:8766，大盘/板块/情绪）
```

## 界面（盯盘页）

版面按 [Chives 工作台说明](../../docs/chives-ux-design.md)：粘性脉搏带（指数卡 + 宽度条 + 引擎摘要）→ 顶部信号筛选芯片 → 待你决策（最多 3 张大卡，没有则整块收起）→ ≥1280px 两列 3:2（左：行业板块、涨跌幅榜、资金流向；右：我的盯盘、信号、已处理），<1280px 单列，顺序固定为 待你决策 → 我的盯盘 → 信号 → 行业板块 → 涨跌幅榜 → 资金流向 → 已处理；底部固定提问条。原来的"事件流"列表整块取消，由信号卡取代。核心内容**不用页签**。

1. **脉搏带（粘性）**：6 张指数卡（名称+代码在上、涨跌徽标在右上、迷你线居中、大号现价在下、成交额在底），`spark_kind=intraday|daily` 时休市标"日线"，`spark` 为空显示"—"；宽度条（涨/跌/平家数、涨停/跌停/炸板/封板率/最大连板、成交额）与 `regime` 徽标；右端交易状态、引擎脉搏点、数据时间与"引擎·规则"徽标（打开规则/变更历史抽屉）。滚动超过 48px 收缩为单行指数名 + 涨跌幅。
2. **引擎摘要**：`/api/market/summary` 的 2–4 条（方向点 + 加粗标题 + 一句话），`refs` 渲染为可点击名称，分别打开行业/个股/指数抽屉；块头标"引擎摘要 · 更新于 N 分钟前"；`stale`、`reason` 或不可达都显示原因。
3. **信号卡**（`/api/hub/signals?status=active&limit=50`，10 秒；`status=done&limit=20`，30 秒）：类型图标/标签/配色（机会蓝、计划触发金、风险橙、板块紫、信息灰，**类型色避开红绿**），方向标签 ▲偏多红/▼偏空绿/—中性（随 `data-chives-updown` 互换）；新卡带呼吸点，卡片错落入场（40ms）。卡片含时间、标题、方向与对象标签、结论（纯文本）、简析、上下文小部件（`range` 进场区间/放弃位条、`rank` 排名变化+迷你线、`spark`）、来源、`merged_count>1` 的"已合并 N 条同类"标签与按钮：
   - 主按钮按 `primary.action`：`open` 打开信号抽屉、`confirm_plan` 向 `POST /api/hub/plan-action` 发 `confirm`、`remove_watch`/`research` 把对应提示语填入底部提问条（不发送）、`ack` 标记已读；
   - "让 Chives 重看"填入"请重新分析 <对象> 的信号：<标题>"；"稍后提醒 ▾"菜单（30 分钟后/收盘前/明天开盘）调用 `snooze`；"忽略"先淡出再调用 `ignore`，底部提示条提供"撤销"（`reopen`）。
   - `decide=true` 的信号按严重度/时间取前 3 进"待你决策"，其余落"信号"。顶部芯片"全部｜待决策｜我的票｜板块"同屏过滤（保留状态，不是页签）。
   - 抽屉：`/api/hub/signal?id=`，显示 `analysis.sections`（结论/方向/要点/详情）与 markdown 原文（React 文本节点，不解析 HTML、不执行脚本），带数据时间与来源；打开时自动 `ack`（seen）。
   - hub 不可达：待你决策与信号区显示"信号服务未启动"空态，并在"已处理"下方提供"原始告警"折叠区，退回 cn-watch 与 market-watch 告警的合并时间线（沿用 `buildTimeline`）。
4. **行业板块**：`/api/market/sectors?level=sw1`；默认热力图，面积依据默认 **成交额(√)**（`sqrt(amount)`，压缩大小行业差距），可切"等权"；每格**一定显示名称**（最小格字号 11px、最多 3 行换行/字符断行），放不下时先隐藏涨跌幅、再隐藏成交额，二者仍在悬停浮层；最小格有 `MIN_TILE_SHARE = 1.2%` 面积下限。悬停浮层含名称、涨跌幅、成交额、占比、领涨股；保持分档配色、`is-strong` 白字与图例。右上"热力图｜排行"是同一模块内的视图开关；点格子/行打开行业抽屉。
5. **涨跌幅榜**：`/api/market/movers`，涨幅榜与跌幅榜并排各前 8（<1280px 上下排），"成交额榜"默认折叠，展开为第三列；"含 ST / 含次新 / 含北交所"默认全关，切换立即重拉；价格变化的行做一次金色脉冲。
6. **资金流向**：`/api/market/flows`，30 秒且仅当区块可见时轮询；并排三列"行业净流入榜｜行业净流出榜｜个股净流入榜"（各前 8），"个股净流出榜"折叠为"更多"。行：序号、名称+代码、主力净流入（亿元，▲/▼，正流入红/负流出绿）、涨跌幅；块头小字"东财主力口径·仅作辅助参考"，`/api/market/flows-northbound` 返回 `available:true` 时在块头右侧显示北向净流入，`false` 时不显示也不报错。点击行业行打开行业抽屉，个股行打开个股抽屉；取不到/陈旧时置灰并显示 `reason`。
7. **我的盯盘**：自选按股票聚合——名称+代码、现价、涨跌幅、距最近涨跌停、**规则默认收成"N 条规则"徽标**（悬停或键盘聚焦弹出完整列表：规则代码 + 中文说明 + 当前状态；移动端点击展开），**仅触发中的规则**以金色小徽标显示在行内；行内再有该股最新一条 hub 信号的一行结论（类型色点 + 时间，点击打开信号详情）与最近告警/分析状态。"＋加自选"仍只填入对话草稿。持仓摘要默认折叠，不读取任何持仓数据。
8. **已处理**：折叠一行"今天已处理 N 条 · 已合并 M 条同类"（N 取 hub `counts.done`），点击展开最近 20 条灰态卡片并可"重新打开"。
9. **抽屉**：右侧滑入、同一时刻只开一个；Esc、点遮罩关闭；打开时聚焦关闭按钮，关闭时把焦点还给触发元素；`position: fixed` 覆盖层不改变面板滚动位置。五类抽屉：行业详情、个股详情、分析全文（纯文本）、引擎与规则、信号详情。
10. **提问条**：固定在页面底部（`position: sticky`）；提交时在问题前加一句公开上下文（交易状态、上证、自选名称），只含公开行情与自选代码，**不含持仓与画像**；文本裁剪到 2000 字。面板内没有 `inputActions`，所以通过 `chives:ask` 事件交给 chives-ui：切到对话面板并把草稿写入输入框（官方 `setDraft`，**不发送**）。页面顶部的搜索框也走同一机制，回车 = "介绍一下 X"。

## 「我的」页（由 chives-ui 实现）

「我的」页的组件、视图模型、样式与文案在 [chives-ui](../chives-ui/README.md)；它只通过本包的同源代理读取 `/api/hub/portfolio-overview`、`/api/hub/portfolio-history` 与 `/api/watch/state`。代理的参数白名单、`Cache-Control: no-store`、不回传 cookie、`hub_unreachable` 精确 body 见下面「数据流」与本文 §Host 半。

## 轮询与动效

- 盯盘页可见时：`/health`、`/state`、`/market/health`、`/market/overview` 5 秒；告警 10 秒；板块 15 秒；规则 60 秒；`/movers` 30 秒、`/flows` 30 秒（仅当对应区块被 `IntersectionObserver` 判定可见时才发请求）；`/summary` 60 秒；`/hub/signals` 10 秒、`/hub/signals?status=done` 30 秒；北向 60 秒。`document.hidden` 或面板被判定为不可见时**暂停全部定时器**，恢复可见立即各拉一次。
- 单路失败按 2 的幂退避（上限 60 秒），成功后复位；旧数据不清空，顶栏/横幅标"数据陈旧"或"引擎不可达"。
- 数字逐位 tick、自选/榜单行变化金色脉冲、迷你线左→右描绘 + 末端呼吸点、热力图面积/颜色平滑过渡、抽屉滑入 + 遮罩渐显、页面区块错落入场（每块 40ms，总长 ≤400ms）、告警入场/流光。
- 只用 CSS 与 Web Animations API；`prefers-reduced-motion: reduce` 下关闭动画、过渡与位移/缩放，只保留状态色变化。
- 列表动画只作用于变化的行（价格变化集）；信号新卡由 hub 的 `status=new` 驱动呼吸点，不按首轮加载整屏亮起。信号/榜单/抽屉都用稳定 key，刷新不重建整棵 DOM，滚动位置、筛选芯片、抽屉与"已处理"展开状态保留。
- reduced-motion 下关闭卡片入场、悬停上浮、忽略淡出、呼吸点与抽屉位移动画，只保留状态色变化。

## 已知限制

- 引擎不可达时只显示最后一次成功的数据；面板不会自己拉起引擎。
- 面板不自行判断交易日历或新鲜度：时段直接显示引擎的 `session`（cn-watch）或 `trading_state`（market-watch），陈旧由引擎 `stale`/`health` 字段决定。
- **页面写接口只有五条**：`POST /api/hub/signal-action`、`POST /api/hub/plan-action`、`POST /api/hub/setting-action`、`POST /api/hub/discipline-action` 与 `POST /api/hub/card-action`，只改信号/计划/设置/纪律/作战卡状态，绝不触发交易；加自选、移除、改规则仍由智能体在对话里完成。
- market-watch 的 `/sectors/{code}` 与 `/members` 在 Host 上对应 `/api/market/sector?code=` 与 `/api/market/sector-members?code=`；Host 只校验 `^BK[0-9]{4}$`、不保存行业清单，未知行业由引擎返回 `unknown_sector`。
- 休市时引擎返回最后有效值并带 `state_note`（`stale:false`）；界面显示该说明，只有 `stale:true` 才标"数据陈旧"。
- 板块列表接口没有 5 日/20 日收益字段；表格列先显示"—"，下钻详情拿到 `history` 后显示。
- 行业详情/成分在打开时加载一次，刷新按钮可重载；不跟随 60 秒轮询（契约允许，本任务未要求）。
- 分析文件由 `cn-watch-trigger` 写入；被冷却等原因跳过的记录不算"已分析"，展开也不读分析文件。
- 分析列表只取最新 `limit`（缺省 50）条记录，更早的不显示。
- 个股抽屉对"榜单里但不在自选"的股票只能显示榜单字段（现价/涨跌/成交额），没有涨跌停价、规则与告警；页面会明确提示，不用旧值或 0 顶替。
- "迷你线"只在指数卡与信号卡的 `context`（rank/spark）上画；`/api/watch/state` 不提供个股 spark，所以自选行不画线（需求允许"无数据源则不画"）。
- "新会话"无法由面板创建：官方 API 只提供 `inputActions.setDraft`，没有 `submit` 或新建会话入口。提问条/搜索/加自选都只填入草稿并切到对话面板，由用户按回车发送。
- 顶栏搜索在 dsh 的 shell 顶栏里没有 slot，本包把搜索框放在工作台脉搏带第一行；行为与提问条一致。
- 盘前的"昨日涨停池"没有契约字段，本任务只把标题切换为"今日关注"，不伪造涨停池。
- `chives:ask` 事件与 `setDraft` 机制来自 chives-ui；只装 watch-panel 时提问条仍会发事件，但没人消费，输入框不会被填充。
- `market-watch` 告警的 `analysis_id` 与 cn-watch 的 `alert_id` 命名空间不同；本包按 `analysis_id` 请求 `/api/watch/analysis?id=`，若该文件不存在则显示"分析内容加载失败"，不编造正文。
- 只在 Node 24 与本机 macOS 上验证过类型检查、构建与离线测试；真实浏览器渲染与动效由验收者做目视验收，本包不声称已验证。
