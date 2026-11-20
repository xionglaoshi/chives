# profile-mcp

本地的用户投资画像 MCP 服务器（stdio），暴露三个工具：`profile_get`、`profile_update`、`profile_clear`。画像保存在本机 JSON 文件里，并渲染成用户全局 `AGENTS.md` 中一个**受管区块**；dsh 的 `agent-instructions` 插件会在**每个新会话的第一条请求**里加载 `$DSH_HOME/AGENTS.md`，所以新会话自动带上画像，不需要智能体每次再调工具读取。

- 入口：`python -m profile_mcp`（stdio MCP 服务器），或安装后的 `profile-mcp`
- Python 3.12
- 依赖只有 `mcp`；不联网、不读密钥、不执行子进程
- 日志只写 stderr，stdout 只承载 MCP 协议

## 安装与运行

```bash
cd packages/profile-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m profile_mcp
```

## 目录解析

| 用途 | 环境变量（按优先级） | 缺省 |
|---|---|---|
| 画像 JSON | `DSH_FINANCE_PROFILE_DIR` → `DSH_HOME` | `~/.dsh` |
| `AGENTS.md` | `DSH_HOME` → `DSH_FINANCE_PROFILE_DIR` | `~/.dsh` |

- 画像文件：`<profile_dir>/finance-profile.json`
- 受管区块：`<agents_home>/AGENTS.md`
- 只设置了 `DSH_FINANCE_PROFILE_DIR` 时，两者同目录，避免把测试数据写进真实 `~/.dsh`。
- 目录不存在会创建；画像文件权限 `0600`，新建的 `AGENTS.md` 也是 `0600`；已存在的 `AGENTS.md` 保留原权限。

## 字段表

| 字段 | 类型 / 取值 | 说明 |
|---|---|---|
| `investor_type` | `practitioner` \| `active_retail` \| `long_term` \| `beginner` | 投资者类型 |
| `experience_years` | 0–60 的整数 | 投资经验年数 |
| `risk_level` | `conservative` \| `balanced` \| `aggressive` | 风险偏好 |
| `horizon` | `intraday` \| `days` \| `weeks` \| `months` \| `years` | 持有周期 |
| `markets` | 列表，元素 `cn` \| `us` \| `hk`，≤3 项 | 关注市场 |
| `sectors` | 短字符串列表，每项 ≤30 字，≤10 项 | 关注行业 |
| `styles` | 短字符串列表，每项 ≤30 字，≤10 项 | 投资风格 |
| `asset_classes` | 短字符串列表，每项 ≤30 字，≤10 项 | 资产类别 |
| `capital_range` | `lt_100k` \| `100k_1m` \| `1m_10m` \| `gt_10m` | 资金粗粒度档位（人民币），不存精确金额 |
| `constraints` | 短字符串列表，每项 ≤60 字，≤8 项 | 硬性约束，如“不碰 ST”“不做融资” |
| `research_depth` | `light` \| `adaptive` \| `thorough` | 研究深度 |
| `output_format` | 列表，元素 `chart` \| `file` \| `text`，≤3 项 | 输出偏好（按优先级） |
| `language` | `zh` \| `en` | 输出语言 |
| `agent_preference` | 自由文本 ≤300 字 | 用户原话补充偏好 |

白名单之外的键一律拒绝（`unknown_field`）。列表会去重并保持顺序；重复项不会报错。

## 工具

### `profile_get()`

无参数。返回：

```json
{
  "ok": true,
  "source": "profile",
  "as_of": "2026-11-03T02:00:00+00:00",
  "status": "ready",
  "data": {
    "profile": {"language": "zh", "risk_level": "balanced"},
    "fields": {"language": "zh", "risk_level": "balanced"},
    "timestamps": {"language": "2026-11-03", "risk_level": "2026-11-03"},
    "field_records": {"language": {"value": "zh", "updated_at": "2026-11-03"}},
    "updated_at": "2026-11-03T02:00:00+00:00",
    "empty": false
  },
  "warnings": []
}
```

没有画像时 `status: "empty"`、`data.profile` 为 `{}`，并带 `data.hint`。`fields` 与 `profile` 相同，只是别名；`field_records` 是“字段 → {value, updated_at}”。`timestamps` 是每个字段最后一次写入的 ISO 日期；`updated_at` 是整个画像最后一次变更的 ISO 时间戳。文件损坏时按空画像处理，`warnings` 里给 `profile_corrupt`。

### `profile_update(fields)`

参数 `fields` 是一个“字段名 → 值”的对象，至少一个字段。**只在用户本人在对话里说明偏好、或明确要求“记住”时才调用**；不要根据对话自行推断写入。返回 `before` / `after` 方便智能体向用户复述：

```json
{
  "data": {
    "before": {"risk_level": "balanced"},
    "after": {"risk_level": "aggressive"},
    "changed": ["risk_level"],
    "timestamps": {"risk_level": "2026-11-03"},
    "updated_at": "2026-11-03T02:05:00+00:00",
    "empty": false,
    "agents_md": {"path": "/home/me/.dsh/AGENTS.md", "status": "updated", "bytes": 412}
  }
}
```

`agents_md.status`：`created` / `updated` / `unchanged` / `removed` / `skipped` / `failed`。校验失败时整次更新都不落盘（要么全写、要么不写）。

### `profile_clear(fields?)`

- 不传 `fields`（或传 `null`）：清空全部
- `fields` 为字段名列表：只清这些；空列表表示不清任何字段
- 未知字段名 → `unknown_field`

返回 `before` / `after` / `cleared`，以及同样的 `agents_md` 信息。

## 统一的返回信封

```json
{
  "ok": true,
  "source": "profile",
  "as_of": "2026-11-03T02:00:00+00:00",
  "status": "ready",
  "data": {},
  "warnings": []
}
```

- `status`：`ready`（有数据/操作成功）、`empty`（还没有画像）、`error`
- 出错时 `ok:false`，并带 `error: {"code", "message"}`；参数错误不会抛 MCP 协议错误
- `warnings` 永远存在，元素是警告码字符串（如 `agents_md_markers_broken`）；需要人读原因时看同级的 `warning_details`（`{"code", "message"}` 列表，只在有警告时出现）

## `AGENTS.md` 受管区块

更新或清空画像后，会把画像渲染成下面两个标记行之间的区块（清空后区块被移除）：

```
<!-- dsh-finance:profile:start -->
## 用户画像（Chives）

以下是用户自己在对话中说明的偏好；给分析和建议时要考虑，行情与持仓等易变事实使用前以当前数据为准；若与用户当前对话冲突，以当前对话为准。

- 投资者类型 (investor_type): long_term
- 关注行业 (sectors): "半导体"、"电力设备"
- 补充偏好 (agent_preference): "多给我反方证据。"
<!-- dsh-finance:profile:end -->
```

规则：

- 文件不存在则创建；存在则**只替换标记之间**，其余内容逐字保留；没有区块则追加到末尾。
- 区块超过 **2 KB**（上限 2000 字节）时，从末尾整条省略字段并加一行说明，两个标记和固定说明始终保留。
- 标记被破坏（只有其中一个、顺序颠倒、重复）时**不修改文件**，返回 `agents_md_markers_broken` 警告；画像本身仍然保存。
- 文件不是 UTF-8 或不可读时不修改，返回 `agents_md_unreadable`。
- 写入是原子的（同目录临时文件 + `os.replace`），并复用原文件权限。

## 安全设计

画像会进入每个会话的系统级上下文，所以按“不可信输入”处理：

1. **白名单**：只接受上表 14 个字段；未知键整次拒绝。
2. **清洗**：自由文本写入前去掉换行、控制字符与零宽字符、`<`、`>`、反引号，去掉行首 `#` 标题记号，压缩空白。
3. **指令注入拒绝**（`suspicious_text`）：40 余个中英文模式，覆盖 “ignore previous / disregard the above / system prompt / you are now / jailbreak / 忽略以上 / 忘记之前 / 系统提示 / 你现在是 / 跳过限制 / 无限制模式” 等。
4. **敏感信息拒绝**（`sensitive_text`）：连续 ≥11 位数字、`sk-`、`api_key`/`apikey`、`password`/`passwd`/`密码`、`token`、`secret`、`cookie`、邮箱、18 位身份证形态。
5. **渲染为数据**：用户文本一律包在双引号里，只作为列表项出现；标记与固定说明由服务器生成，用户无法写入。
6. **最小权限**：画像 JSON 与新建 `AGENTS.md` 为 `0600`；不读任何凭据文件；工具不接受路径参数；整个包不 `subprocess`/`exec`/联网。
7. **损坏即空**：无法解析的 JSON、形状不符或存有非法值的文件按空画像处理并给 `profile_corrupt` 警告，不崩溃。

`capital_range` 只存粗档位，工具描述明确要求不要询问或保存精确金额。

## 已知限制

- **只在新会话生效**：受管区块由 `agent-instructions` 在会话第一条请求时载入，因此当前会话的智能体不会自动感知新画像，必须依赖 `profile_update` 返回的 `after` 和对话上下文。
- 同一台机器多个 dsh 会话共享同一份画像；没有按项目/按用户的多画像。
- 并发写入用 `fcntl.flock` 串行化（POSIX；Windows 不支持）。
- 自由文本清洗是启发式的：能挡住明显的注入与敏感信息，不能保证穷尽。
- 画像不会自动过期；`updated_at` / `timestamps` 只是记录时间，不做陈旧判断。
- 不校验 `AGENTS.md` 里区块之外的内容，也不会整理区块外的重复说明。

## 测试

```bash
cd packages/profile-mcp
.venv/bin/python -m pytest -q
```

测试完全离线，且只使用包内临时目录：字段校验与非法值、注入/敏感样例、清洗、区块渲染（保留原文、替换而非追加、标记破坏不改文件、空画像移除、2 KB 上限、原子写与 0600）、损坏 JSON 容错、`profile_clear` 部分/全部、多进程并发更新不丢字段、目录解析优先级。测试不会读写真实 `~/.dsh`。
