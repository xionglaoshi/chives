# cn-watch-trigger

`cn-watch-trigger` 是 `chives-radar` 盯盘引擎的**告警触发分析守护进程**：轮询引擎的只读 `GET /alerts?after_id=&limit=`，按规则筛选、限流、去重，对选中的告警用 `dsh --profile headless --json` 跑一次**只读**分析，把结果写成 Markdown 并追加一条 JSONL 记录。计划规则（`rule_type:"plan"`）的告警总是记 `skipped`/`plan_alert`，交给 hub 的触发队列，避免两条队列重复分析。它不碰面板、不改引擎、不接任何下单工具。

## 为什么只读

- 对引擎只发 `GET /alerts`，没有任何写接口；本包没有下单、转账或券商连接代码。
- runner 的提示词来自验收者维护的 `presets/finance/alert-analysis.md`，其中明确要求不下单、不调用 `paper_` 开头的工具、不给买卖指令。
- `runner.command` 只允许一个 `{prompt}` 占位符，提示词作为**单个 argv 元素**传入；示例配置不含 `paper_broker`、`trading-guard` 相关配置；runner 命令里也不会出现这两类参数。
- 本包不读取任何凭据、token 或 dsh 的家目录内容；runner 的环境变量会先去掉名字含 `KEY`/`TOKEN`/`SECRET`/`PASSWORD` 的项（大小写不敏感），再叠加 `runner.env`。
- 告警字段按 `json.dumps(..., ensure_ascii=False, indent=2)` 嵌入模板的 `{alert_json}`；序列化结果里的 `<`/`>` 会写成 `\u003c`/`\u003e`，解析后字段值不变，但第三方文本无法提前闭合 `<alert_data>` 数据块。

## 安装与运行

```bash
cd packages/cn-watch-trigger
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'

# 只校验配置后退出（失败退出码 2）
.venv/bin/python -m cn_watch_trigger --config trigger.example.yaml --once --dry-run

# 处理一批后退出；首次启动没有 state 且没给 --from-id 时只建立基线，不分析历史
.venv/bin/python -m cn_watch_trigger --config trigger.example.yaml --once

# 常驻轮询
.venv/bin/python -m cn_watch_trigger --config trigger.example.yaml
```

所有日志写 stderr；stdout 不输出业务内容。`--now ISO8601` 用指定时刻代替墙钟（测试/回放用），`--from-id N` 从 `id > N` 开始并**覆盖**已保存的游标（可重放），`--dry-run` 走完全部检查但不启动 runner。

## 配置

```yaml
engine: http://127.0.0.1:8765        # 主机必须是 127.0.0.1 / localhost / [::1]
state_dir: runtime/watch/analyses     # 相对路径相对于配置文件所在目录
poll_seconds: 3.0                     # > 0
prompt_template: ../presets/finance/alert-analysis.md   # 必须含 {alert_json}
triggers:                             # 非空；告警匹配任一项即选中
  - {rule_ids: ["pct_up_3"], codes: ["*"]}
limits:
  max_runs_per_day: 20                # 正整数；按 --now（或当前时间）的 Asia/Shanghai 日历日
  cooldown_seconds: 1800              # >= 0；同一 (code, rule_id) 按告警 ts 比较
  max_alert_age_seconds: 300          # > 0；告警太旧则跳过
  run_timeout_seconds: 600            # > 0；超时杀掉整个进程组
  max_queue: 5                        # 正整数；一批只处理最新 N 条
runner:
  command: ["npx", "-y", "@deepseek-ai/dsh@0.2.1-rc.5", "--profile", "headless", "--json", "{prompt}"]
  env: {}                             # 字符串到字符串
  cwd: .                              # 相对路径相对于配置文件所在目录
```

校验是严格的：主机不是回环地址（包括 `127.0.0.1.evil.com` 这类后缀伪装）、模板缺失或不含 `{alert_json}`、`triggers` 为空、`poll_seconds <= 0`、日预算/队列不是正整数、超时/过期不是正数、`command` 不是列表或 `{prompt}` 不是恰好一个，都会以退出码 2 结束并在 stderr 说明原因。

## 处理顺序

一次拉取一批待处理告警，按 `id` 升序串行处理：

1. `state_dir/STOP` 存在 → `skipped` / `kill_switch`；
2. `rule_type == "plan"` 或 `rule_id` 以 `plan:` 开头 → `skipped` / `plan_alert`（计划告警由 hub 的触发队列处理，**不启动 runner、不占日预算、不写冷却**）；
3. 未被 `triggers` 选中 → `not_selected`；
4. `ts` 早于 `now` 超过 `max_alert_age_seconds` → `stale_alert`；
5. 同一 `(code, rule_id)` 距上一条**实际运行**的告警 `ts` 小于 `cooldown_seconds` → `cooldown`；
6. 当日实际运行数达到 `max_runs_per_day` → `daily_limit`；
7. 一批待处理超过 `max_queue` 时，更早的告警在以上检查**之前**记 `queue_overflow`，只留最新 `max_queue` 条；
8. 通过全部检查才运行；`--dry-run` 在这一步记 `dry_run`，不启动 runner。

每处理完一条（包括跳过）立即把 `last_alert_id` 推进到该告警 id，原子写回 `state.json`。没有状态文件且没给 `--from-id` 时，先把基线设为引擎当前最大告警 id，**不分析历史**；`--once` 下打印提示后直接退出 0。

## 预算与熔断

- `max_runs_per_day`：按 `--now`（或当前时间）在 Asia/Shanghai 的日历日计；从 `analyses.jsonl` 里状态为 `done`/`failed`/`timeout` 的记录数实时统计，进程重启后仍然有效。
- `cooldown_seconds`：按告警自带的 `ts` 比较，起点是上一条真正启动过 runner 的告警（失败或超时也算），跳过的不算。
- `max_alert_age_seconds`：防止引擎补发旧告警时一次性烧预算。
- `max_queue`：一批积压太多时只处理最新的 N 条，避免长时间追赶。
- `run_timeout_seconds`：`subprocess` 以独立进程组启动，超时后 `killpg` 整个组，记录 `timeout`。
- 熔断：在 `state_dir` 放一个名为 `STOP` 的文件，下一条告警起全部记 `kill_switch` 并消费掉（不会被重放）；删掉文件后不会补跑已消费的告警。`kill -TERM` 也会让守护进程在当前批结束后退出。

## 输出与状态

`state_dir/state.json`（原子写）：

```json
{"last_alert_id": 5, "last_run_ts": {"002553.SZ|pct_up_3": "2026-11-03T09:33:00+08:00"}}
```

`state_dir/analyses.jsonl` 追加写，每行一条：

```json
{"alert_id": 3, "code": "002553.SZ", "rule_id": "pct_up_3", "status": "done", "started_at": "2026-11-03T09:40:00+08:00", "finished_at": "2026-11-03T09:40:12+08:00", "file": "/abs/path/state/analysis-3.md", "session_id": "..."}
```

`status` 只有 `done | failed | timeout | skipped`；`skipped` 带 `reason`（`kill_switch`、`plan_alert`、`not_selected`、`stale_alert`、`cooldown`、`daily_limit`、`queue_overflow`、`dry_run`、`invalid_alert_ts`）。只有真正启动过 runner 的记录才有 `started_at`/`finished_at`/`file`。

`state_dir/analysis-<alert_id>.md` 先写告警摘要头（id、时间、代码、名称、规则、状态、开始与结束时间、sessionId），再写分析正文；失败或超时写原因。`state.json` 与每个 Markdown 文件都先写同目录临时文件再 `os.replace`；`analyses.jsonl` 只追加。

## 怎么换模型/家目录

- **换模型**：模型由 dsh 的 profile 决定，不由本包决定。把 `runner.command` 的 `--profile headless` 换成你自己的 headless 变体（在 dsh 侧配置好模型），或整体换成等价的 headless 命令；`{prompt}` 必须仍恰好出现一次。
- **换家目录**：在 `runner.env` 里设 `DSH_HOME: /path/to/isolated-home`，让分析会话使用独立家目录，不碰主目录的会话历史。不要在这个家目录里放券商凭据或密钥。
- **换可执行文件**：`command` 的第一个元素可以是任意绝对路径或无参数命令名；本包不做 PATH 解析，也不使用 shell。

## 测试

```bash
.venv/bin/python -m pytest -q
```

测试完全离线：假引擎是本地 `http.server`，假 runner 是子进程脚本；覆盖基线、`--from-id`、去重、触发筛选、冷却、日预算、告警过期、队列溢出、runner 失败/超时、熔断、干跑、提示词内容与数据块隔离（含提示注入样例）、提示词单 argv、环境变量脱敏、非回环地址拒绝。

## 已知限制

- **不接面板、不负责启动**：本任务只做守护进程；面板展示与开机启动是后续任务。
- **单实例假设**：同一 `state_dir` 同时跑两个进程会互相覆盖游标，可能重复分析；本包不加文件锁。
- **runner 的工具权限由 dsh profile 决定**：本包只能约束命令行、提示词和环境变量，不能给 dsh 内部加工具白名单；分析是否真的只读取决于所用 profile 和提示词。
- **提示注入不能根除**：告警里的 `name` 等字段作为第三方数据放进 `<alert_data>` 数据块，模板明确要求“只当数据”，但模型仍可能被绕过；不要给分析 profile 任何下单权限。
- **`--from-id` 会重放**：它显式覆盖已保存游标；冷却可能挡住一部分，但不是严格的“只跑一次”保证。
- **HTTP 没有重试退避**：引擎暂时不可用时每个 `poll_seconds` 重试一次，只有一条 warning 日志。
- **`--now` 会冻结时间戳**：测试/回放时 `started_at`/`finished_at` 等于该时刻，不是真实墙钟。
- **没有推送**：结果只落盘，不接飞书/Telegram/邮件。
