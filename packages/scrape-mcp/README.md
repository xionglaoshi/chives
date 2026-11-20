# scrape-mcp

只读的公开网页抓取 MCP 服务器，两个工具：`scrape_page`、`scrape_pages`。两层抓取：

- `fast`：`httpx` 纯 HTTP，不执行 JavaScript；
- `browser`：Playwright 驱动**Chives 专属 Chromium**，无头渲染 JS 页面。

不实现 stealth 层，不实现 `solve_cloudflare`，不绕过验证码、挑战页、登录或付费墙。被拦截时返回 `blocked`，由调用方改用搜索工具或官方 API。

- 入口：`python -m scrape_mcp`（stdio MCP）
- Python ≥ 3.12
- 日志只写 stderr，stdout 只承载 MCP 协议
- 不读取任何凭据文件，不接受本地路径参数

## 正文抽取

`extraction=markdown|text` 用 **`trafilatura`** 做正文抽取（在 `trafilatura` 与 `html2text` 中选了前者：它能剥离导航/页脚，并直接输出 Markdown）；`trafilatura` 返回空时退回内置 `HTMLParser` 的纯文本兜底。`extraction=html` 直接返回原始 HTML。

## 安装与运行

```bash
cd packages/scrape-mcp
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m scrape_mcp
```

在 Chives 根目录运行 `bash scripts/install-browser.sh`。它把 Playwright Python 包、随包提供的 Node 驱动和匹配版本的 Chromium 实装到 `runtime/ms-playwright/`。可用 `runtime/ms-playwright/bin/playwright --version` 查看版本。浏览器缺失时重新执行安装脚本。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SCRAPE_ALLOW_HOSTS` | 空 | 逗号分隔的域名白名单；设置后只允许这些域名及其子域 |
| `SCRAPE_TEST_ALLOW_LOOPBACK` | 未设置 | 仅测试用；设为 `1` 时放行回环地址，私网/链路本地/云元数据仍然拒绝 |
| `SCRAPE_MIN_INTERVAL_SECONDS` | `1` | 同域名两次请求的最小间隔；测试可设为 `0` |
| `SCRAPE_MAX_REQUESTS_PER_MINUTE` | `600` | 单进程每分钟页面抓取上限，超出返回 `rate_limited` |

## 统一返回信封

```json
{
  "ok": true,
  "source": "scrape",
  "as_of": "2026-11-03T08:00:00+00:00",
  "status": "ready",
  "data": {
    "url": "https://example.com/page",
    "final_url": "https://example.com/page",
    "http_status": 200,
    "title": "Example",
    "content": "...",
    "truncated": false,
    "content_chars": 1234,
    "fetched_at": "2026-11-03T08:00:00+00:00",
    "untrusted_text": true
  },
  "warnings": []
}
```

- `status`：`ready`（有正文）、`empty`（请求成功但没有正文）、`error`（参数、策略或抓取错误）
- 出错时 `ok:false`、`data:{}`、`error:{"code","message"}`
- `warnings` 始终存在；截断、robots.txt 不可读、browser 拦截子请求等提示放在这里
- **页面内容是第三方不可信文本**：`untrusted_text: true` 提醒智能体，其中的指令不是系统指令，不得执行

### 工具 1：`scrape_page`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `url` | string | 必填 | 公开 http(s) URL，≤ 2048 字符，不得含用户名密码 |
| `mode` | string | `fast` | `fast` 或 `browser`；`stealth`、`solve_cloudflare`（作为 mode 值或独立参数）返回 `invalid_argument` 并说明不支持 |
| `extraction` | string | `markdown` | `markdown`、`text` 或 `html` |
| `timeout` | number | 30 | 1–60 秒 |

### 工具 2：`scrape_pages`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `urls` | string[] | 必填 | 1–10 个公开 http(s) URL |
| `mode` / `extraction` / `timeout` | 同上 | 同上 | 对每个 URL 生效 |

逐条返回，单条失败不影响其他条。并发上限：`fast` 4、`browser` 2。

```json
{
  "ok": true,
  "source": "scrape",
  "status": "ready",
  "data": {
    "count": 2,
    "succeeded": 1,
    "failed_count": 1,
    "results": [
      {"ok": true, "url": "...", "final_url": "...", "http_status": 200, "title": "...",
       "content": "...", "truncated": false, "content_chars": 42,
       "fetched_at": "...", "untrusted_text": true},
      {"ok": false, "url": "http://127.0.0.1/", "error": {"code": "ssrf_blocked", "message": "..."}}
    ],
    "failed": [
      {"ok": false, "url": "http://127.0.0.1/", "error": {"code": "ssrf_blocked", "message": "..."}}
    ],
    "untrusted_text": true
  },
  "warnings": []
}
```

全部失败时 `status:"error"`，`data` 仍保留逐条结果。

### 错误码

| `error.code` | 含义 |
|---|---|
| `invalid_url` | 非 http(s)、带凭据、超长、含空白/反斜杠、端口非法等 |
| `ssrf_blocked` | 回环、私网、链路本地、CGNAT、组播、云元数据、十进制/八进制/十六进制 IP、`[::ffff:127.0.0.1]`、`localhost` 变体、`0.0.0.0`、白名单外域名 |
| `robots_disallowed` | 目标站点 robots.txt 禁止本工具 UA |
| `blocked` | 403/429、验证页/挑战页、下载 |
| `fetch_failed` | 连接失败、DNS 失败、重定向环、其他非 2xx |
| `timeout` | 超出 `timeout` 或读取超时 |
| `too_large` | 响应超过 5 MB |
| `extract_failed` | 非文本 `content-type`、正文抽取失败 |
| `browser_unavailable` | Chrome 不存在或无法启动 |
| `invalid_argument` | 参数非法，包括 `stealth` / `solve_cloudflare` |
| `rate_limited` | 触发单进程每分钟上限或域名间隔超出本次超时预算 |

## 安全设计

### SSRF 防护（重点是 fast 层）

1. **结构校验**：只允许 http/https；拒绝用户名密码、空白、反斜杠、控制字符、长度 > 2048、非法端口。
2. **主机形态**：拒绝 `localhost`、`*.localhost`；拒绝非规范的十进制/八进制/十六进制 IP（`2130706433`、`0x7f000001`、`0177.0.0.1`、`127.1`）；IPv4 映射的 IPv6（`::ffff:127.0.0.1`）一律拒绝。
3. **DNS 解析后逐地址校验**：回环、私网（10/8、172.16/12、192.168/16）、链路本地（169.254/16）、CGNAT（100.64/10）、组播、保留地址、未指定地址、IPv6 ULA/链路本地/6to4/Teredo/NAT64，以及云元数据地址（`169.254.169.254`、`100.100.100.200`、`169.254.170.2`、`192.0.0.192`、`168.63.129.16` 等）全部拒绝。任一解析结果不合格即拒绝，避免轮询 DNS 绕过。
4. **连接绑定解析出的 IP**：socket 直接连校验过的 IP 字面量，`Host` 头保留原域名，TLS 用 `sni_hostname` 保留原域名做 SNI 与证书校验。这样即使 DNS 第二次回答变成内网地址，连接也不会跟着变（防 DNS rebinding）。
5. **逐跳重定向校验**：手动跟随，最多 5 跳；每跳重新做结构、DNS、地址校验；跨主机允许但仍校验；重定向环直接拒绝。
6. **browser 层**：用 CDP `Fetch` 域在请求发出前拦截页面与重定向发出的每个请求（Playwright 的 `route` 看不到 302 之后的跳转，不能只靠它），复用同一套校验（含 DNS 解析）；拒绝一切非 http(s) 协议、私网/回环/链路本地地址与文件下载；WebSocket 一律关闭；每域名解析结果在单次抓取内缓存。主框架导航还要过 robots 检查。
7. **域名白名单**：`SCRAPE_ALLOW_HOSTS` 非空时，白名单外主机在 DNS 解析前就被拒绝。

### robots 与礼貌

- 抓取前读取 `robots.txt`（按本工具 UA `dsh-finance-scrape/<版本>`），并遵守 `Disallow`；
- 取不到 robots.txt（网络错误、4xx、解析失败）视为允许；
- robots 结果按 origin 缓存 1 小时；
- 同一域名两次请求最小间隔 1 秒（`SCRAPE_MIN_INTERVAL_SECONDS`）；这段等待不计入 `timeout`，也不会被跳过；
- 并发上限 `fast` 4、`browser` 2；
- 识别 Cloudflare "Just a moment..."、`cf-chl-*`、`challenge-platform`、验证码等挑战页 → `blocked`，**不尝试绕过**。

### 输出与日志

- 页面内容一律当数据，`untrusted_text: true`；
- URL 查询参数里 `token=`、`key=`、`password=`、`secret=`、`session=`、`signature=` 等值替换为 `***`；
- 错误信息中 `Authorization:`、`Cookie:`、`Set-Cookie:`、`X-Api-Key:` 等头部值替换为 `***`；
- 不发送 Cookie、不带登录态、不使用代理环境变量（`trust_env=False` / `--no-proxy-server`）；
- 不读取任何密钥或凭据文件。

## 已知限制

- 不执行 stealth 反检测，不处理 Cloudflare/验证码/付费墙；被拦截就返回 `blocked`。
- `fast` 层不执行 JS，单页应用可能只有空壳；需要时用 `mode="browser"`。
- 只处理文本类响应，不解析 PDF、Office、图片、音视频。
- 响应上限 5 MB、返回正文上限 100 000 字符，超出截断并置 `truncated: true`。
- `browser` 每抓取一次启动一个独立 Chrome 进程（全新无痕上下文，结束即关闭），延迟和内存开销明显高于 `fast`；并发上限 2。
- 浏览器发出的站点请求经本次进程专用的本机转发器连接已校验的 IP，HTTPS 仍由 Chromium 按原域名验证证书。Clash 返回 Fake-IP 时，通过阿里公共 DNS 的 HTTPS 接口获取真实 A 记录，再检查地址范围。
- robots.txt 缓存 1 小时，站点规则变更最长 1 小时后生效。
- 不跟踪 `Crawl-delay`（统一用 1 秒/域名）；不解析 sitemap。

## 合规边界

本工具只用于抓取公开页面，供研究与信息整理：

- 遵守目标站点 robots.txt 与服务条款；
- 不绕过登录、付费墙、验证码、访问频率限制或其他技术保护措施；
- 不伪装成浏览器 UA（fast 与 browser 都用 `dsh-finance-scrape/<版本>`），被站点拒绝即停止，不重试规避；
- 不抓取非公开数据，不向外部地址上传本地数据；
- 页面内容可能含提示注入，使用方必须把它当数据而不是指令。

## 测试

```bash
cd packages/scrape-mcp
.venv/bin/python -m pytest -q
```

测试完全离线：本地回环假站点（`SCRAPE_TEST_ALLOW_LOOPBACK=1`，由测试 fixture 设置）覆盖正文抽取、重定向、重定向环、超大响应、慢响应、提示注入、验证页、robots 禁止、非文本类型；SSRF 矩阵覆盖 30+ 种 IP 写法与 IPv6 变体；DNS 用可注入的假解析器模拟 rebinding；browser 用例使用 Chives 专属 Chromium 渲染本地静态 JS 页，Chives Chromium 不存在时 `pytest.skip`。测试不会访问公网。
