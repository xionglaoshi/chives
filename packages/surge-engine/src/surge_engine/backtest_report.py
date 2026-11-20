"""Chinese Markdown report + SVG charts for one 主升浪 backtest run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backtest_charts import area_chart, bar_chart, histogram_chart, line_chart


def _num(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2f}%"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _equity_values(equity_rows: list[dict[str, Any]]) -> tuple[list[str], list[float], list[float]]:
    labels = [str(row["date"]) for row in equity_rows]
    normalized = []
    drawdowns = []
    peak = None
    first = float(equity_rows[0]["equity"]) if equity_rows else 1.0
    for row in equity_rows:
        value = float(row["equity"])
        peak = value if peak is None else max(peak, value)
        normalized.append(value / first if first else 1.0)
        drawdowns.append((value / peak - 1.0) * 100 if peak else 0.0)
    return labels, normalized, drawdowns


def _benchmark_series(equity_rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    first = None
    for row in equity_rows:
        raw = row.get(key)
        if raw is None:
            values.append(values[-1] if values else 1.0)
            continue
        if first is None:
            first = float(raw)
        values.append(float(raw) / first if first else 1.0)
    return values


def write_report(result: dict[str, Any], run_dir: Path) -> None:
    summary = result["summary"]
    per = summary["per_trade"]
    port = summary["portfolio"]
    equity_rows = result["equity_rows"]
    labels, equity_curve, drawdowns = _equity_values(equity_rows)

    line_chart(
        run_dir / "equity.svg",
        labels,
        [
            ("策略净值", equity_curve),
            ("沪深300", _benchmark_series(equity_rows, "hs300")),
            ("中证1000", _benchmark_series(equity_rows, "csi1000")),
        ],
        f"资金曲线：{summary['scheme_label']}（2020-01-01 起，起点=1）",
        "净值",
    )
    area_chart(run_dir / "drawdown.svg", labels, drawdowns, "策略回撤（%）", "回撤 %")
    yearly = summary.get("by_year") or []
    bar_chart(
        run_dir / "yearly.svg",
        [str(item["year"]) for item in yearly],
        [float(item["return_pct"] or 0.0) for item in yearly],
        "组合分年收益（%）",
        "收益 %",
    )
    histogram_chart(run_dir / "histogram.svg", per.get("histogram") or [], "逐笔收益分布（笔数）")

    lines: list[str] = []
    lines.append(f"# 主升浪回测报告：{summary['scheme_label']}")
    lines.append("")
    lines.append(
        f"> 区间 {summary['start']} 至 {summary['cutoff']}；信号事件「{summary['signal_event']}」；"
        f"结果目录 `{run_dir}`。按冻结规则的历史模拟，不代表未来收益，不是投资建议。"
    )
    lines.append("")
    lines.append("## 0. 结论（先行）")
    lines.append("")
    lines.append(
        f"- 信号 {summary['signal_count']} 个：成交 {per['count']} 笔，买不到 {per['unfilled_limit_up']} 笔，"
        f"停牌超 5 日放弃 {per['suspension_abandoned']} 笔，超出区间 {per['out_of_range']} 笔。"
    )
    lines.append(
        f"- 逐笔（每笔 10 万元、互不影响）：胜率 {_pct(per['win_rate_pct'])}，平均收益 "
        f"{_pct(per['avg_return_pct'])}，中位 {_pct(per['median_return_pct'])}，盈亏比 "
        f"{_num(per['profit_loss_ratio'])}，平均持有 {_num(per['avg_holding_days'])} 个交易日。"
    )
    lines.append(
        f"- 组合（初始 100 万、最多 10 只、每只 1/10）：总收益 {_pct(port['total_return_pct'])}，"
        f"年化 {_pct(port['annualized_return_pct'])}，最大回撤 {_pct(port['max_drawdown_pct'])}"
        f"（{port['max_drawdown_peak']} → {port['max_drawdown_trough']}），夏普 {_num(port['sharpe'])}，"
        f"卡玛 {_num(port['calmar'])}，年化双边换手 {_num(port['turnover_annualized'])}。"
    )
    lines.append(
        f"- 仓满跳过 {per['skipped_full']} 笔、已持有跳过 {per['skipped_held']} 笔；截止日未平仓 "
        f"{per['unclosed_count']} 笔按截止日收盘估值。"
    )
    for label, stats in (summary.get("out_of_sample") or {}).items():
        lines.append(
            f"- 样本外 {label}：{stats['count']} 笔，胜率 {_pct(stats['win_rate_pct'])}，"
            f"平均 {_pct(stats['avg_return_pct'])}，中位 {_pct(stats['median_return_pct'])}。"
        )
    lines.append("")
    lines.append("## 1. 冻结口径")
    lines.append("")
    rules = summary["rules"]
    lines.append(
        _table(
            ["项目", "口径"],
            [
                ["入场", rules["entry"]],
                ["卖出", rules["exit"]],
                ["佣金", rules["commission"]],
                ["印花税", rules["stamp_tax"]],
                ["滑点", rules["slippage"]],
                ["复权", rules["adjustment"]],
                ["逐笔资金", f"{rules['per_trade_capital']:,.0f} 元"],
                ["组合", f"初始 {rules['initial_capital']:,.0f} 元，最多 {rules['max_positions']} 只；"
                 f"{rules['position_size']}"],
                ["无风险利率", "0（夏普按日收益年化）"],
                ["最小开仓预算", f"{rules.get('min_position_budget', 1000):,.0f} 元/只；低于此值不再开仓，避免最低佣金造成的失真。"],
            ],
        )
    )
    lines.append("")
    lines.append("## 2. 逐笔统计")
    lines.append("")
    lines.append(
        _table(
            ["指标", "值"],
            [
                ["信号数", per["signals"]],
                ["成交笔数", per["count"]],
                ["买不到（开盘涨停）", per["unfilled_limit_up"]],
                ["停牌超 5 日放弃", per["suspension_abandoned"]],
                ["超出回测区间", per["out_of_range"]],
                ["胜率", _pct(per["win_rate_pct"])],
                ["平均收益", _pct(per["avg_return_pct"])],
                ["中位收益", _pct(per["median_return_pct"])],
                ["盈亏比", _num(per["profit_loss_ratio"])],
                ["平均持有天数", _num(per["avg_holding_days"])],
                ["单笔最大盈利", _pct(per["max_win_pct"])],
                ["单笔最大亏损", _pct(per["max_loss_pct"])],
                ["最长连亏", per["longest_losing_streak"]],
                ["未平仓", per["unclosed_count"]],
            ],
        )
    )
    lines.append("")
    lines.append("![逐笔收益分布](histogram.svg)")
    lines.append("")
    lines.append("## 3. 组合回测")
    lines.append("")
    lines.append(
        _table(
            ["指标", "策略", "沪深300", "中证1000"],
            [
                ["总收益", _pct(port["total_return_pct"]),
                 _pct((summary["benchmarks"].get("hs300") or {}).get("total_return_pct")),
                 _pct((summary["benchmarks"].get("csi1000") or {}).get("total_return_pct"))],
                ["年化收益", _pct(port["annualized_return_pct"]),
                 _pct((summary["benchmarks"].get("hs300") or {}).get("annualized_return_pct")),
                 _pct((summary["benchmarks"].get("csi1000") or {}).get("annualized_return_pct"))],
                ["最大回撤", _pct(port["max_drawdown_pct"]),
                 _pct((summary["benchmarks"].get("hs300") or {}).get("max_drawdown_pct")),
                 _pct((summary["benchmarks"].get("csi1000") or {}).get("max_drawdown_pct"))],
                ["夏普", _num(port["sharpe"]),
                 _num((summary["benchmarks"].get("hs300") or {}).get("sharpe")),
                 _num((summary["benchmarks"].get("csi1000") or {}).get("sharpe"))],
                ["卡玛", _num(port["calmar"]), "—", "—"],
                ["年化双边换手", _num(port["turnover_annualized"]), "—", "—"],
                ["组合成交笔数", port["trades"] if "trades" in port else len(result["portfolio_trades"]), "—", "—"],
                ["平均持仓只数", _num(port["avg_positions"]), "—", "—"],
            ],
        )
    )
    lines.append("")
    lines.append(f"- 最大回撤区间：{port['max_drawdown_peak']} → {port['max_drawdown_trough']}。")
    lines.append("")
    lines.append("![资金曲线](equity.svg)")
    lines.append("")
    lines.append("![回撤](drawdown.svg)")
    lines.append("")
    lines.append("## 4. 分年")
    lines.append("")
    rows = []
    trade_by_year = {str(item["group"]): item for item in summary.get("yearly_trade_stats") or []}
    for item in yearly:
        stats = trade_by_year.get(str(item["year"]), {})
        rows.append(
            [
                item["year"],
                _pct(item["return_pct"]),
                _num(item["end_equity"]),
                stats.get("count", 0),
                _pct(stats.get("win_rate_pct")),
                _pct(stats.get("avg_return_pct")),
            ]
        )
    lines.append(_table(["年份", "组合收益", "年末权益", "逐笔笔数", "逐笔胜率", "逐笔平均收益"], rows))
    lines.append("")
    lines.append("![分年收益](yearly.svg)")
    lines.append("")
    lines.append("## 5. 分组（逐笔等额 10 万元）")
    for key, title in (
        ("by_environment", "按市场环境（沪深300 收盘相对 MA20）"),
        ("by_board", "按板块"),
        ("by_first_score", "按首板池总分档位（仅 p1/p2）"),
        ("by_base_score", "按入场时主升浪涨幅基础分"),
    ):
        items = summary.get("groups", {}).get(key) or []
        if not items:
            continue
        lines.append("")
        lines.append(f"### {title}")
        lines.append("")
        lines.append(
            _table(
                ["分组", "笔数", "胜率", "平均收益", "中位收益", "平均持有天数"],
                [
                    [
                        item["group"],
                        item.get("count", 0),
                        _pct(item.get("win_rate_pct")),
                        _pct(item.get("avg_return_pct")),
                        _pct(item.get("median_return_pct")),
                        _num(item.get("avg_holding_days")),
                    ]
                    for item in items
                ],
            )
        )
    lines.append("")
    lines.append("## 6. 样本外（不调整任何参数）")
    lines.append("")
    oos_rows = []
    for label, stats in (summary.get("out_of_sample") or {}).items():
        oos_rows.append(
            [
                label,
                stats.get("count", 0),
                _pct(stats.get("win_rate_pct")),
                _pct(stats.get("avg_return_pct")),
                _pct(stats.get("median_return_pct")),
                _num(stats.get("avg_holding_days")),
            ]
        )
    lines.append(_table(["区间", "笔数", "胜率", "平均收益", "中位收益", "平均持有天数"], oos_rows))
    lines.append("")
    lines.append("## 7. 逐笔样例（供复核）")
    lines.append("")
    samples = [row for row in result["per_trade_rows"] if row.get("return_pct") not in ("", None)][:3]
    if samples:
        lines.append(
            _table(
                ["代码", "信号日", "买入日", "买入开盘", "因子", "卖出日", "卖出开盘", "费用合计", "收益"],
                [
                    [
                        row["code"],
                        row["signal_date"],
                        row["buy_date"],
                        _num(row["buy_open_raw"]),
                        _num(row["buy_adj_factor"], 6),
                        row.get("sell_date") or row.get("valuation_date"),
                        _num(row.get("sell_open_raw") or row.get("valuation_close_raw")),
                        _num(
                            float(row["buy_commission"] or 0)
                            + float(row.get("sell_commission") or 0)
                            + float(row.get("stamp_tax") or 0),
                        ),
                        _pct(row["return_pct"]),
                    ]
                    for row in samples
                ],
            )
        )
    else:
        lines.append("没有成交样本。")
    lines.append("")
    lines.append("## 8. 限制与未验证")
    lines.append("")
    lines.append(
        "- 历史 ST 身份按当前简称近似（T154 数据层限制），会影响涨停价判定与股票池。"
        "\n- 成交按开盘价一次性撮合，未模拟盘中流动性、冲击成本与涨跌停后的排队。"
        "\n- 复权因子用于把持有期收益接到同一口径；现金分红不再单独计息或扣税。"
        "\n- 指数日线经网关 `market_bars` 取，缓存于 `runtime/surge/backtest/benchmarks/`；"
        "指数与个股交易日不一致时按上一可用收盘前向填充。"
        "\n- 组合每只按买入当时总资产的 1/10 下单（含费用预算），未使用整手取整。"
    )
    lines.append("")
    lines.append(
        f"> 生成时间：{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}；"
        f"引擎 spec v1。按冻结规则的历史模拟，不代表未来收益，不是投资建议。"
    )
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
