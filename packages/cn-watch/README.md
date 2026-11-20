# cn-watch

`cn-watch` 是一个**完全确定性、不调用任何大模型**的 A 股盯盘引擎：经本机数据网关批量取快照、按配置的五类规则判断、把告警追加到本地 JSONL，并通过 `127.0.0.1` 上的 HTTP 接口暴露状态。

- Python 3.12；运行时依赖只有 `pyyaml` 与 `requests`（后者仅用于只读的市场上下文客户端）；网关取数与 HTTP 服务都用标准库。
- 时钟（`cn_watch.clock`）、数据源（`cn_watch.sources`）与交易日历（`cn_watch.calendar`）都是注入的，引擎核心不直接读系统时间、不 sleep、不发请求、不写网络。
- 不交易：没有任何下单、转账或券商连接能力。HTTP 除受限的自选股增删、规则增删改与计划规则增删接口外只有 GET；写接口不能改配置文件、引擎端口/进程，也不能下单。

## 安装与运行

```bash
cd packages/cn-watch
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'

.venv/bin/python -m cn_watch --config watch.example.yaml --check-config
.venv/bin/python -m cn_watch --config watch.example.yaml                 # 真实轮询 + HTTP
.venv/bin/python -m cn_watch --config watch.example.yaml --once          # 请求一次，打印 JSON
.venv/bin/python -m cn_watch --config cfg.yaml --replay replay.jsonl     # 确定性回放
.venv/bin/python -m cn_watch --config cfg.yaml --replay replay.jsonl --serve
```

所有日志写 stderr；`--once` 的 JSON 写 stdout。默认 `--out-dir ./cn-watch-data`。

## 配置

```yaml
watchlist: [002553.SZ, 300750.SZ, 601099.SH, 512880.SH]  # 1~80 个；可写 6 位数字（5/6/9 开头为沪，其余为深）；支持 ETF
polling:
  base_seconds: 3.0
  fast_seconds: 1.0
  hot_band_pct: 0.3
  fast_hold_seconds: 30
  idle_seconds: 30
  jitter_pct: 10
  timeout_seconds: 3
  backoff_seconds: [3, 6, 12, 30]
  stale_after_seconds: 15
  max_lag_seconds: 20                     # 可选，默认 20；必须为正数
alerts:
  cooldown_seconds: 300
  rearm_pct: 0.5
active_windows: ["09:30:00-11:30:00", "13:00:00-14:57:00"]
calendar: {source: weekdays}             # 可选；weekdays | file | akshare
rules:
  - {id: pct_up_3, type: pct_change, direction: up, threshold_pct: 3.0}
  - {id: vwap_dev_2, type: vwap_deviation, threshold_pct: 2.0, min_amount_yuan: 20000000}
  - {id: near_up_wide, type: limit_proximity, side: up, within_pct: 1.5, symbols: [601099.SH]}
  - {id: near_up, type: limit_proximity, side: up, within_pct: 0.5, symbols: [002553.SZ]}
  - {id: cross_16, type: price_cross, level: 16.00, direction: up}
  - {id: surge_3x, type: volume_surge, window_seconds: 60, multiple: 3.0, min_window_amount_yuan: 5000000}
api: {host: 127.0.0.1, port: 8765}
# 行情只经本机数据网关取；默认 http://127.0.0.1:8768，只允许回环地址
gateway_url: http://127.0.0.1:8768
limits: {max_watchlist: 10, max_rules: 30}  # 可选；自选股与规则总数上限，默认 10 / 30
# watchlist_runtime_file: /abs/path/watchlist.runtime.json  # 可选；相对路径按配置文件目录解析，默认 <out-dir>/watchlist.runtime.json
```

行情只经本机数据网关：每轮以 `POST /v1/call` 调 `market_quote`，单批最多 20 只，超过则串行分批。外壳 `status` 非 `ok`/`partial` 按取数失败处理（退避、`health` 降级）；单只缺失只记为 missing，不编造价格。

所有时间按 `Asia/Shanghai`（固定 UTC+8）解释。

### 按标的生效的规则（`symbols`）

每条规则可带可选的 `symbols: [...]`，格式与 `watchlist` 相同（可写 6 位数字，按 `5/6/9 → SH、其余 → SZ` 规范化）：

- **不写 `symbols`**：规则对全部自选股生效，行为与旧配置完全一致。
- **写了 `symbols`**：只对列出的标的评估；未列出的标的不会产生该规则的告警，也不会出现在 `/state` 的该规则状态里。
- `symbols` 不在当前 `watchlist` 中只记一条 WARNING，不阻塞 `--check-config`（运行时可再添加该标的）；空列表、重复项（规范化后重复也算）、非法代码、指数代码、非列表类型都是配置错误。
- 同一类型的规则可以有多条，只要 `id` 唯一。例如可以同时配置 `near_up_wide`（`symbols: [601099.SH]`, `within_pct: 1.5`）与 `near_up`（`symbols: [002553.SZ]`, `within_pct: 0.5`）。
- 冷却与再武装仍按 `（规则 id, 标的）` 独立维护；每条告警的 `code` 与 `rule_id` 字段不变。
- `GET /rules` 的每条规则都带 `symbols`：未限定为 `null`，限定则为规范化后的代码列表。旧的 `codes` 写法仍兼容，但不能再与 `symbols` 同时出现。

### 运行时规则（热生效、可审计、可撤销）

规则 = **配置文件规则 ∪ 运行时规则**。运行时层写入 `<out-dir>/rules.runtime.json`（原子替换），**绝不改写 `config/watch.yaml`**；文件缺失、损坏或含非法规则时按空/跳过处理并记日志，不会导致引擎崩溃。重启后运行时规则、覆盖与审计记录都会恢复，并与配置文件重新合并。

- `GET /rules` 的每条规则增加 `source`：`config`（来自配置文件）、`runtime`（运行时新建）、`override`（对配置规则的运行时覆盖）。被 `remove` 的配置规则仍会出现在列表里，带 `source=override`、`disabled=true`、`enabled=false`。
- `POST /rules/upsert`：body 就是一条完整规则（字段与配置文件相同，含可选 `symbols`）。id 不存在则新建（`source=runtime`）；id 与配置规则相同则生成覆盖（`source=override`，YAML 原规则不动）；id 已是运行时规则或覆盖则整条替换。
- `POST /rules/remove`：body `{"id": "..."}`。运行时规则直接删除；配置规则记为禁用覆盖（`source=override`、`disabled=true`），不是真删。
- `POST /rules/revert`：body `{"id": "..."}`。撤销该 id 的全部运行时改动；运行时新建的等同删除，配置规则回到 YAML 原样。对本来就没有覆盖的配置规则是空操作（`status=unchanged`）。
- `GET /rules/history?limit=N`：审计记录，**最新在前**，默认 50、上限 500。每条含 `ts`、`action`（`upsert`/`remove`/`revert`）、`rule_id`、`before`、`after`、`actor`。`actor` 来自请求头 `X-Actor`，缺省 `unknown`，长度截到 64 并清洗控制字符/尖括号；MCP 写工具固定带 `X-Actor: agent`。

写接口是**热生效**的：下一轮轮询即按新规则评估，无需重启。新建规则从干净状态开始；修改规则的阈值或 `symbols` 时只重置该规则的冷却/武装状态，其余规则状态不动；告警 `id` 序列与已发出的告警不受影响。

运行时规则的校验与边界（失败返回 4xx 与错误码，状态不变）：

| 字段 | 允许范围 |
|---|---|
| `pct_change.threshold_pct` | `[0.1, 25]` |
| `vwap_deviation.threshold_pct` | `[0.1, 25]` |
| `limit_proximity.within_pct` | `[0.05, 10]` |
| `volume_surge.multiple` | `[1.2, 50]` |
| `price_cross.level` | `> 0` |

其余字段沿用配置校验（类型、必填、`symbols` 的非空/去重/合法代码等）；超出上表范围返回 `out_of_bounds`，响应里带 `field`、`min`/`max` 与 `allowed`。`id` 只允许 `[A-Za-z0-9_-]{1,40}`；规则总数（启用的生效规则）受 `limits.max_rules`（默认 30）限制；请求体上限 8 KiB。

### 计划规则（Plan，组合条件 + 状态机）

计划规则把"一组市场/板块/个股条件的组合判断"交给 cn-watch 评估，与单指标规则（`pct_change` 等）并存。它是作战卡在盘中的唯一评估逻辑：hub 只保存卡片业务属性，确认后下发 Plan 并订阅状态。计划规则**绝不触发交易**。

```yaml
market_watch_url: http://127.0.0.1:8766   # 可选；只允许回环 http(s)，默认 8766
```

`POST /plans/upsert` 的 body 是一个完整 Plan（同 id 覆盖）：

```json
{
  "id": "card-42", "code": "002553.SZ",
  "market": [{"type": "regime", "values": ["strong", "neutral"]}],
  "sector": [{"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 1.0}],
  "stock": [{"type": "price_cross", "direction": "up", "level": 16.0}],
  "policy": "all", "giveup": [{"type": "pct_change", "direction": "down", "threshold_pct": 3.0}],
  "stop_price": 15.2, "held": false, "expires_at": "2026-11-05T14:57:00+08:00", "label": "复盘卡"
}
```

- 字段白名单严格：Plan 只接受上述字段，`market`/`sector`/`stock`/`giveup` 各 ≤6 条；`policy` 只作用于 `stock`，`market` 与 `sector` 必须全部成立；`lo < hi`；`id` 为 `[A-Za-z0-9_-]{1,40}`；`code` 只接受沪深 A 股/ETF，拒绝北交所与指数；`expires_at` 必须是带时区的 ISO8601；计划总数 ≤30。未知字段、越界值返回 400 `{ok:false, code, message, field}`。
- 条件类型：`regime`、`index_pct`、`sector_change`、`sector_rank`、`price_cross`、`price_in_range`、`pct_change`、`open_pct`、`volume_ratio`。`volume_ratio` 取网关行情返回的量比字段，取不到为 unknown；`open_pct` 在 09:25 后才评估。
- 状态机：`expired > abandon（任一 giveup 成立）> exit（held 且现价 ≤ stop_price）> execute > await_confirm > observe`。unknown 一律不算成立，也不算 giveup 命中；空 `market`/`sector` 列表视为成立。
- 滞回：从 `execute`/`await_confirm` 退回较低状态、或离开 `abandon`/`exit`，需要连续 3 次评估支持；升级立即生效。同一 `(plan, to_state)` 5 分钟内不重复告警；重启后首次评估只恢复状态、不告警。非交易时段不评估、不告警，状态保持。
- `GET /plans` 返回 `{ok, as_of, market_context:{ok, age_s, regime}, plans:[PlanState]}`；`GET /plans?id=<id>` 返回该 PlanState，不存在为 404 `not_found`。`PlanState` 含 `state`、`since`、`last_price`、`held`、逐条 `conds`（true/false/null）与最近 30 条 `history`。
- 状态跃迁到 `execute`/`abandon`/`exit`/`await_confirm` 时写一条普通告警：`rule_id:"plan:<id>"`、`rule_type:"plan"`、`severity` 为 L2（`await_confirm` 为 L1）、`detail:{plan_id, from, to, reason, label}`；沿用 `/alerts`、`after_id`/`since_id` 与去重键。
- 自动监控：`/plans/upsert` 会把新 code 以 `source:"plan"` 加入运行期自选（`/watchlist`、`/state` 可见）；计划都移除后自动撤销，但绝不删除 YAML 自选或用户手动添加的票；超出 `limits.max_watchlist` 时整个 upsert 失败且无副作用。过期计划在 1 个交易日后撤销自动监控。
- 持久化：`<out-dir>/plans.runtime.json` 与 `rules.runtime.json` 同目录，原子替换；文件缺失/损坏/结构错误按空处理并记 WARNING，不会覆盖坏文件；计划定义、状态、逐条条件和 history 一并保存。
- 市场上下文来自只读 market-watch（默认 `127.0.0.1:8766`）：每 5 秒取 `/overview` 与 `/sectors`，`risk_on→strong`、`risk_off→weak`；超过 30 秒未更新或取不到时，相应条件为 unknown，market-watch 故障不影响行情轮询、单指标规则和告警。

### 配置文件热重载

引擎每轮轮询前检查配置文件（`--config` 指向的文件）的修改时间，变化后重新加载 `rules`、`alerts`、`active_windows`、`limits`、`polling` 与 `watchlist`；运行时添加的标的继续与新的配置自选股合并（配置优先）。

- 新配置解析/校验失败：**保留旧配置继续运行**，日志记一行 `rules action=config_reload result=error`，并在 `GET /health`、`GET /state` 的 `config_reload_error` 里给出原因；修好文件后下一次读取/轮询恢复并清空该字段。
- 重载成功记一行 `rules action=config_reload result=ok`。
- `api.host` / `api.port`、`calendar`、`watchlist_runtime_file` 的变更需要重启进程，日志会明确提示，当前实例继续使用旧值；其余字段热生效。
- `GET /health`、`GET /state`、`GET /rules` 也会先做一次同样的检查，因此即使引擎暂时没有新轮询，也能看到配置错误或新规则。

### ETF 标的

`5xxxxx`（沪市基金，如 `512880`）与 `159xxx`（深市基金）可以作为自选股，配置文件与运行时 `POST /watchlist/add` 都接受；名称取网关行情返回的名称。行情解析、涨跌停字段、`pct_change`、`vwap_deviation`、`volume_surge`、`limit_proximity` 与个股使用同一套逻辑。

**不支持指数代码**（如 `399975`、`399975.SZ`、`000300.SH`）：配置校验直接失败；运行时添加返回 `unsupported_instrument`，不会崩溃。可转债、北交所等其他品种也不在支持范围内。

配置**严格校验**。以下任一情况都以退出码 2 退出并在 stderr 给出明确错误：未知规则类型、缺字段、阈值不是正数、规则 id 重复、`watchlist` 超过 80（空列表合法：只盯计划自动加入的代码）、代码格式错误、指数代码、`symbols` 为空/重复/非列表/含非法代码、`api.host` 不是 `127.0.0.1`/`localhost`、`active_windows` 格式错误或起点不早于终点、退避列表为空、`max_lag_seconds` 不是正数（`0`、负数、字符串、布尔、`null` 都算）、`calendar.source` 未知、`source: file` 缺少 `file`、交易日历文件缺失/不是 JSON 数组/含非法日期/为空、`limits.max_watchlist` 不是 1~80 的正整数、`limits.max_rules` 不是正整数、`watchlist` 数量超过 `limits.max_watchlist`、`rules` 数量超过 `limits.max_rules` 等。

### 交易日历

`calendar` 可选，缺省等价于 `{source: weekdays}`。它决定某一天是否评估规则；**非交易日不评估规则、不触发告警**，`stale` 恒为 `false`，`mode` 为 `idle`、`next_interval` 为 `idle_seconds`，但仍会正常轮询并更新最新快照与指标（开盘前仍能看到前收盘价）。交易日的行为与没有日历配置时完全一致。

- `source: weekdays`：周一至周五为交易日，周末休市；**不处理法定节假日与调休补班**。
- `source: file` + `file: <路径>`：文件是 JSON 数组，列出**所有交易日**（如 `["2026-11-02", "2026-11-04"]`），数组之外一律休市。路径相对**配置文件所在目录**解析。文件缺失、不是数组、含非法日期（必须为 `YYYY-MM-DD`）或为空数组都算配置错误，`--check-config` 以退出码 2 退出。
- `source: akshare`：调用 `ak.tool_trade_date_hist_sina()` 取交易日历，缓存到 `cache_path`（可选，缺省 `<out-dir>/trade_calendar.json`；相对路径相对配置文件所在目录）。每个进程每天最多刷新一次；取不到时回退到磁盘缓存，缓存也没有则回退 `weekdays`，并把 `calendar_status` 标为 `degraded`。AKShare 的调用可注入，测试不联网。

`polls.jsonl` 每行、`GET /health`、`GET /state` 都带 `trading_day`（bool）、`calendar_status`（`ok|degraded`）、`session` 与 `last_rule_eval_ts`。

### 交易时段与规则评估时间

`session` 由交易日历与 `active_windows` 共同决定，**窗口两端都算 `open`**：

| 值 | 含义 |
|---|---|
| `non_trading_day` | 交易日历判定当天不是交易日（优先级最高） |
| `pre_open` | 交易日，但当前时刻早于第一个活跃窗口起点 |
| `open` | 当前时刻落在任一活跃窗口内（含起点与终点） |
| `break` | 交易日，当前时刻位于两个活跃窗口之间 |
| `after_hours` | 交易日，当前时刻晚于最后一个活跃窗口终点 |

`last_rule_eval_ts` 是最近一次**真正评估了规则**的轮询时刻（ISO8601 `+08:00`，与 `polls.jsonl` 的 `t` 同格式）；进程启动后从未评估过则为 `null`。评估了规则的那次轮询，它这一行的值就是该轮询自己的 `t`；之后没评估规则的轮询（盘前、午休、盘后、休市、陈旧、取数失败、重复快照）沿用上一次的值。也就是说，**收盘后启动的引擎不会评估规则**，会一直显示 `last_rule_eval_ts: null`、`fired_count: 0`：规则只在 `session == "open"` 时评估，**没有告警不代表没有触发条件**。

判 `open` 时窗口终点是含的（11:30:00、14:57:00 仍为 `open`），但轮询档位与 `stale` 判定沿用原规则（终点那一秒不算活跃档），所以收盘秒可能显示 `session=open` + `mode=idle`。

### 指标

- `change_pct = (price / prev_close − 1) × 100`（`prev_close<=0` 时不计算）。
- `vwap = amount_yuan / (volume_lots × 100)`；`volume_lots<=0` 或成交额缺失时不计算 VWAP，相关规则跳过。
- `vwap_dev_pct = (price − vwap) / vwap × 100`。

网关行情直接给 `amount_yuan`（元）与 `volume_shares`（股）；`volume_lots` 由股数 ÷100 得到，成交额缺失时为 `null`，不估算。

## 五类规则

| 类型 | 触发条件 | 方向 |
|---|---|---|
| `pct_change` | `up`: `change_pct >= threshold_pct`；`down`: `change_pct <= -threshold_pct` | 配置的 `direction` |
| `vwap_deviation` | 仅当 `amount_yuan >= min_amount_yuan`；`abs(vwap_dev_pct) >= threshold_pct` | 偏离的符号（`up`/`down`） |
| `limit_proximity` | `up`: `limit_up>0` 且 `price >= limit_up×(1−within_pct/100)`；`down` 对称 | 配置的 `side` |
| `price_cross` | `up`: 上一次有效快照 `price < level` 且当前 `price >= level`；`down` 对称。**启动后第一次快照永不触发** | 配置的 `direction` |
| `volume_surge` | 墙钟滑动窗：`W` 为最近 `window_seconds` 的累计成交额增量，`P` 为再往前一个同长窗口的增量；内存中至少要有 `2×window_seconds` 的样本；`W >= multiple×P` 且 `W >= min_window_amount_yuan` | `null` |

## 冷却与迟滞

按`标的 × 规则`独立维护：

- 触发后 `armed=false`；重新武装必须**同时**满足：
  1. 距上次触发已过 `cooldown_seconds`；
  2. 触发以来**曾经**回撤到再武装线。
- 再武装线：
  - `pct_change`（up）：`change_pct <= threshold_pct − rearm_pct`（down 对称）；
  - `vwap_deviation`：`abs(vwap_dev_pct) <= threshold_pct − rearm_pct`；
  - `limit_proximity`（up）：`price <= limit_up×(1−(within_pct+rearm_pct)/100)`（down 对称）；
  - `price_cross`（up）：`price <= level×(1−rearm_pct/100)`（down 对称）；
  - `volume_surge`：`W < multiple×P×0.8`。
- 两个条件满足后重新武装；若此刻条件仍成立，则在**下一次**有效快照触发。每次触发写一条告警，不会重复写同一次触发。

## 有效快照、活跃时段与陈旧

- 交易所时间戳（网关 `quote_time`）**没有前进**的快照视为重复数据，永不参与规则评估；时间戳回退同样忽略。
- 只在 `session == "open"` 时评估规则（`active_windows` 两端都含）；窗口外只更新最新状态，不触发，轮询用 `idle_seconds`。
- `lag_seconds = 本次轮询的墙钟时刻 − 自选股最新交易所时间戳`。多只标的取各自最新时间戳中的**最大者**，因此单只停牌不会把整个面板误判为陈旧；第一次轮询拿到数据之前为 `null`，保留浮点秒不取整。
- 活跃时段内，**任一**条件成立即为陈旧（`stale=true`、`health=stale`，规则评估被抑制）：
  1. 最新交易所时间戳连续**超过** `stale_after_seconds` 没有前进；
  2. 本次拿到了数据，且 `lag_seconds > max_lag_seconds`（**严格大于**，恰好等于不算）。
  两条都不成立才恢复；陈旧期间即使时间戳仍在前进、价格已越过阈值也不会告警，恢复后按正常规则评估。
- 首次快照不再单独与 `stale_after_seconds` 比较：它同样走上面的 `lag_seconds` 判定（周末/节假日拿到旧时间戳会立即陈旧）。
- 非交易日或交易时段之外不判陈旧（即使 `lag_seconds` 很大）；非交易日的 `stale` 恒为 `false`。
- 开闭市由 `calendar` 显式判断，不再依赖"交易所时间戳是否前进"来猜周末/节假日：休市日显示 `trading_day=false`，而不是 `stale=true`。

## 调度与退避

- 所有标的合并为一次请求，每次最多 80 个（配置上限即 80）。
- 基础档 `base_seconds`；任一**已武装**规则距触发线不超过 `hot_band_pct` 个百分点时进入 `fast_seconds`，并在最后一次"临近"后保持 `fast_hold_seconds`。`volume_surge` 不参与"临近"判断。
- 失败（超时、非 200、解析失败）按 `backoff_seconds` 依序退避：第 1 次失败用第 1 项，第 2 次用第 2 项……超出取最后一项；成功一次立即回到基础/快速档。
- `health`：连续失败 1~2 次为 `degraded`，≥3 次为 `down`，成功后回到 `ok`；陈旧时为 `stale`。
- 下一次间隔乘以 `1 ± jitter_pct%` 内的随机数。

## 文件格式（`--out-dir` 下）

- `alerts.jsonl`：追加写，一行一个告警：
  `id`（自增整数）、`ts`（ISO8601 `+08:00`，回放时为模拟时间）、`code`、`name`、`rule_id`、`rule_type`、`direction`（`up`/`down`/`null`）、`price`、`prev_close`、`change_pct`、`vwap`、`limit_up`、`limit_down`、`detail`（触发值与阈值）、`dedupe_key`（`code|rule_id|<触发序号>`）。计划规则告警的 `rule_id` 为 `plan:<id>`、`rule_type` 为 `plan`，并额外带 `severity`（`L1`/`L2`）。
- `polls.jsonl`：每次轮询一行：
  `{"t", "ok", "mode": "base|fast|backoff|idle", "next_interval", "stale", "health": "ok|degraded|down|stale", "consecutive_failures", "lag_seconds", "max_lag_seconds", "trading_day", "calendar_status"}`。`lag_seconds` 在首次拿到数据前为 `null`。
- `state.json`：原子写入（同目录临时文件写完后 `os.replace`），含每个标的的最新快照与指标、每条规则的 `armed`/`last_fired`、`health`、`mode`、`next_interval`、`updated_at`、`stale`、`trading_day`、`calendar_status`、`session`、`last_rule_eval_ts`、`lag_seconds`、`max_lag_seconds`。
- `watchlist.runtime.json`：运行时增删的自选股列表，如 `["601099.SH"]`，原子替换。只由自选股写接口与计划自动监控维护；`source:"plan"` 的自动加入标记保存在 `plans.runtime.json` 的 `auto_codes` 里，因此不会改变这个列表的格式。名称不落盘，重启后下一轮快照会给 `GET /watchlist` 补上 `name`。**配置文件 `watch.yaml` 永远不会被改写**。
- `rules.runtime.json`：运行时规则层，含 `rules`（运行时新建/整条替换）、`overrides`（对配置规则的覆盖或禁用）、`history`（审计记录）与 `version`，原子替换。只由规则写接口与该文件自身的规范化维护；**配置文件 `watch.yaml` 永远不会被改写**。
- `plans.runtime.json`：计划规则层，含 `plans`（每个计划的定义、`state`、`since`、逐条 `conds`、`history`、去噪时间）、`auto_codes`（计划自动加入的自选股）与 `version`，原子替换；坏文件按空处理并记 WARNING，不会被自动覆盖。

## HTTP 接口（回环地址）

监听地址始终绑定 `127.0.0.1`（配置写 `localhost` 也一样）。响应头 `Content-Type: application/json; charset=utf-8`。

- `GET /health`：`{status, health, mode, next_interval, consecutive_failures, last_poll_ts, last_exchange_time, stale, trading_day, calendar_status, session, last_rule_eval_ts, lag_seconds, max_lag_seconds, market_context, plan_count}`；`market_context` 为 `{ok, age_s, regime}`
- `GET /state`：与 `state.json` 相同
- `GET /alerts?after_id=N&limit=M`：按 `id` 升序，`limit` 缺省 100、上限 500；`after_id` 也可写作 `since_id`
- `GET /rules`：当前规则（`{"rules": [...], "count": n, "enabled_count": m}`）；每条带 `symbols`（`null` 表示对全部标的生效）与 `source`（`config`/`runtime`/`override`），禁用覆盖还带 `disabled: true`
- `GET /watchlist`：`{"watchlist": [{"code", "name", "source"}], "count": n, "limit": m}`；`source` 为 `config`（来自配置文件）、`runtime`（用户运行时添加）或 `plan`（计划自动加入），`name` 取不到时为 `null`
- `POST /watchlist/add`：body `{"code": "601099"}`，成功返回 `{"ok": true, "status": "added", "code": "601099.SH", "name": "太平洋", "source": "runtime", ...}`；重复添加是幂等的，返回 `"status": "already_present"`
- `POST /watchlist/remove`：body `{"code": "601099.SH"}`；只能删除 `runtime` 来源的标的，成功返回 `"status": "removed"`，本就不存在时返回 `"status": "not_present"`
- `POST /rules/upsert`、`POST /rules/remove`、`POST /rules/revert`、`GET /rules/history`：运行时规则接口，语义与边界见上面的“运行时规则”；仍只绑回环地址
- `POST /plans/upsert`、`POST /plans/remove`、`GET /plans`、`GET /plans?id=<id>`：计划规则接口，`actor` 取自 `X-Actor` 并写入日志审计；语义见上面的“计划规则”

写接口仍然只绑回环地址：

- 代码规范化沿用引擎规则：6 位数字按首位推断（`5`/`6`/`9` 为 `.SH`，其余 `.SZ`），也接受显式 `.SH`/`.SZ`；`5xxxxx` 与 `159xxx` 等 ETF 代码同样适用。
- 北交所代码（`92`/`43`/`83`/`87`/`88` 开头或 `.BJ`）一律拒绝；指数代码（如 `399975`）返回 `unsupported_instrument`；其他非法代码也拒绝。
- 添加前必须用引擎当前行情源取到一次真实快照；取不到或名称为空则拒绝，不写入列表。
- 总数上限为 `limits.max_watchlist`（默认 10），超过即拒绝；重复添加不算新增。
- 配置文件声明的标的受保护，不能通过接口删除。
- 增删立即热生效：下一轮轮询开始/停止盯该标的，无需重启。已有标的的快照、规则冷却与告警 `id` 序列不受影响；删除标的不会删除其告警历史。
- 运行时列表在引擎重启后与配置文件合并（去重，配置优先）；文件缺失或损坏按空列表处理并记日志，不会导致引擎崩溃。

错误响应为 `{"ok": false, "code": "...", "message": "...", "error": "..."}`（HTTP 400/409/500），错误码：

| `code` | HTTP | 含义 |
|---|---|---|
| `invalid_symbol` | 400 | 代码格式错误（含非 6 位数字、未知后缀等） |
| `unsupported_market` | 400 | 北交所代码，引擎暂不支持 |
| `unsupported_instrument` | 400 | 指数代码，引擎暂不支持 |
| `quote_unavailable` | 400 | 添加前取不到该代码的行情或名称为空 |
| `watchlist_full` | 409 | 自选股总数已达 `limits.max_watchlist` |
| `protected_symbol` | 409 | 该标的来自配置文件，不能通过接口删除 |
| `persistence_error` | 500 | 无法写入运行时自选股文件 |

规则接口的错误码：`invalid_rule`（字段/类型校验失败）、`invalid_id`（id 不合规）、`out_of_bounds`（阈值超界，响应带允许范围）、`rules_full`（409，规则数达 `limits.max_rules`）、`rule_not_found`（404）、`persistence_error`（500，无法写运行时规则文件）。错误响应同样为 `{"ok": false, "code": "...", "message": "...", "error": "..."}`。

计划接口的错误码：`invalid_plan`（字段/类型/范围校验失败）、`invalid_condition`（条件不合法）、`too_many_conditions`（单组超过 6 条）、`too_many_plans`（计划总数超过 30）、`invalid_symbol`（代码非法/北交所/指数）、`watchlist_full`（计划新增的 code 会超出自选上限）、`not_found`（404，计划不存在）、`persistence_error`（500）。除 `not_found` 外均为 HTTP 400，响应为 `{ok:false, code, message, field?}`。

其余非 GET/POST 请求仍为 405（`Allow: GET, POST`）；未知路径 404。

## 回放格式

`--replay FILE` 每行是：

```json
{"t": "2026-11-03T09:30:00+08:00", "quotes": {"002553.SZ": {"name": "南方精工", "price": 15.2, "prev_close": 15.0, "open": 15.0, "high": 15.2, "low": 15.0, "volume_lots": 1000, "amount_yuan": 1520000.0, "exch_time": "20261103093000", "limit_up": 16.5, "limit_down": 13.5}}}
```

或 `{"t": "...", "error": "timeout"}`。模拟时钟走到 `now` 时返回 `t <= now` 的最近一行；最近一行是 `error` 则本次请求失败。回放在最后一行之后再多跑 10 秒（模拟时间），不真实 sleep。

## 测试

```bash
.venv/bin/python -m pytest -q                 # 默认全部离线
.venv/bin/python -m pytest -q -m network      # 真实联网（默认不跑）
```

## 已知限制

- **数据网关与其上游接口没有任何保证**：可能限流、改字段、停服或返回缺失/脏数据；出现连续失败时引擎只会退避与显示 `down`，不会回退到直连数据源。
- **Level-1 快照，约 3 秒一次**，不是逐笔成交；轮询快于 3 秒不会带来更新的数据，只会缩小发现更新的等待。
- **`weekdays` 会误判调休**：法定节假日落在周一至周五时仍被当作交易日，调休补班的周末仍被当作休市。需要精确判断时用 `source: file` 或 `source: akshare`。
- **`file` 需要外部维护**：数组必须列出**所有**交易日（漏写的日期会被当成休市），每年/每次调休后都要更新；生成器不在本包内。
- **`akshare` 依赖第三方接口**：刷新失败且没有可用磁盘缓存时退化为 `weekdays` 并把 `calendar_status` 标为 `degraded`，此时仍有上面的 `weekdays` 调休误判；缓存文件本身也可能过期。
- **`lag_seconds` 依赖本机墙钟**：它等于本机注入时钟与交易所时间戳之差，本机时钟偏差会直接进入陈旧判定；引擎不做 NTP 校准或时钟漂移检测。
- **未做推送**：不接飞书/Telegram/邮件，只在本地文件与 `127.0.0.1` 接口可见；`--serve` 也只是回环接口，自选股写接口不改变这一点。
- 成交额第 37 字段以万元四舍五入；VWAP 优先用第 35 字段的精确元值，只有缺失时才退回第 37 字段，后者会有精度损失。
- 多个标的共用一次请求；只要整次请求失败（超时/非 200/完全无法解析）就整体退避，不区分是哪个代码导致的。
- **只支持个股与 ETF**：指数、可转债、北交所等品种没有专门的行情/规则适配；指数代码在配置和运行时都会被拒绝。
- ETF 的涨跌停价同样取自网关的 `limit_up`/`limit_down`；数据源缺失这两个字段时，`limit_proximity` 对该标的自动跳过（与个股一致）。
- 进程重启后规则状态从 `alerts.jsonl` 恢复最后触发时间与序号，但"自触发以来是否回撤"需要重新观察。
