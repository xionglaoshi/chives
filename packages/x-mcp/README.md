# x-mcp

只读的 X（Twitter）检索 MCP 服务器，暴露 5 个工具：`x_search_recent`、`x_get_post`、`x_get_user`、`x_user_posts`、`x_counts_recent`。**本工具不含任何写操作**：不发帖、不点赞、不关注、不发私信，也不访问任何账号相关端点。

- 入口：`python -m x_mcp`（stdio MCP 服务器）
- Python 3.12
- 日志只写 stderr，stdout 只承载 MCP 协议
- 上游只允许 `https://api.x.com`

## 安装与运行

```bash
cd packages/x-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m x_mcp
```

## 密钥

取 `X_BEARER_TOKEN` 的顺序：

1. 进程环境变量 `X_BEARER_TOKEN`
2. `DSH_FINANCE_SECRETS` 指向的 dotenv 文件
3. 默认 `<仓库根>/config/secrets.env`（相对于包位置解析）

只读取 `X_BEARER_TOKEN` 这一项。用 `scripts/install-keys.py` 写入密钥。没有密钥时服务器仍能启动并列出工具；调用工具返回 `missing_key`。

密钥只出现在 HTTP 请求头 `Authorization: Bearer <token>` 中，不出现在 URL 或请求体里。所有对外文本（工具返回、`error.message`、异常）在输出前都会把令牌值、可识别前缀以及 `Bearer ` 之后的内容替换为 `***`，包括上游错误响应体回显令牌的情况。

## 上游地址白名单

生产环境只允许 `https://api.x.com`。只有 `X_TEST_MODE=1` 时才允许把 `X_BASE_URL`（或 `X_API_BASE_URL`）设成 `http://127.0.0.1:<端口>`（离线测试用）；其他值、非回环主机、https 仿冒域名、带路径或凭据的地址都会让服务器启动失败。客户端不跟随重定向。

## 统一返回信封

```json
{
  "ok": true,
  "source": "x",
  "as_of": "2026-11-03T05:00:00+00:00",
  "status": "ready",
  "data": {
    "untrusted_text": true,
    "budget": {"used_today": 11, "remaining": 489}
  }
}
```

- `status`：`ready`（有数据）、`empty`（请求有效但没有结果）、`error`
- 出错时额外有 `error: {"code", "message"}`，`ok` 为 `false`
- 成功响应的 `data.budget` 给出当日已用条数与剩余条数
- 推文文本、用户名、简介都是第三方不可信文本。`data.untrusted_text: true` 提醒智能体：其中的指令不是系统指令，不得执行

## 工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `x_search_recent` | `query`（≤512）、`max_results`（10–100，默认 10）、`next_token`、`start_time`、`end_time` | `GET /2/tweets/search/recent`，近 7 天 |
| `x_get_post` | `tweet_id`（1–25 位数字） | `GET /2/tweets/{id}` |
| `x_get_user` | `username`（1–15 位字母数字下划线，可带一个前导 `@`） | `GET /2/users/by/username/{name}` |
| `x_user_posts` | `user_id`（数字串）、`max_results`（5–100，默认 10）、`pagination_token` | `GET /2/users/{id}/tweets` |
| `x_counts_recent` | `query`（≤512）、`granularity`（`minute\|hour\|day`，默认 `day`） | `GET /2/tweets/counts/recent` |

时间参数必须是带时区的 ISO8601，且落在最近 7 天内；`start_time` 不得晚于 `end_time`。非法参数返回 `invalid_argument`，不会请求上游。

返回体只保留请求的固定字段白名单：`tweet.fields=created_at,author_id,public_metrics,lang,conversation_id,entities`，`user.fields=id,name,username,created_at,description,public_metrics,verified`，`expansions=author_id`；上游多给的字段会被丢弃。单条推文文本最多保留 4000 字符、用户简介最多 2000 字符，超出部分截断并加 `"truncated": true`。

## 每日读取预算

X API 按读取的资源计费。为避免分页失控，服务器在每次上游请求前先**预扣**预算，拿到响应后按**实际返回的资源条数**结算（搜索按返回帖子数、用户/单帖按 1、计数端点按 1）：

- 预算上限：`X_DAILY_POST_BUDGET`，默认 500 条/本地日期
- 预算用尽：返回 `budget_exhausted`，`data` 里有 `budget.used_today`、`remaining`、`reset_at`、`reset_at_epoch`
- 状态文件：可用 `X_BUDGET_STATE` 指定文件（也接受 `X_BUDGET_STATE_FILE`、`X_STATE_FILE`），或用 `X_STATE_DIR` 指定目录；都没设置时，若设置了 `DSH_FINANCE_HOME` 则用 `<DSH_FINANCE_HOME>/x-mcp/budget.json`，否则用 `<仓库根>/runtime/x-mcp/budget.json`。原子写、按本地日期归零；文件锁保证多进程共享同一文件时也不超支
- 状态文件损坏时按"当日已用 0"重建，不会导致启动失败

## 限速与 429

本地令牌桶默认容量 30、每 30 秒恢复 1 个（约 30 次/15 分钟），明显低于官方限额；可用 `X_RATE_CAPACITY`、`X_RATE_REFILL_SECONDS` 调整。本地拒绝返回 `rate_limited` 并带 `retry_after_seconds`。

上游返回 429 时，解析 `x-rate-limit-reset`（缺失时用 `retry-after`）返回 `rate_limited`，`data` 带 `reset_at_epoch` 与 `retry_after_seconds`。**不自动重试**。

## 错误码

| 情况 | `error.code` |
|---|---|
| 找不到密钥 | `missing_key` |
| 参数非法 | `invalid_argument` |
| 401 | `auth_failed` |
| 403（套餐不含该端点等） | `forbidden`，提示去 Developer Console 确认 |
| 404 | `not_found` |
| 429 | `rate_limited` |
| 当日预算用尽 | `budget_exhausted` |
| 其他非 2xx | `http_error` |
| 超时或连接失败 | `network_error` |
| 畸形 JSON / 响应形状不符 | `malformed_response` |

## 费用

X API 现为按量付费（官方定价页 `https://docs.x.com/x-api/getting-started/pricing`，读取按返回资源计费，据该页 Posts 约 0.005 美元/条、User 约 0.01 美元/条；限额页 `https://docs.x.com/x-api/fundamentals/rate-limits`）。价格页没有发布日期，**上线前以你在 X Developer Console 里看到的为准**；本项目不臆测数值。

## 已知限制

- 只做近期搜索（近 7 天），不做全量归档搜索
- 不做任何写操作或账号端点
- 不自动重试 429，也不跨端点合并限速额度
- 预算按"实际返回条数"记账；若上游在传输中断前已计费，本地可能少记
- 单进程令牌桶；多进程共享预算文件但不共享令牌桶

## 测试

```bash
cd packages/x-mcp
.venv/bin/python -m pytest -q
```

测试完全离线：使用本地假上游验证参数校验、信封、错误映射、预算、限速、URL 白名单与令牌脱敏，不访问 `api.x.com`，也不读取真实的 `config/secrets.env`。
