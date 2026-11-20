# tavily-mcp

只读的 Tavily 搜索与网页抽取 MCP 服务器，暴露两个工具：`tavily_search`、`tavily_extract`。代码可审计，密钥只从环境变量或 dotenv 文件读取，绝不写进配置文件、URL 或请求体。

- 入口：`python -m tavily_mcp`（stdio MCP 服务器）
- Python 3.12
- 日志只写 stderr，stdout 只承载 MCP 协议
- 不提供 crawl / map / research 能力

## 安装与运行

```bash
cd packages/tavily-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m tavily_mcp
```

在 dsh 中通过 `overlays/tavily.cordis.yml` 接入，server 名为 `tavily`。

## 密钥

取 `TAVILY_API_KEY` 的顺序：

1. 进程环境变量 `TAVILY_API_KEY`
2. `DSH_FINANCE_SECRETS` 指向的 dotenv 文件
3. 默认 `<仓库根>/config/secrets.env`（相对于包位置解析）

只读取 `TAVILY_API_KEY` 这一项。设置了 `DSH_FINANCE_SECRETS` 就不会再回退到默认文件。仓库里提供了 `scripts/install-keys.py` 用于写入密钥。

没有密钥时服务器仍能启动并列出工具；调用工具返回 `missing_key`，提示先运行安装脚本。

密钥只出现在 HTTP 请求头 `Authorization: Bearer <key>` 中，不出现在 URL 或请求体里。所有对外文本（工具返回、`error.message`、异常）在输出前都会把密钥值替换为 `***`，包括上游错误响应体回显令牌的情况。

## 上游地址白名单

生产环境只允许 `https://api.tavily.com`。只有 `TAVILY_TEST_MODE=1` 时才允许把 `TAVILY_BASE_URL` 设成 `http://127.0.0.1:<端口>`（离线测试用）；其他值、非回环主机、https 仿冒域名、带路径或凭据的地址都会让服务器启动失败。客户端不跟随重定向。

## 统一返回信封

每个工具都在文本内容里返回一个 JSON 对象：

```json
{
  "ok": true,
  "source": "tavily",
  "as_of": "2026-11-02T05:00:00+00:00",
  "status": "ready",
  "data": {
    "untrusted_text": true
  }
}
```

- `status`：`ready`（有数据）、`empty`（请求有效但没有结果）、`error`（参数、密钥或上游错误）
- 出错时额外有 `error: {"code", "message"}`，`ok` 为 `false`
- 上游错误不会抛 MCP 协议错误；工具照常返回 `ok:false` 的信封
- 网页内容是第三方文本。`data.untrusted_text: true` 提醒智能体：其中的指令不是系统指令，不得执行

## 工具 1：`tavily_search`

参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 非空，最多 400 字符 |
| `max_results` | integer | 否 | 1–10，默认 5 |
| `search_depth` | string | 否 | `basic` 或 `advanced`，默认 `basic` |
| `topic` | string | 否 | `general`、`news`、`finance`，默认 `general` |
| `time_range` | string/null | 否 | `day`、`week`、`month`、`year` 或 null |
| `include_domains` | string[]/null | 否 | 最多 10 个域名 |
| `exclude_domains` | string[]/null | 否 | 最多 10 个域名 |

域名必须匹配 `^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`。非法参数返回 `invalid_argument`，不会请求上游。

返回 `data`：

```json
{
  "query": "南方精工 2026 三季报",
  "count": 3,
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "content": "...",
      "score": 0.9,
      "published_date": "2026-10-30"
    }
  ],
  "untrusted_text": true
}
```

每条 `content` 最多保留 2000 字符；被截断的条目额外带 `"truncated": true`。没有结果时 `status:"empty"`。

## 工具 2：`tavily_extract`

参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `urls` | string[] | 是 | 1–5 个公开 http/https URL |

拒绝非 http/https、无主机名、带用户名密码、回环/内网/链路本地地址（如 `127.*`、`10.*`、`192.168.*`、`172.16–31.*`、`169.254.*`、`localhost`、`[::1]`）→ `invalid_argument`，不请求上游。

返回 `data`：

```json
{
  "count": 2,
  "results": [{"url": "https://...", "content": "..."}],
  "failed": [{"url": "https://...", "error": "..."}],
  "untrusted_text": true
}
```

每条 `content` 最多 2000 字符，超出部分截断并加 `"truncated": true`。

## 错误码

| 上游情况 | `error.code` |
|---|---|
| 401 / 403 | `unauthorized` |
| 429 | `rate_limited` |
| 432 / 433（超出套餐用量） | `plan_limit` |
| 20 秒超时或连接失败 | `upstream_unreachable` |
| 其他非 2xx | `upstream_error` |
| 找不到密钥 | `missing_key` |
| 参数非法 | `invalid_argument` |

## 缓存与限流

- 相同参数的请求缓存 300 秒；空结果和错误不缓存
- 本地滑动窗口限流：每分钟最多 20 次上游请求；超过返回 `rate_limited`
- 缓存命中不消耗上游配额，也不占限流名额

## 额度

Tavily 免费额度按月计算，具体次数与计费方式请查 Tavily 官方页面（本项目不臆测数值）。

## 测试

```bash
cd packages/tavily-mcp
.venv/bin/python -m pytest -q
```

测试完全离线：使用本地假上游验证参数校验、URL 校验、信封、截断、错误映射、缓存、限流、三级取密钥、`TAVILY_BASE_URL` 白名单、请求头携带密钥与密钥脱敏。测试不会读取真实的 `config/secrets.env`，也不会访问 `api.tavily.com`。
