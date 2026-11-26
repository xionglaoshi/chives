# hub-mcp

chives-signals 的本机 stdio MCP 客户端。它只连回环地址上的 hub（默认 `http://127.0.0.1:8767`），把信号读成精简卡片，把智能体的“到价提醒 / 不再跟”变成**待用户确认**的计划，并为复盘/盘前提供数据包、结构化复盘、设置建议与作战卡。

- 入口：`python -m hub_mcp`（stdio MCP 服务器），或安装后的 `hub-mcp`
- Python 3.12；依赖只有 `mcp`，HTTP 客户端用标准库
- 环境变量：
  - `CHIVES_HUB_URL`（缺省 `http://127.0.0.1:8767`，必须是回环地址，否则启动失败）
  - `HUB_MCP_PROFILE`（缺省 `agent`；只接受 `agent` / `readonly`，其它值启动失败退出码 2）
- **没有任何** confirm/tighten_stop/set_state、信号 action、判断回写、触发队列或交易工具；包内不使用 `subprocess/exec/eval`

## 安装与运行

```bash
cd packages/hub-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m hub_mcp
```

## 工具集合按 profile 限制

| profile | 工具数 | 内容 |
|---|---|---|
| `agent`（默认） | 14 | 下列 5 个 v1 工具 + 9 个 v2 工具 |
| `readonly` | 8 | `hub_list_signals`、`hub_get_signal`、`hub_list_plans`、`hub_get_review_data`、`hub_list_settings`、`hub_list_cards`、`hub_get_card`、`hub_candidate_stats` |

### v1：信号、计划

| 工具 | 读/写 | 说明 |
|---|---|---|
| `hub_list_signals(status="active", decide=None, limit=20)` | 读 | 只返回 id、ts、kind、object、title、direction、conclusion、brief、status |
| `hub_get_signal(id)` | 读 | 返回信号与分析的 conclusion/direction/points/detail；detail 截断到 4000 字，并标 `untrusted_text: true` |
| `hub_list_plans(status="all")` | 读 | 计划列表与各状态计数 |
| `hub_propose_plan(code, kind, condition, rationale, stop=None, expires_in_days=5, analysis_id=None)` | 写 | 固定以 `proposed_by:"agent"` 提交，落库为 `status:"proposed"`；参数里没有 proposed_by/status |
| `hub_cancel_plan(id)` | 写 | 仅当计划 `proposed_by=="agent"` 且 `status=="proposed"` 时取消 |

`hub_propose_plan` 只接受 A 股股票与场内基金代码，规范为 `NNNNNN.SH/.SZ/.BJ`；`condition` 只接受契约里的三种形状：

```json
{"type": "price_cross", "direction": "up|down", "level": 9.50}
{"type": "price_in_range", "lo": 9.20, "hi": 9.80}
{"type": "pct_change", "direction": "up|down", "threshold_pct": 3.0}
```

`rationale` ≤200 字，按 profile-mcp 的口径清洗并拒绝指令式文本、疑似密钥/账号形态数字串；`expires_in_days` 1–30。提交成功返回：

```json
{"ok": true, "plan": {"id": 12, "status": "proposed", "...": "..."},
 "status": "proposed", "proposed_by": "agent",
 "message": "已提交，等待用户在「盯盘/我的」页确认后才会生效"}
```

计划只产生提醒，**不下单**；只有用户在「盯盘/我的」页确认后才会生效。取消一个用户自己创建或已生效的计划会被拒绝（`not_agent_plan` / `invalid_status`），且不会向 hub 发送任何动作。

### v2：复盘、设置建议、作战卡

| 工具 | 读/写 | 上游 | 说明 |
|---|---|---|---|
| `hub_get_review_data()` | 读 | `GET /review-data` | `trading_day:false` 只回简包；交易日结果 `private:true` + `untrusted_text:true`（含持仓，不写日志） |
| `hub_save_review(review)` | 写 | `POST /reviews` | 参数就是契约里的 review 对象；本地按同一 schema 校验（候选 ≤5、字段长度、多余字段、kind、日期）后再请求；成功返回 `{ok,date,kind,revision}` |
| `hub_list_settings()` | 读 | `GET /settings` | 11 项设置的值/来源/待采纳建议 |
| `hub_suggest_setting(key, value, basis)` | 写建议 | `POST /settings/{key}/suggest` | 只写 suggestion，**永不改 value**；key 白名单 11 项、范围本地校验、`basis` 必填 ≤200 字；返回 `status:"suggested"` |
| `hub_propose_card(card)` | 写 | `POST /cards` | 固定 `proposed_by:"agent"`，落库 `proposed`；本地校验 Cond 白名单/条数/thesis/北交所/止损 |
| `hub_list_cards(status="all", date=None)` | 读 | `GET /cards` | 卡片列表与计数 |
| `hub_get_card(id)` | 读 | `GET /cards/{id}` | 单卡全文，文本不可信 |
| `hub_candidate_stats(days=20)` | 读 | `GET /candidates/stats` | 候选统计，`days` 1–365；`n<30` 标样本不足 |
| `hub_cancel_card(id)` | 写 | 先 `GET /cards/{id}` 再 `POST /cards/{id}/action` | 只能取消自己提议且仍 `proposed` 的卡 |

`hub_save_review` 的 review 字段与限制见 `docs/hub-api.md` 的 Review 节。`hub_propose_card` 的 Cond 白名单为 `regime`、`index_pct`、`sector_change`、`sector_rank`、`price_cross`、`price_in_range`、`pct_change`、`open_pct`、`volume_ratio`；每类 ≤6 条；`risk.stop_price` 必填且必须低于入场参考价、距离 ≤30%；北交所代码被拒绝。提交成功后卡是 `proposed`，**必须用户在「复盘」页确认后才生效**。

### 只写建议，不替用户采纳

`hub_suggest_setting` 只提交建议，采纳/修改/清除/忽略都只能由用户在「复盘」页完成。本包**没有** adopt/set/clear/dismiss 工具；返回里的 `setting.value` 仍是 hub 当前值（未采纳时通常为 `null`），不要对用户说“已设置/已生效”。

## 错误与上限

- hub 不可达、超时：`{"ok":false,"error":{"code":"hub_unreachable"}}`，不抛栈
- 超过 512KB：`response_too_large`；非 JSON：`invalid_response`
- 请求超时 5 秒；启动时校验 `CHIVES_HUB_URL` 为 `127.0.0.1` / `localhost` / `::1`，`HUB_MCP_PROFILE` 为 `agent` / `readonly`
- 参数错误在本地拒绝，不会到达 hub：`invalid_code`、`invalid_kind`、`invalid_condition`、`bad_condition`、`bad_stop`、`too_many_candidates`、`unknown_key`、`bad_value`、`suspicious_text`、`sensitive_text`、`invalid_value`
- 日志只含工具名与异常类型，不含持仓、复盘正文或文本内容

## 测试

```bash
.venv/bin/python -m pytest -q
```

测试只连本地假 hub，不访问公网；覆盖两个 profile 的工具集合、每个新工具的成功/本地拒绝/错误透传/不可达/超大响应，以及“没有 confirm/adopt/set_state/交易工具”的断言。
