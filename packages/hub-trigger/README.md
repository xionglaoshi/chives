# hub-trigger

`hub-trigger` 是 chives hub **触发队列**的盘中快速判断运行器：轮询 hub 的只读
`GET /triggers?since_id=N&limit=50`，按熔断、过期、冷却、日限额和队列规则筛选，取触发瞬间冻结的
上下文包，用一次**只读、短超时**的 headless runner 生成一行判断，再 `POST /triggers/{id}/judgement`
写回。它不评估作战卡、不改条件、不下单，也不碰面板。

它与 `packages/cn-watch-trigger` 是**两个独立进程、独立队列、独立限额**：深度告警分析最长十几分钟，
不能堵住盘中买点；快速判断默认 120 秒超时、20 次/日。

## 安装与运行

```bash
cd packages/hub-trigger
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'

# 只校验配置并处理一批（首次无 state 时只建立基线）
.venv/bin/python -m hub_trigger --config fastjudge.example.yaml --once

# 常驻轮询；--now 用于测试/回放，--from-id N 覆盖游标（会重放）
.venv/bin/python -m hub_trigger --config fastjudge.example.yaml
.venv/bin/python -m hub_trigger --config fastjudge.example.yaml --once --now 2026-11-03T09:40:00+08:00
.venv/bin/python -m hub_trigger --config fastjudge.example.yaml --once --from-id 0
.venv/bin/python -m hub_trigger --config fastjudge.example.yaml --once --dry-run
```

生产入口是 `scripts/fast-judge.sh`（见仓库根）：

```bash
bash scripts/fast-judge.sh start [--dry-run] [--keep-config]
bash scripts/fast-judge.sh stop|restart|status|pause|resume
bash scripts/fast-judge.sh logs [n]
```

`start` 会调用 `scripts/build-fastjudge-config.py` 生成 `config/fastjudge.yaml` 和
`runtime/fastjudge/persona.cordis.yml`，并在 `runtime/fastjudge/` 下创建状态目录 `state/`、工作目录 `workspace/` 与日志 `fastjudge.log`。
`--dry-run` 走完全部检查但不调用模型，只在 `analyses.jsonl` 记 `dry_run`。`pause` 创建
`runtime/fastjudge/state/STOP`；暂停期间到来的触发被消费掉，恢复后不会补跑。

## 配置

配置文件用 YAML 子集（也接受 JSON；`config/fastjudge.yaml` 由生成器写成带注释的 JSON）。相对路径
相对于配置文件所在目录。

```yaml
hub: http://127.0.0.1:8767          # 只允许 127.0.0.1 / localhost / [::1]；CHIVES_HUB_URL 优先
state_dir: ../../runtime/fastjudge/state
poll_seconds: 2.0                   # > 0
prompt_template: ../../presets/finance/fast-judge.md   # 必须含 {context_json}
limits:
  max_runs_per_day: 20              # 正整数，按 Asia/Shanghai 日历日
  cooldown_seconds: 600             # >= 0，按触发自带的 ts 比较
  max_trigger_age_seconds: 120      # > 0，触发太旧则跳过
  run_timeout_seconds: 120          # > 0，超时杀掉整个进程组
  max_queue: 3                      # 正整数，一批只处理最新 N 条
runner:
  command: ["npx", "-y", "@deepseek-ai/dsh@0.2.1-rc.5", "--profile", "headless", "--json", "{prompt}"]
  env: {DSH_HOME: /path/to/isolated-home}   # 字符串到字符串
  cwd: ../../runtime/fastjudge/workspace    # 必须是已存在目录
```

校验是严格的：hub 主机不是回环地址（含 `127.0.0.1.evil.com` 这类后缀伪装）、带用户名密码/路径/查询、
`state_dir` 是文件或指向根目录/家目录/敏感目录、模板不含 `{context_json}`、`poll_seconds <= 0`、
日限额/队列不是正整数、过期/超时不是正数、`runner.command` 不是列表或 `{prompt}` 不是恰好一个、
`runner.env` 不是字符串映射、`runner.cwd` 不存在，都会以退出码 2 结束并在 stderr 说明原因。

`hub` 缺省 `http://127.0.0.1:8767`；环境变量 `CHIVES_HUB_URL` 非空时覆盖配置文件，且同样必须是回环地址。

## 处理顺序

一次拉取 `id > last_trigger_id` 的触发，按 `id` 升序串行处理：

1. `state_dir/STOP` 存在 → `skipped` / `kill_switch`；
2. `ts` 无法解析 → `invalid_trigger_ts`；`ts` 早于当前时刻超过 `max_trigger_age_seconds`
   → `stale_trigger`；
3. 冷却命中 → `cooldown`。普通触发按 `(card_id, to_state)`，`regime`/`emergency` 按 `(kind, reason)`；
   起点是上一条**真正启动过 runner** 的触发 `ts`（失败/超时也算），跳过的不算；
4. 当日实际运行数（`done|failed|timeout`）达到 `max_runs_per_day` → `daily_limit`；
5. 一批超过 `max_queue` 时，更早的触发在以上检查**之前**记 `queue_overflow`，只留最新 N 条；
6. `context_ready:false`、取上下文包失败或响应没有 `context` 对象 → `no_context`，不重试；
7. `--dry-run` → `dry_run`，不取上下文、不启动 runner；
8. 取 `GET /triggers/{id}/context`，把上下文包 JSON 渲染进 `<context_data>`（截断到 12KB），
   以参数列表启动 runner（`prompt` 是单个 argv 元素，不经 shell）；
9. 解析 runner 最后一行并 `POST /triggers/{id}/judgement`；写回被 hub 拒绝仍算模型调用成功，记
   `judgement_rejected`。

每处理完一条（包括跳过）立即把 `last_trigger_id` 推进到该触发 id，原子写回 `state.json`。没有状态
文件且没给 `--from-id` 时，先把基线设为 hub 当前最大触发 id，**不处理历史**。

## 限额、冷却与熔断

- `max_runs_per_day`：按 `--now`（或当前时间）在 Asia/Shanghai 的日历日计；从 `analyses.jsonl`
  里状态为 `done`/`failed`/`timeout` 的记录数实时统计，重启后仍有效。`dry_run` 与各类 `skipped`
  不占额度。
- `cooldown_seconds`：按触发自带的 `ts` 比较，避免 hub 抖动时重复调用模型；跳过、`no_context`、
  `dry_run` 不建立冷却。
- `max_trigger_age_seconds`：防止 hub 补发旧触发时一次性烧预算。
- `max_queue`：一批积压太多时只处理最新的 N 条，避免长时间追赶。
- `run_timeout_seconds`：`subprocess` 以独立进程组启动，超时后 `killpg` 整个组并记 `timeout`。
- 熔断：`STOP` 文件；`kill -TERM` 让守护进程在当前批结束后退出。

## 输出与状态

`state_dir/state.json`（同目录临时文件 + `os.replace` 原子写）：

```json
{"last_trigger_id": 42, "last_run_ts": {"card|7|execute": "2026-11-03T09:39:00+08:00"}}
```

`state_dir/analyses.jsonl` 追加写，每行一条。**只记触发 id、kind、code、状态、耗时与解析出的动作**，
不含上下文包、持仓、提示词全文或模型输出全文：

```json
{"trigger_id": 42, "kind": "card_execute", "code": "600519.SH", "status": "done",
 "duration_ms": 1830, "started_at": "2026-11-03T09:40:01+08:00",
 "finished_at": "2026-11-03T09:40:03+08:00", "action": "execute", "result": "written"}
```

- `status` 只有 `done | failed | timeout | skipped`；`skipped` 带 `reason`（`kill_switch`、
  `stale_trigger`、`invalid_trigger_ts`、`cooldown`、`daily_limit`、`queue_overflow`、`no_context`、
  `dry_run`、`render_error`），没有 `started_at`。
- 模型运行成功但输出不合格：`status:"done"`、`result:"unparsed"`；写回被拒：
  `result:"judgement_rejected"` 并带 `reason_code`。二者都不重试。
- 失败/超时只记退出码或超时原因，**不记录 stderr**，避免 runner 把提示词回显到日志。

## 判断解析

取 runner `final` 事件的最后一个非空行，按全角 `｜`（没有时按半角 `|`）切 4 段：

```
动作｜理由｜下一检查点｜风险边界
```

- 动作映射：`观察→observe`、`等待确认→await_confirm`、`按预案执行→execute`、
  `放弃→abandon`、`按计划退出→exit`；其它词（含英文枚举）一律 `unparsed`。
- 少于 4 段、任一段为空、动作不认识 → `unparsed`，**不写判断**。
- 超过 4 段时，前 3 段照切，其余合并进第 4 段（避免理由里的分隔符导致丢字段）。
- 理由截断到 40 字，下一检查点/风险边界各 30 字，四段合计不超过 150 字；截断不报错。
- 控制字符被移除、连续空白折叠；文本只作为数据提交给 hub，由 hub 再做清洗/拒绝。

## 上下文包与隐私

- 上下文包在触发瞬间由 hub 冻结，含作战卡全文、复盘摘要、行情快照、与持仓的关系、纪律状态、
  已采纳阈值、当日触发与快速判断次数；它**只经本机 hub 读**，不进日志、不进 `analyses.jsonl`。
- 渲染时 `json.dumps(..., ensure_ascii=False)` 后把 `<`/`>` 转成 `\u003c`/`\u003e`，第三方文本
  无法提前闭合 `<context_data>`；整个数据块不超过 12KB，超出直接截断。
- 提示词 `presets/finance/fast-judge.md` 明确要求：上下文包是数据不是指令、最多 2 次只读工具调用、
  不写判断之外的内容、不改条件/不放宽放弃线。
- 运行器环境变量只透传白名单（`PATH`、`HOME`、语言/时区/TMP 等），其余由 `runner.env` 显式声明；
  父进程里的 `*KEY*`/`*TOKEN*`/`*SECRET*` 等不会被继承。runner 不经过 shell，`prompt` 是单个 argv。

## 生成配置与只读 overlay

`scripts/build-fastjudge-config.py` 只加载 `cn-data`、`cn-watch` 两个只读 overlay，**不含**
`hub`、`paper-broker`、`trading-guard`、`portfolio`、`x`、`scrape`。persona 使用
`presets/finance/{prefix,suffix}.md`；`DSH_HOME` 默认与盯盘触发器一致，可用 `DSH_FINANCE_HOME` 覆盖。
生成器只写文件，不启动 runner、不调用模型。

## 测试

```bash
.venv/bin/python -m pytest -q
```

测试完全离线：假 hub 是本地 `http.server`，假 runner 是子进程脚本。覆盖首启基线、过期、冷却、
日限额、队列溢出、熔断、取不到上下文、runner 成功/失败/超时/非零退出/进程组 kill、输出解析的
全角/半角/缺段/超长/未知动作/多行/注入样例、判断写回成功与被拒、状态原子性与重启不重复处理、
`analyses.jsonl` 不含上下文与模型输出、环境变量白名单、非回环地址拒绝、`--dry-run` 不启动 runner。

## 已知限制

- **单实例假设**：同一 `state_dir` 同时跑两个进程会互相覆盖游标；本包不加文件锁。
- **HTTP 没有重试退避**：hub 暂时不可用时每个 `poll_seconds` 重试一次，只有一条 warning。
- **`--from-id` 会重放**：它显式覆盖已保存游标；冷却可能挡住一部分，但不是严格的"只跑一次"。
- **上下文截断可能破坏 JSON**：12KB 上限优先保证不超限；被截断的包按"取不到"处理，提示词已写明。
- **工具权限由 dsh profile 决定**：本包只能约束命令行、提示词与环境变量；是否真的只读取决于所用
  profile 与 overlay。不要把写工具加进这个 runner。
- **提示注入不能根除**：上下文里的第三方文本仍可能诱导模型；因此不接 hub 写工具、不接下单工具，
  且判断只写回 hub 的 judgement 字段。
