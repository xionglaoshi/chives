# 用假数据看画板 01–03

前后端一起起：

```bash
cd /Users/xiong/.chives
CHIVES_HARNESS=fake pnpm dev
```

- `apps/server` 在 `127.0.0.1:8780` 用 `FakeDriver` 跑（无需 dsh、无需任何密钥）。
- `apps/web` 的 Vite 在 `127.0.0.1:5173`，`/api` 代理到 8780。打开 <http://127.0.0.1:5173/>。
- 想从空时间线重新开始，先把 `CHIVES_DATA_DIR` 指到一个临时目录再起（默认为仓库的 `data/`）：
  `CHIVES_HARNESS=fake CHIVES_DATA_DIR=$(mktemp -d) pnpm dev`。

对应关系：

| 画板 | 怎么看到 |
|---|---|
| 01 主界面 | 默认打开行情看板。左侧从上到下是会话搜索、工作台、已在岗Bot和人才市场。点击 Bot 继续原会话。 |
| 02 关键状态 | 发一条消息后，点击"工作了…"折叠行可以看到工具步骤、参数与输出。假 driver 会推 `draft.reset/delta/commit` 与 `tool.started/ended`，但它每步只等 2ms，草稿和"停止"按钮一闪而过；这两处的行为由 `pnpm --filter @chives/web test` 覆盖（草稿 reducer、停止按钮切换）。时间线的分页、翻页用测试覆盖；`FakeDriver` 只回一句"模拟回答"，折叠行里的工具步骤与状态是真实事件。 |
| 03 首次使用 | 用空数据目录起服务，当前 bot 时间线为空时显示问候、4 个起手建议和三条边界说明；点建议会直接发送。 |

假模式的 SSE 事件与真实模式同一套协议；断网/重连可直接在 DevTools 的 Network 面板里 off/on，或用 `pnpm --filter @chives/server test` 里的 SSE 测试看服务端行为。
