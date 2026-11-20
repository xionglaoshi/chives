"""K-line annotation for one round (spec section 6).

Output is a JSON document plus a standalone HTML/SVG file.  The task allows
matplotlib only when an existing environment already has it; the cn-daily-store
venv does not, so this module deliberately adds no dependency and draws the
chart as inline SVG.
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from typing import Any

from cn_daily_store import DailyStore

from .outputs import OutputStore, default_paths
from .spec import SPEC_VERSION

_REVIEW_DIR = "review"


def annotate_round(
    code: str,
    round_id: int,
    *,
    output: OutputStore | None = None,
    store: DailyStore | None = None,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    owns_output = output is None
    owns_store = store is None
    output = output or OutputStore()
    store = store or DailyStore()
    try:
        round_row = output.round_row(code, round_id)
        if round_row is None:
            raise ValueError(f"round not found: {code} #{round_id}")
        events = output.events_for(code, round_id)
        snapshots = output.snapshots_for_round(code, round_id)
        calendar = store.calendar()
        f_date = date.fromisoformat(round_row["F"])
        f_index = calendar.index(f_date)
        end_date = _end_date(round_row, snapshots, output, calendar)
        start_date = calendar[max(0, f_index - 25)]
        bars = store.bars(code, start_date, end_date, adjust="qfq")
        payload = _payload(code, round_id, round_row, events, bars, calendar, f_date, end_date, store)
        target = Path(out_dir) if out_dir else default_paths()[0].parent / _REVIEW_DIR
        target.mkdir(parents=True, exist_ok=True)
        stem = f"{code}_{round_id}"
        json_path = target / f"{stem}.json"
        html_path = target / f"{stem}.html"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        html_path.write_text(render_html(payload), encoding="utf-8")
        payload["json_path"] = str(json_path)
        payload["html_path"] = str(html_path)
        return payload
    finally:
        if owns_output:
            output.close()
        if owns_store:
            store.close()


def _end_date(
    round_row: dict, snapshots: list[dict], output: OutputStore, calendar: list[date]
) -> date:
    for key in ("main_out_date", "first_out_date"):
        if round_row.get(key):
            return date.fromisoformat(round_row[key])
    if snapshots:
        return date.fromisoformat(snapshots[-1]["date"])
    stored = output.get_meta("last_date")
    if stored:
        return date.fromisoformat(stored)
    return calendar[-1]


def _payload(
    code: str,
    round_id: int,
    round_row: dict,
    events: list[dict],
    bars: list[Any],
    calendar: list[date],
    f_date: date,
    end_date: date,
    store: DailyStore,
) -> dict[str, Any]:
    by_date = {bar.date: bar for bar in bars}
    closes = [bar.close for bar in bars]
    ma: dict[str, dict[str, float | None]] = {"ma5": {}, "ma10": {}, "ma20": {}}
    for offset, bar in enumerate(bars):
        for window in (5, 10, 20):
            key = f"ma{window}"
            ma[key][bar.date.isoformat()] = (
                sum(closes[offset - window + 1 : offset + 1]) / window if offset + 1 >= window else None
            )

    f_index = calendar.index(f_date)
    end_index = calendar.index(end_date)
    hb_by_date: dict[str, float | None] = {}
    max_close: float | None = None
    for offset in range(f_index, end_index + 1):
        day = calendar[offset]
        hb_by_date[day.isoformat()] = max_close
        bar = by_date.get(day)
        if bar is not None:
            max_close = bar.close if max_close is None else max(max_close, bar.close)

    rows = []
    for bar in bars:
        key = bar.date.isoformat()
        rows.append(
            {
                "date": key,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "limit_up": bool(store.is_limit_up(code, bar.date)),
                "ma5": ma["ma5"][key],
                "ma10": ma["ma10"][key],
                "ma20": ma["ma20"][key],
                "hb": hb_by_date.get(key),
            }
        )

    pit = round_row["G"]
    pit_candidates = [bar for bar in bars if bar.date < f_date and abs(bar.close - pit) < 1e-9]
    pit_date = pit_candidates[-1].date.isoformat() if pit_candidates else None
    return {
        "spec_version": SPEC_VERSION,
        "code": code,
        "round_id": round_id,
        "round": round_row,
        "bars": rows,
        "events": events,
        "lines": {
            "first_board_date": f_date.isoformat(),
            "first_board_close": round_row["C_F"],
            "first_board_low": round_row["L_F"],
            "golden_pit": pit,
            "golden_pit_date": pit_date,
            "window_max": round_row["window_max"],
            "window_min": round_row["window_min"],
            "mark_price": round_row["P_star"],
            "basis": round_row["B"],
        },
        "range": {"start": bars[0].date.isoformat() if bars else None, "end": end_date.isoformat()},
    }


# -- HTML/SVG ---------------------------------------------------------------
def render_html(payload: dict[str, Any]) -> str:
    rows = payload["bars"]
    lines = payload["lines"]
    title = f"{payload['code']} 轮次 {payload['round_id']}"
    if not rows:
        return f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><p>无 K 线数据</p>"
    width, height = 1280, 720
    left, right, top = 64, 150, 42
    price_bottom = 520
    volume_top, volume_bottom = 545, 665
    step = (width - left - right) / max(1, len(rows))
    lows = [row["low"] for row in rows]
    highs = [row["high"] for row in rows]
    candidates = lows + highs + [value for value in lines.values() if isinstance(value, (int, float))]
    low, high = min(candidates), max(candidates)
    pad = (high - low) * 0.04 or 0.1
    low, high = low - pad, high + pad

    def x(index: int) -> float:
        return left + (index + 0.5) * step

    def y(price: float) -> float:
        return price_bottom - (price - low) / (high - low) * (price_bottom - top)

    parts: list[str] = []
    parts.append(f"<svg viewBox='0 0 {width} {height}' xmlns='http://www.w3.org/2000/svg' class='chart'>")
    parts.append("<rect width='100%' height='100%' fill='#0f1621'/>")
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        price = low + (high - low) * fraction
        yy = y(price)
        parts.append(f"<line x1='{left}' x2='{width - right}' y1='{yy:.2f}' y2='{yy:.2f}' stroke='#243044'/>")
        parts.append(
            f"<text x='{left - 8}' y='{yy + 4:.2f}' text-anchor='end' fill='#8aa0bb' font-size='11'>{price:.2f}</text>"
        )
    for index, row in enumerate(rows):
        if index % max(1, len(rows) // 10) != 0:
            continue
        parts.append(
            f"<text x='{x(index):.2f}' y='{price_bottom + 16}' text-anchor='middle' fill='#8aa0bb' font-size='10'>"
            f"{row['date'][5:]}</text>"
        )

    body = step * 0.55
    for index, row in enumerate(rows):
        up = row["close"] >= row["open"]
        color = "#e5534b" if up else "#2ea043"
        parts.append(
            f"<line x1='{x(index):.2f}' x2='{x(index):.2f}' y1='{y(row['high']):.2f}' y2='{y(row['low']):.2f}' "
            f"stroke='{color}' stroke-width='1'/>"
        )
        top_price, bottom_price = max(row["open"], row["close"]), min(row["open"], row["close"])
        parts.append(
            f"<rect x='{x(index) - body / 2:.2f}' y='{y(top_price):.2f}' width='{body:.2f}' "
            f"height='{max(1.0, y(bottom_price) - y(top_price)):.2f}' fill='{color}'/>"
        )

    def polyline(key: str, color: str, width_px: float) -> None:
        points = [
            (x(index), y(row[key]))
            for index, row in enumerate(rows)
            if row.get(key) is not None
        ]
        if len(points) > 1:
            text = " ".join(f"{px:.2f},{py:.2f}" for px, py in points)
            parts.append(
                f"<polyline points='{text}' fill='none' stroke='{color}' stroke-width='{width_px}' opacity='0.95'/>"
            )

    polyline("ma5", "#f2cc60", 1.4)
    polyline("ma10", "#58a6ff", 1.4)
    polyline("ma20", "#bc8cff", 1.4)
    polyline("hb", "#8b949e", 1.0)

    for label, value, color in (
        ("G/S1", lines["golden_pit"], "#ff7b72"),
        ("L_F/S2", lines["first_board_low"], "#39c5cf"),
        ("P*", lines["mark_price"], "#e3b341"),
        ("B", lines["basis"], "#d29922"),
    ):
        if value is None:
            continue
        yy = y(value)
        parts.append(
            f"<line x1='{left}' x2='{width - right}' y1='{yy:.2f}' y2='{yy:.2f}' stroke='{color}' "
            f"stroke-width='1.1' stroke-dasharray='6 4'/>"
        )
        parts.append(
            f"<text x='{width - right + 8}' y='{yy + 4:.2f}' fill='{color}' font-size='11'>{label} {value:.2f}</text>"
        )

    event_colors = {
        "首板": "#f0883e",
        "二板": "#f0883e",
        "启动": "#3fb950",
        "优先级一确定": "#3fb950",
        "优先级二确定": "#3fb950",
        "MA10跌破": "#e5534b",
        "MA10修复": "#3fb950",
        "支撑跌破": "#ff7b72",
        "支撑最终破位": "#ff7b72",
        "支撑收复": "#39c5cf",
        "主升浪移出": "#e5534b",
        "到期移出": "#8b949e",
        "确认失败移出": "#8b949e",
    }
    by_date = {row["date"]: index for index, row in enumerate(rows)}
    f_index = by_date.get(lines.get("first_board_date"))
    if f_index is not None:
        frow = rows[f_index]
        parts.append(
            f"<line x1='{x(f_index):.2f}' x2='{x(f_index):.2f}' y1='{top}' y2='{price_bottom}' "
            f"stroke='#f0883e' stroke-width='1' stroke-dasharray='3 5'/>"
        )
        parts.append(
            f"<path d='M {x(f_index):.2f} {y(frow['low']) - 12:.2f} l -5 8 l 10 0 z' fill='#f0883e'>"
            f"<title>首板 {lines['first_board_date']}</title></path>"
        )
    g_index = by_date.get(lines.get("golden_pit_date"))
    if g_index is not None and lines.get("golden_pit") is not None:
        parts.append(
            f"<circle cx='{x(g_index):.2f}' cy='{y(lines['golden_pit']):.2f}' r='4' fill='none' "
            f"stroke='#ff7b72' stroke-width='2'><title>黄金坑低点 G={lines['golden_pit']:.2f}</title></circle>"
        )
    for event in payload["events"]:
        index = by_date.get(event["date"])
        if index is None:
            continue
        row = rows[index]
        color = event_colors.get(event["event"], "#c9d1d9")
        cy = y(row["close"])
        parts.append(
            f"<circle cx='{x(index):.2f}' cy='{cy:.2f}' r='3.4' fill='{color}' stroke='#0f1621' stroke-width='1'>"
            f"<title>{html.escape(event['date'] + ' ' + event['event'])}</title></circle>"
        )

    for index, row in enumerate(rows):
        if row["limit_up"]:
            parts.append(
                f"<circle cx='{x(index):.2f}' cy='{y(row['high']) - 6:.2f}' r='2.2' fill='#f0883e'/>"
            )

    max_volume = max((row["volume"] for row in rows), default=1) or 1
    for index, row in enumerate(rows):
        bar_height = (row["volume"] / max_volume) * (volume_bottom - volume_top)
        color = "#e5534b" if row["close"] >= row["open"] else "#2ea043"
        parts.append(
            f"<rect x='{x(index) - body / 2:.2f}' y='{volume_bottom - bar_height:.2f}' width='{body:.2f}' "
            f"height='{bar_height:.2f}' fill='{color}' opacity='0.65'/>"
        )
    parts.append(
        f"<text x='{left}' y='{volume_top - 8}' fill='#8aa0bb' font-size='11'>成交量（股）</text>"
    )

    legend = [
        ("MA5", "#f2cc60"),
        ("MA10", "#58a6ff"),
        ("MA20", "#bc8cff"),
        ("突破线 Hb", "#8b949e"),
        ("G/S1", "#ff7b72"),
        ("L_F/S2", "#39c5cf"),
        ("P*", "#e3b341"),
    ]
    for position, (label, color) in enumerate(legend):
        lx = left + position * 120
        parts.append(f"<line x1='{lx}' x2='{lx + 18}' y1='{22}' y2='{22}' stroke='{color}' stroke-width='2'/>")
        parts.append(f"<text x='{lx + 24}' y='{26}' fill='#c9d1d9' font-size='11'>{html.escape(label)}</text>")
    parts.append(
        f"<text x='{left}' y='{height - 14}' fill='#8aa0bb' font-size='11'>"
        f"F={payload['round']['F']}  轮次状态={payload['round'].get('main_out_reason') or payload['round'].get('first_out_reason') or '在池'}"
        f"  spec={SPEC_VERSION}</text>"
    )
    parts.append("</svg>")

    event_rows = "".join(
        f"<tr><td>{html.escape(event['date'])}</td><td>{html.escape(event['event'])}</td>"
        f"<td><code>{html.escape(json.dumps(event['values'], ensure_ascii=False))}</code></td></tr>"
        for event in payload["events"]
    )
    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body {{ background:#0b1119; color:#c9d1d9; font: 13px/1.5 -apple-system, "PingFang SC", sans-serif; margin: 18px; }}
h1 {{ font-size: 18px; margin: 0 0 6px; }}
.meta {{ color:#8aa0bb; margin-bottom:12px; }}
.chart {{ width:100%; height:auto; border:1px solid #243044; border-radius:8px; }}
table {{ border-collapse:collapse; margin-top:18px; width:100%; }}
th, td {{ border-bottom:1px solid #243044; padding:6px 8px; text-align:left; vertical-align:top; }}
th {{ color:#8aa0bb; font-weight:600; }}
code {{ color:#a5d6ff; word-break:break-all; }}
</style></head>
<body>
<h1>{html.escape(title)}</h1>
<div class="meta">首板 {html.escape(str(payload['round']['F']))} · 分支 {html.escape(str(payload['round'].get('branch')))} · 优先级 {html.escape(str(payload['round'].get('priority')))} · 标记价 P* {payload['round'].get('P_star')} · 区间 {html.escape(str(payload['range']['start']))} 至 {html.escape(str(payload['range']['end']))}</div>
{''.join(parts)}
<table><thead><tr><th>日期</th><th>事件</th><th>数值</th></tr></thead><tbody>{event_rows}</tbody></table>
</body></html>
"""
