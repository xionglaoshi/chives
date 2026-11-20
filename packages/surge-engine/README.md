# surge-engine

主升浪规则引擎（T155）。按 `docs/strategy/zhushenglang-spec.md` v1 实现首板识别、首板观察池、
突破确认、主升浪评分与 MA10 移出，回测与每日增量共用同一套按日推进代码。

只读使用 `packages/cn-daily-store`；运行产物写到 `runtime/surge/`。

## 安装

```bash
cd packages/surge-engine
UV_CACHE_DIR=$PWD/.uv-cache uv venv --python 3.12 .venv
UV_CACHE_DIR=$PWD/.uv-cache uv pip install --python .venv/bin/python -e ../cn-daily-store
UV_CACHE_DIR=$PWD/.uv-cache uv pip install --python .venv/bin/python -e '.[test]'
```

## CLI

```bash
.venv/bin/surge-engine replay --start 2020-01-01 --end 2026-11-17
.venv/bin/surge-engine step --date 2026-11-18
.venv/bin/surge-engine pools --date 2026-11-17
.venv/bin/surge-engine round 600519.SH
.venv/bin/surge-engine annotate 600519.SH 1
.venv/bin/surge-engine backtest --scheme p1 --start 2020-01-01 --end 2026-11-17
```

`backtest` 的 `--scheme` 为 `p1`、`p2`、`start`、`second_board`；结果写
`runtime/surge/backtest/<run_id>/`（`trades.csv`、`portfolio_trades.csv`、`equity.csv`、
`summary.json`、`report.md` 与 4 张 SVG）。指数日线经网关 `market_bars` 取并缓存在
`runtime/surge/backtest/benchmarks/`；`--no-benchmark` 仅供离线调试。

K 线标注输出 JSON + 一个独立的 HTML/SVG 文件（不引入 matplotlib 依赖）。

## 产物

- `runtime/surge/surge.sqlite`：`events`、`pool_snapshots`、`rounds`、`meta`
- `runtime/surge/*.csv`：上述三张表的 CSV 导出
- `runtime/surge/state.json`：增量 `step` 的轮次状态
- `runtime/surge/review/`：抽样轮次的 JSON/HTML 标注

规则口径以规格 v1 为准；待确认项按规格第 8 节括号内口径实现，代码注释标注。
