# strategy-hub

策略服务（T158）：在 `127.0.0.1:8769` 以只读方式读取 `cn-daily-store` 与 `surge-engine` 的库，
按 `strategy_id` 提供统一的策略读取接口与 stdio MCP。本期只有 `zhushenglang`（主升浪）。

## 安装与运行

```bash
cd packages/strategy-hub
UV_CACHE_DIR=$PWD/.uv-cache uv venv --python 3.12 .venv
UV_CACHE_DIR=$PWD/.uv-cache uv pip install --python .venv/bin/python -e ../cn-daily-store -e ../surge-engine -e '.[test]'
.venv/bin/python -m strategy_hub --port 8769
```

日程：交易日 15:35 运行 `cn-daily-store update`，完成后对当日运行 `surge-engine step`，
事件写入策略服务的 `alerts` 表；失败重试 3 次并在 `/health` 报告。启动时若最近交易日尚未计算则补算。
`--no-scheduler` 可关闭日程（测试/临时运行用）。

## HTTP

- `GET /v1/strategies`
- `GET /v1/{id}/pools?date=`
- `GET /v1/{id}/round?code=&date=`
- `GET /v1/{id}/events?start=&end=&kinds=&limit=`
- `GET /v1/{id}/levels?code=`
- `GET /v1/{id}/annotate?code=&round_id=`
- `POST /v1/{id}/backtest`：body `{"scheme":"p1","start":"2020-01-01","end":"2026-11-17"}`，
  异步返回 `job_id`；同一参数复用已有结果。
- `GET /v1/{id}/backtest/{job_id}`：状态与摘要（含 `per_trade`、`portfolio`、`out_of_sample`）。
- `GET /v1/{id}/backtests?limit=`：历史任务列表。
- `GET /alerts?since_id=&limit=`：策略事件流，字段与 market-watch `/alerts` 对齐。
- `GET /health`

## MCP

```bash
CHIVES_STRATEGIES=zhushenglang .venv/bin/python -m strategy_hub.mcp_server --url http://127.0.0.1:8769
```

工具：`strategy_list`、`strategy_pools`、`strategy_round`、`strategy_events`、`strategy_levels`、
`strategy_annotate`、`strategy_backtest`、`strategy_backtest_result`。`CHIVES_STRATEGIES`（逗号分隔）
限制可用的策略 ID；未设置时允许全部。

口径：前复权、收盘后计算、不使用未来数据；规则筛选结果，不是投资建议。
回测是按冻结买卖与费用规则的历史模拟，不代表未来收益，不是投资建议。
