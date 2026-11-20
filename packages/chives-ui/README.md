# chives-ui

Chives 的品牌壳与「我的」页：侧栏品牌标记/字标、`chives` 主题与 `--chives-*` 令牌、欢迎页快捷卡片、**"我的"与"盯盘"两个侧栏入口**，以及把 dsh 默认落点改成「我的」页（T101）。本包注册 `main` key `chives-mypage`（「我的」页），[watch-panel](../watch-panel/README.md) 注册 `chives-workbench`（盯盘页）；Host 代理仍在 watch-panel，本包 Host 半只注册一条只读 GET 路由 `/api/chives/health`。

- 目标 dsh 版本：`0.2.1-rc.5`；`@deepseek-ai/dsh-*`、react、typescript、tsdown 与 [watch-panel](../watch-panel/package.json) **完全同版本、精确钉死**，没有新增任何依赖。
- 不引用外部 URL、不下载字体、不含图片文件；品牌标记是内联 SVG。

## 构建

```bash
cd packages/chives-ui
npm ci
npm run -s typecheck
npm run -s build
npm test
```

产物：

- `lib/index.js`：Host 半（ESM），`main` 指向它。
- `lib/client.js`：Client 半（CJS，`window.__ModuleLoader__.load({ id: "chives-ui", ... })` 包装），`exports["./client"]` 指向它。

`npm test` 用 `node:test` 直接加载纯 TS 模型/桥接模块（Node 24 类型擦除）；DOM 渲染测试用已有的 `typescript` devDependency 把 `src/client` 临时转译成 JS 再交给 `react-dom/server`（`tests/tsx.ts`），不新增依赖。当前 **117** 个用例。

## 装进 profile

```bash
dsh plugin --profile <profile> add "link:$PWD"
```

然后手动把 `chives-ui` 加进该 profile `package.json` 的 `dsh.profile.bundles`（CLI 只转发给包管理器，不会写这个列表），重启 dsh。`cordis.patch.yml` 随 bundle 生效：插入本包，并隐藏官方品牌占位（`ui-brand-official`）、插件管理、"更多"菜单与"智能体预设"设置页。

## 环境变量（Host 半）

| 变量 | 缺省 | 说明 |
|---|---|---|
| `CHIVES_ENGINE` | `WATCH_PANEL_ENGINE`，再缺省 `http://127.0.0.1:8765` | cn-watch 引擎地址。主机名必须是回环地址（`127.0.0.1`、`localhost`、`[::1]`），否则 Host 半在 `apply` 时抛错、拒绝加载。 |

路由不接受任何查询参数（400），只发 `GET /health` + `accept: application/json`，3 秒超时；连不上/超时返回 502 `{"error":"engine_unreachable"}`。响应头只回 `content-type: application/json; charset=utf-8`，不转发浏览器请求头，也不暴露引擎地址。

## 主题

- 用 `ctx.theme.register` 注册两个 id：`chives`（深色，`colorScheme: 'dark'`）与 `chives-light`（浅色，`colorScheme: 'light'`），token 是 `--dsw-alias-*` 到 `--chives-*` 的映射。
- 同时用 `ctx.theme.overrideTokens('chives-ui', { light, dark })` 叠一层别名覆盖。**因此即使用户在设置里选的是内置的浅色/深色/跟随系统，Chives 配色也会生效**；不需要、也不会写用户的主题设置（Host 半不碰 settings）。
- dsh 的设置页只列内置的 light/dark/system，第三方主题 id 是进程内扩展、不进设置 schema（`core/dsh/packages/client/ui-theme/README.md` 的 Known Limitations）。所以"让 chives 成为默认主题"是通过上面那层覆盖实现的，而不是把偏好改成 `chives`。要完全退出 Chives 配色，移除本 bundle。
- 红涨绿跌是默认；把 `data-chives-updown="green-up"` 放到 `<html>` 或 `<body>`（或 `:root`）上会互换 `--chives-up` / `--chives-down`。颜色之外必须另有 ▲▼ 符号——本包只提供令牌与色值，符号由使用方渲染。

## 令牌表

唯一颜色来源是 [`src/client/tokens.ts`](src/client/tokens.ts)；其余源码只允许 `var(--chives-*)` / `var(--dsw-alias-*)`，测试会扫描。

| 组 | 令牌 | 浅色 | 深色 |
|---|---|---|---|
| 表面 | `--chives-surface-base` | `#FAF8F3` | `#0E1116` |
| | `--chives-surface-panel` | `#FFFFFF` | `#151A21` |
| | `--chives-surface-raised` | `#F3EFE6` | `#1B222B` |
| | `--chives-surface-sunken` | `#F0EBE0` | `#0A0D11` |
| 文字 | `--chives-text-primary` | `#1B1A17` | `#ECE7DA` |
| | `--chives-text-secondary` | `#55514A` | `#B9B4A6` |
| | `--chives-text-tertiary` | `#7C776C` | `#8A8579` |
| 品牌金 | `--chives-gold` | `#9A7B1F` | `#D4AF37` |
| | `--chives-gold-deep` | `#7A6118` | `#B8912B` |
| | `--chives-gold-soft` | `#C9A94E` | `#E8C766` |
| | `--chives-gold-glow` | `rgba(154,123,31,.22)` | `rgba(212,175,55,.20)` |
| 涨跌 | `--chives-red` / `--chives-green` | `#C62F35` / `#1F7A4D` | `#E5484D` / `#2FA36B` |
| | `--chives-up` / `--chives-down` | `var(--chives-red)` / `var(--chives-green)` | 同左 |
| | `--chives-flat` | `#8A8579` | `#8A8579` |
| 状态 | `--chives-state-healthy` | `#1F7A4D` | `#2FA36B` |
| | `--chives-state-warn` | `#9A6B00` | `#D9A441` |
| | `--chives-state-critical` | `#B3261E` | `#E5484D` |
| | `--chives-state-idle` | `#7C776C` | `#8A8579` |
| 发散 | `--chives-diverging-neg/mid/pos` | `#C62F35` / `#B8B2A6` / `#1F7A4D` | `#E5484D` / `#6B7280` / `#2FA36B` |
| 热力图 | 用 `--chives-up` / `--chives-down` + `--chives-diverging-mid` 做 `color-mix`，以便跟随 `data-chives-updown` 互换；`diverging-*` 保留给非涨跌语义的发散图 | — | — |
| 分类 | `--chives-cat-1`…`--chives-cat-8` | 固定顺序，不循环 | 固定顺序，不循环 |
| 发丝线 | `--chives-hairline` / `--chives-hairline-color` / `--chives-border-weak` | `0.5px` / `#E4DCCB` / `#EEE7D9` | `0.5px` / `#2A313B` / `#222932` |
| 动效 | `--chives-ease` / `--chives-dur-fast/base/slow` | `cubic-bezier(.22,1,.36,1)` / `120ms` / `200ms` / `320ms` | 同左 |
| 标记 | `--chives-mark-stone(-deep)` / `--chives-mark-gold(-deep)` / `--chives-mark-highlight` / `--chives-ripple` | 见 token 文件 | 见 token 文件 |
| 字体 | `--chives-font-serif` | `Georgia, "Songti SC", "Noto Serif CJK SC", serif` | 同左 |

`--dsw-alias-*` 覆盖：`bg-base`、`bg-layer-1/2/3`、`label-primary/secondary/tertiary/caption`、`border-l1/2/3`、`brand-primary`、`brand-text`、`link`、`interactive-bg-hover/active`、`state-success/warn/error/idle-primary`。

## 动效表

| 动效 | 时长 | 实现 |
|---|---|---|
| 欢迎页启动序幕（触碰涟漪） | 900ms 扫金 + 1100ms 涟漪 | 内联 SVG + CSS `clip-path` 关键帧；`localStorage`（try/catch）记录，一周内不重复 |
| 6 张卡片错落入场 | 200ms，间隔 40ms，最后一张 400ms 落地 | CSS `animation-delay` |
| 卡片悬停金色径向高光 | 120ms 淡入 | CSS 变量 `--chives-mx/--chives-my` + `pointermove`，rAF 节流 |
| 首页卡片错落入场 | 240ms，间隔 40ms，总长 400ms | CSS `animation-delay` |
| 首页数字逐位 tick | 320ms | 每个变化字符换 key 重新挂载 + `translateY` |
| 首页迷你线描绘/末端呼吸/悬停十字线 | 700ms + 2400ms 循环 | 内联 SVG + CSS `stroke-dashoffset`/关键帧 |
| 首页告警入场/30 秒金色边光 | 420ms + 30s | CSS 关键帧 |
| 引擎脉搏点 | 2.2s/3.2s/4.6s | CSS 关键帧；断流更慢 |
| 跨面板追问 | 无动画 | `chives:ask` 事件 + `setDraft` |

`@media (prefers-reduced-motion: reduce)` 关闭卡片入场、扫金、涟漪的动画与位移/缩放，并隐藏悬停高光；状态色变化保留。只用 CSS 动画/Web Animations，不引入动画库。

## 界面与落点

- `sidebar.brand.mark` / `sidebar.brand.name`：Chives 内联标记 + 衬线字标与"让股民享受AI时代红利"。两个 single cell 都以 `priority: -10` 注册，遮蔽 official 构建在 rank 0 的官方占位；补丁同时禁用 `ui-brand-official` 让出 cell。
- `conversation.hero.brand.mark`：大号标记 + 标题"今天想研究什么？" + 启动序幕。标题没有独立 slot、`conversation` locale 又是单占用，所以标题由本座位渲染，`styles.ts` 用 `[class*="titleGroup"]` 隐藏自带的标题与"预览版"徽标。
- `conversation.input.dock`：欢迎页 6 张快捷卡片，只在 `session.blank` 时出现；点击调用官方 `inputActions.setDraft(text)` **填入输入框、不发送**。同一组件也消费"待处理草稿"（见下）。卡片区上边距 20px（叠加上方 8px gap 约 28px）、下边距 24px，≤900px 两列、≤560px 一列。
- `sidebar.panellist` 的 `chives-mypage`（order 5）：**"我的"入口**（默认落点），钱包风格内联 SVG 图标；`main` 面板 `chives-mypage` 也由本包注册（`apply.ts:160-165`）。
- `sidebar.panellist` 的 `chives-workbench`（order 10）：**"盯盘"入口**，图标就是 Chives 标记。主面板由 watch-panel 注册；侧栏行必须与 watch-panel 的 `PANEL_ID = 'chives-workbench'` 保持一致。
- `sidebar.panellist` 的 `schedules`（order 90，`priority: -10`）：遮蔽 dsh 自带定时任务行并改中文名；主面板仍由 dsh 提供。
- 侧栏入口顺序：新会话（dsh 自带）→ 我的 → 盯盘 → 定时任务。原"首页"面板已删除。

## 我的 / 盯盘入口（T97/T100/T101）

- 「我的」页由本包的 `main` 面板 `chives-mypage` 提供：总览、持仓表、风险、收益曲线、持仓结构、关注清单与导入/诊断入口都在那一页里；数据经 watch-panel 的同源代理读取。
- 盯盘页由 watch-panel 的 `main` 面板 `chives-workbench` 提供：脉搏带、引擎摘要、待你决策、信号卡、行业板块、涨跌幅榜、资金流向、我的盯盘、已处理、抽屉与底部提问条都在那一页里。
- 本包负责侧栏：`MY_PAGE_PANEL = 'chives-mypage'`、`WORKBENCH_PANEL = 'chives-workbench'`、`NAV_ORDER = { myPage: 5, workbench: 10, schedule: 90 }`。`MyPageIcon` 是钱包轮廓，`WorkbenchIcon` 是 Chives 标记；`ScheduleIcon` 保留时钟。
- 启动落点：本包注册 `chives-mypage` 后调用 `ctx.layout.selectPanel('chives-mypage')`；若布局注册表尚未刷新，最多重试 20 次、每次 100ms。沿用 T93 的官方 `selectPanel` 机制，不替换 `main.conversation`。
- 跨面板切换：`src/client/panels.ts` 监听 `chives:panel`（`detail.panel` 只接受上面两个已知 id），转发给 `ctx.layout.selectPanel`；「我的」页的"去盯盘页看信号"用它切到 `chives-workbench`。
- 旧 `HomePanel`/`homeModel` 已随合并删除；`styles.ts` 里仍保留旧首页的样式规则是历史遗留，当前无组件使用（后续可清理，不影响运行）。
- 只装 chives-ui、不装 watch-panel 时，「我的」页能打开但数据代理与盯盘主面板缺失；两个包必须同时安装。

## 跨面板"打开对话继续追问"

`main` 槽位没有 `inputActions`。watch-panel 的"打开对话继续追问"发出 `window` 事件 `chives:ask`（`detail.text`）；本包在 `apply` 里监听，把文本写入 `chives.pendingDraft`（内存 + 带 try/catch 的 `localStorage`），调用 `ctx.layout.selectPanel('conversation')`。持仓页的提示语带 `detail.persist=false`，只写内存草稿、不落 `localStorage`，避免成本价等持仓信息被持久化。`conversation.input.dock` 里的卡片组件在挂载时或收到同一事件时调用官方 `inputActions.setDraft(text)`，**不调用 `submit()`**。文本裁剪到 2000 字符；存储不可用时退回内存。
- 启动默认落「我的」页：注册 `chives-mypage` 的 `main` 后调用 `ctx.layout.selectPanel('chives-mypage')`（布局 store 初始为 `null`=对话；这是官方导航 API，不替换 `main.conversation`）。
- 侧栏顺序常量：我的 5、盯盘 10、定时任务 90。定时任务（`schedules`，dsh 自带 id）以 `priority: -10` 遮蔽同名 `sidebar.panellist` 单元格，改标签/顺序/图标，主面板仍由原包提供。

## 「我的」页（T101）

- 顶栏：标题、数据时间、行情时间、交易状态、隐藏金额眼睛开关、导入/诊断。交易状态取 `/api/watch/state` 的 `session`；cn-watch 不可达时显示"未知"。
- 六格总览：总资产、持仓市值、今日盈亏、累计浮盈、仓位（细进度条）、现金；`price_unavailable` 行从汇总排除；`total_assets_cny`/`cash_cny` 缺失显示"未设置现金"而不是 0。
- 持仓表：名称+代码、持仓（股）、成本、现价、今日盈亏、累计盈亏（金额 + 百分比）、占比（数字 + 细条）、标记（T+1 不可卖、涨停/跌停、行情缺失）；列头升降排序、默认占比降序；行内展开成本价、可卖数量、占总资产与"问 Chives 这只票"（提示语只含该股名称/代码/现价/成本）。
- 风险卡：年化波动率、最大回撤、Beta、第一大持仓、有效 N + 一行白话解释；`risk` 为 null 显示"风险指标计算中…/暂不可用"与 `risk_reason`；`risk_pending` 20 秒后自动重取一次。
- 收益曲线：`/portfolio/history` 的 SVG 面积折线，方向色取最后一点相对第一点；少于 2 点显示"已记录 N 天快照…不回补历史"；悬停十字线给出日期/总资产/当日盈亏；"30 天｜90 天｜全部"对应 days=30/90/365。
- 持仓结构：前 5 大 + "其他"堆叠条，颜色只用 `--chives-cat-*` 且避开 cat-2/cat-7；点条段高亮对应行。
- 关注清单：`/api/watch/state` 的自选，名称+代码、现价、涨跌胶囊，与持仓重叠标"持有"；"去盯盘页看信号"发 `chives:panel` 切到 `chives-workbench`。
- 空态：`empty:true` 显示"还没有持仓"引导卡并突出导入；总览卡显示"—"；hub 不可达显示"数据服务未启动"+重试，有旧数据时显示"数据陈旧"横幅。
- 隐私：持仓只在组件内存；唯一持久化是隐藏金额开关 `chives.my.hidden`（try/catch）；含持仓的 `chives:ask` 带 `persist:false`，只写内存草稿、不落 `chives.pendingDraft`；页面只请求同源 `/api/hub/portfolio-*` 与 `/api/watch/state`。
- 轮询：overview 10 秒、history 5 分钟、watch state 10 秒，页面/面板不可见时暂停；失败按 2 的幂退避，旧数据不清空。
- 为什么页面在本包：T18 的 watch-panel client bundle 预算是 200 KB；页面计入 watch-panel 会到 245 KB。页面放在本包后 watch-panel 为 194,701 bytes，Host 代理仍留在 watch-panel。

## 未隐藏的及原因

| 条目 | 处理 | 原因 |
|---|---|---|
| `ui-brand-official` | 隐藏 | 它在 official 构建以 rank 0 占住 `sidebar.brand.mark` / `sidebar.brand.name` 两个 single cell；Chives 以 -10 遮蔽，补丁再让出 cell，两层都保留。 |
| `ui-plugin-manager` | 隐藏 | 插件管理是独立行，注册 `main` key、`sidebar.panellist` 与 `shell.overlay`，没有别的包依赖它声明的 slot。 |
| `entry-customization` | 隐藏 | "更多"菜单 = 它在 `sidebar.panellist.actions`、`conversation.session.header.views.actions`、`sidebar.right.tab.guide.actions` 三处注册的入口；三处都由别的包声明 slot，删掉它只是移除消费者。侧栏启动器另有 `nav[class*="panelList"] button[aria-haspopup="menu"]` 样式兜底。 |
| `ui-agent-preset` | 隐藏 | `agent-presets` 设置页由这一行的 `settings.section` 占用；同时它还给欢迎页预设 chip、会话头标签。只有一个 finance 预设时这些控件没有内容，故整行隐藏。 |
| `ui-settings-plugins` / `ui-settings-plugin-inventory` | **保留** | 任务只要求隐藏"插件管理"；这是设置里的只读内置清单页，不在要求内，隐藏会牵动设置导航。 |
| `ui-layout` / `ui-sidebar` / `ui-conversation` / `ui-theme` / `ui-settings-general` | **不动** | 结构性行，声明了 `main`、`sidebar.*`、`conversation.*`、`settings.section` 等 seat；禁用会让所有注册方失效。 |
| 右侧栏 guide 的"更多"按钮 | 随 `entry-customization` 一起消失 | 同一个消费行，无法只删一处；保留 slot 本身。 |
| 设置里其他标题（通用/模型/账号等） | **不改名** | `ctx.locale.register` 对同一 `(namespace, locale)` 重复注册会抛错（见下），插件无法覆盖已有 key。 |

## 文案覆盖的限制

`ctx.locale.register(ns, locale, dict)` 在 `(namespace, locale)` 已存在时直接抛错（`core/dsh/packages/client/locale/src/client/index.ts:421` 附近），没有"覆盖单个 key"的 API。因此：

- 欢迎页标题不再依赖 locale 覆盖：由 `conversation.hero.brand.mark` 座位渲染"今天想研究什么？"，并用样式隐藏 `titleGroup`（自带标题 + "预览版"徽标）。这是核心没有标题 slot 时的最后手段，核心若提供标题 slot/覆盖 API 应改回官方入口。
- 侧栏定时任务改名是通过遮蔽 dsh 自带的 `schedules` 单元格实现的（改为"定时任务"），不是改 locale。
- 设置页标题、其他包的文案无法改名；如需，只能改核心或让核心提供覆盖 API。

## 已知限制

- 浏览器标签标题与 favicon 需要重新构建前端，本包不做，保持 dsh 原样。
- 第三方主题 id 不出现在设置的选择列表里；Chives 配色靠覆盖层生效（见上）。
- 静态 client bundle 没有动态插件沙箱里的 `styles.insert` 符号；本包用自有的 `<style data-chives="chives-ui">` 标签实现同一语义，并在 `ctx.effect` 卸载时移除。
- 欢迎页卡片只放在 `conversation.input.dock`；若上游改变该 slot 的 owner props（`InputZone`），需要同步。
- 盯盘页数据依赖 watch-panel 已安装并注册 `/api/market/*`、`/api/watch/*` 与 `/api/hub/*`；只装 chives-ui 时侧栏盯盘行没有对应主面板。
- 侧栏入口与主面板跨包：本包注册 `sidebar.panellist` 与 `chives-mypage` 的 `main`，watch-panel 注册 `chives-workbench` 的 `main`，两边用同一组字符串；改 id 必须两边同步。
- 「我的」页的数据代理在 watch-panel：只装本包时页面能打开但请求 404。持仓行的涨停/跌停标记由 `change_pct` 与代码板块近似推断（主板 10%、创业板/科创板 20%、北交所 30%），ST 等特殊标的可能漏标。收益曲线"全部"最多请求 365 天。
- `chives:panel` 是页面之间的轻量约定：本包只做 id 白名单校验后调用布局服务；若目标面板未注册，`selectPanel` 抛错被吞掉，页面不崩溃但不会切换。
- 本包无法创建"新会话"：提问条/追问只把草稿填入当前对话输入框并切到对话面板（官方 `inputActions.setDraft`，不调用 `submit`）。"新建会话"按钮在 dsh 自带的侧栏顶部，不在本包控制范围内。
- 告警分析全文只对 cn-watch 告警可用；market-watch 告警显示其 `detail`，契约没有单条分析正文端点。工作台的"个股抽屉"对榜单里、但不在自选中的股票只能显示榜单字段（无规则/无涨跌停价），页面会明确提示。
- 只在 Node 24 + macOS 上验证过类型检查、构建与离线测试；真实浏览器渲染与动效由验收者做，本包不声称已验证。
