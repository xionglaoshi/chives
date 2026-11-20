"""Minimal dependency-free SVG charts for the 主升浪 backtest report.

T155 used standalone HTML/SVG because the cn-daily-store virtualenv has no
matplotlib; the same choice is kept here.
"""

from __future__ import annotations

import math
from pathlib import Path

WIDTH = 940
HEIGHT = 390
LEFT = 78
RIGHT = 26
TOP = 54
BOTTOM = 58
FONT = "PingFang SC, Noto Sans CJK SC, Microsoft YaHei, sans-serif"
COLORS = ("#2563eb", "#ea580c", "#16a34a", "#9333ea", "#dc2626", "#0891b2")


def _esc(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    if high <= low:
        high = low + 1.0
    raw = (high - low) / count
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = min(
        (1, 2, 2.5, 5, 10),
        key=lambda item: abs(item * magnitude - raw),
    ) * magnitude
    first = math.floor(low / step) * step
    ticks = []
    value = first
    while value <= high + step * 0.5:
        ticks.append(value)
        value += step
    return ticks


def _frame(title: str, ylabel: str, low: float, high: float, n: int) -> tuple[list[str], dict[str, float]]:
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{LEFT}" y="28" font-family="{FONT}" font-size="17" font-weight="600" fill="#111827">{_esc(title)}</text>',
    ]
    plot_w = WIDTH - LEFT - RIGHT
    plot_h = HEIGHT - TOP - BOTTOM
    ticks = _ticks(low, high)
    for value in ticks:
        y = TOP + plot_h - (value - low) / (high - low) * plot_h
        elements.append(
            f'<line x1="{LEFT}" y1="{y:.1f}" x2="{LEFT + plot_w}" y2="{y:.1f}" stroke="#e5e7eb" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{LEFT - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="{FONT}" '
            f'font-size="11" fill="#6b7280">{_esc(_fmt(value))}</text>'
        )
    elements.append(
        f'<line x1="{LEFT}" y1="{TOP + plot_h}" x2="{LEFT + plot_w}" y2="{TOP + plot_h}" stroke="#9ca3af"/>'
    )
    elements.append(
        f'<text x="16" y="{TOP + plot_h / 2:.1f}" transform="rotate(-90 16 {TOP + plot_h / 2:.1f})" '
        f'text-anchor="middle" font-family="{FONT}" font-size="11" fill="#6b7280">{_esc(ylabel)}</text>'
    )
    label_count = min(6, max(2, n))
    positions = []
    for index in range(label_count):
        positions.append(round(index * (n - 1) / (label_count - 1)) if n > 1 else 0)
    return elements, {"plot_w": plot_w, "plot_h": plot_h, "ticks": ticks, "label_positions": positions}


def _x(index: int, n: int, plot_w: float) -> float:
    return LEFT + (index / (n - 1) * plot_w if n > 1 else 0.0)


def _y(value: float, low: float, high: float, plot_h: float) -> float:
    return TOP + plot_h - (value - low) / (high - low) * plot_h


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.0f}"
    return f"{value:.2f}"


def _axis_labels(elements: list[str], labels: list[str], label_positions: list[int]) -> None:
    for position in label_positions:
        if not labels:
            continue
        x = LEFT + position / max(1, len(labels) - 1) * (WIDTH - LEFT - RIGHT)
        elements.append(
            f'<text x="{x:.1f}" y="{HEIGHT - 24}" text-anchor="middle" font-family="{FONT}" '
            f'font-size="10" fill="#6b7280">{_esc(labels[position])}</text>'
        )


def _legend(elements: list[str], names: list[str], colors: tuple[str, ...]) -> None:
    x = LEFT
    for index, name in enumerate(names):
        color = colors[index % len(colors)]
        elements.append(f'<line x1="{x}" y1="44" x2="{x + 18}" y2="44" stroke="{color}" stroke-width="3"/>')
        elements.append(
            f'<text x="{x + 23}" y="48" font-family="{FONT}" font-size="11" fill="#374151">{_esc(name)}</text>'
        )
        x += 34 + len(str(name)) * 12


def line_chart(path: Path, labels: list[str], series: list[tuple[str, list[float]]], title: str, ylabel: str) -> None:
    all_values = [value for _, values in series for value in values if value is not None]
    low, high = (min(all_values), max(all_values)) if all_values else (0.0, 1.0)
    pad = (high - low) * 0.08 or 1.0
    low, high = low - pad, high + pad
    elements, frame = _frame(title, ylabel, low, high, len(labels))
    _legend(elements, [name for name, _ in series], COLORS)
    for index, (_name, values) in enumerate(series):
        color = COLORS[index % len(COLORS)]
        points = " ".join(
            f"{_x(i, len(values), frame['plot_w']):.1f},{_y(value, low, high, frame['plot_h']):.1f}"
            for i, value in enumerate(values)
            if value is not None
        )
        elements.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
    _axis_labels(elements, labels, frame["label_positions"])
    elements.append("</svg>")
    Path(path).write_text("\n".join(elements) + "\n", encoding="utf-8")


def area_chart(path: Path, labels: list[str], values: list[float], title: str, ylabel: str) -> None:
    low = min(values + [0.0])
    high = max(values + [0.0])
    pad = (high - low) * 0.08 or 1.0
    elements, frame = _frame(title, ylabel, low - pad, high + pad, len(labels))
    low, high = low - pad, high + pad
    zero_y = _y(0.0, low, high, frame["plot_h"])
    points = [f"{_x(0, len(values), frame['plot_w']):.1f},{zero_y:.1f}"]
    points += [
        f"{_x(i, len(values), frame['plot_w']):.1f},{_y(value, low, high, frame['plot_h']):.1f}"
        for i, value in enumerate(values)
    ]
    points.append(f"{_x(len(values) - 1, len(values), frame['plot_w']):.1f},{zero_y:.1f}")
    elements.append(f'<polygon points="{" ".join(points)}" fill="#fecaca" stroke="#dc2626" stroke-width="1.5"/>')
    _axis_labels(elements, labels, frame["label_positions"])
    elements.append("</svg>")
    Path(path).write_text("\n".join(elements) + "\n", encoding="utf-8")


def bar_chart(path: Path, labels: list[str], values: list[float], title: str, ylabel: str) -> None:
    low = min(values + [0.0])
    high = max(values + [0.0])
    pad = (high - low) * 0.15 or 1.0
    elements, frame = _frame(title, ylabel, low - pad, high + pad, len(labels))
    low, high = low - pad, high + pad
    zero_y = _y(0.0, low, high, frame["plot_h"])
    slot = frame["plot_w"] / max(1, len(values))
    width = max(4.0, slot * 0.58)
    for index, value in enumerate(values):
        x = LEFT + slot * index + (slot - width) / 2
        y = _y(value, low, high, frame["plot_h"])
        top, height = min(y, zero_y), abs(zero_y - y)
        color = "#16a34a" if value >= 0 else "#dc2626"
        elements.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{width:.1f}" height="{height:.1f}" fill="{color}" opacity="0.85"/>')
        elements.append(
            f'<text x="{x + width / 2:.1f}" y="{top - 4 if value >= 0 else top + height + 13:.1f}" '
            f'text-anchor="middle" font-family="{FONT}" font-size="10" fill="#374151">{value:.1f}</text>'
        )
    for index, label in enumerate(labels):
        elements.append(
            f'<text x="{LEFT + slot * index + slot / 2:.1f}" y="{HEIGHT - 24}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="10" fill="#6b7280">{_esc(label)}</text>'
        )
    elements.append("</svg>")
    Path(path).write_text("\n".join(elements) + "\n", encoding="utf-8")


def histogram_chart(path: Path, bins: list[dict], title: str) -> None:
    labels = [str(item["label"]) for item in bins]
    values = [float(item["count"]) for item in bins]
    low, high = 0.0, max(values + [1.0]) * 1.18
    elements, frame = _frame(title, "笔数", low, high, len(bins))
    slot = frame["plot_w"] / max(1, len(values))
    width = max(3.0, slot * 0.72)
    for index, value in enumerate(values):
        x = LEFT + slot * index + (slot - width) / 2
        y = _y(value, low, high, frame["plot_h"])
        elements.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{TOP + frame["plot_h"] - y:.1f}" '
            f'fill="#2563eb" opacity="0.8"/>'
        )
        if value > 0:
            elements.append(
                f'<text x="{x + width / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="9" fill="#374151">{int(value)}</text>'
            )
    for index, label in enumerate(labels):
        elements.append(
            f'<text x="{LEFT + slot * index + slot / 2:.1f}" y="{HEIGHT - 24}" text-anchor="end" '
            f'transform="rotate(-30 {LEFT + slot * index + slot / 2:.1f} {HEIGHT - 24})" '
            f'font-family="{FONT}" font-size="9" fill="#6b7280">{_esc(label)}</text>'
        )
    elements.append("</svg>")
    Path(path).write_text("\n".join(elements) + "\n", encoding="utf-8")
