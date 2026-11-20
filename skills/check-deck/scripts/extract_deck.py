#!/usr/bin/env python3
"""Read a .pptx into the JSON report the deck checks consume.

Usage:
    python extract_deck.py presentation.pptx > deck.json

The report keeps the slide structure a prose export throws away: one entry per
slide with its `index`, `title`, `layout`, its `text` lines in shape order, a
`shapes` inventory of names, positions, character counts and font sizes, `tables`
as `cells` (a list of rows of strings), `charts` as `series` values against
`categories`, and speaker `notes`. That structure is the point: a figure can then be reported
as slide 4, `Table 3 r2c2`, and a table cell can be read through the row label
and column header that say what it is, neither of which survives a prose export.

Requires python-pptx (`pip install python-pptx`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def extract(path: Path) -> dict:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    slides: list[dict] = []

    def is_hidden(shape) -> bool:
        element = getattr(shape, "_element", None)
        if element is None:
            return False
        holder = element.find(".//{*}cNvPr")
        return holder is not None and str(holder.get("hidden", "")).lower() in ("1", "true")

    def placeholder(shape) -> str:
        try:
            return str(shape.placeholder_format.type) if shape.is_placeholder else ""
        except (AttributeError, ValueError):
            return ""

    def walk(shape, lines: list[str], tables: list[dict], charts: list[dict]) -> dict:
        name = getattr(shape, "name", "") or "shape"
        entry = {"name": name, "top": (getattr(shape, "top", 0) or 0) / 914400,
                 "chars": 0, "hidden": is_hidden(shape), "placeholder": placeholder(shape),
                 "font_sizes": []}
        if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP:
            entry["kind"] = "group"
            entry["members"] = [walk(member, lines, tables, charts) for member in shape.shapes]
            entry["chars"] = sum(member["chars"] for member in entry["members"])
            return entry
        if getattr(shape, "has_table", False) and shape.has_table:
            rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
            tables.append({"shape": name, "rows": len(rows), "cells": rows})
            for row in rows:
                lines.append(" ".join(cell for cell in row if cell))
            entry["kind"] = "table"
            return entry
        if getattr(shape, "has_chart", False) and shape.has_chart:
            chart = shape.chart
            try:
                categories = [str(category) for category in chart.plots[0].categories]
            except (AttributeError, IndexError, ValueError):
                categories = []  # an XY chart carries x_values on the series, not categories
            series = []
            for item in chart.series:
                values = [None if value is None else float(value) for value in item.values]
                series.append({"name": item.name, "values": values})
            charts.append({"shape": name, "categories": categories, "series": series})
            entry["kind"] = "chart"
            return entry
        entry["kind"] = "shape"
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            own = [paragraph.text for paragraph in shape.text_frame.paragraphs if paragraph.text]
            lines.extend(own)
            entry["chars"] = sum(len(line) + 1 for line in own)
            entry["font_sizes"] = sorted({
                round(run.font.size.pt, 1)
                for paragraph in shape.text_frame.paragraphs
                for run in paragraph.runs
                if run.font.size is not None
            })
        return entry

    for index, slide in enumerate(prs.slides, start=1):
        lines: list[str] = []
        tables: list[dict] = []
        charts: list[dict] = []
        shapes = [walk(shape, lines, tables, charts) for shape in slide.shapes]
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        slides.append({
            "index": index,
            "title": slide.shapes.title.text if slide.shapes.title else "",
            "layout": slide.slide_layout.name,
            "text": lines,
            "shapes": shapes,
            "tables": tables,
            "charts": charts,
            "notes": notes,
        })
    return {
        "file": str(path),
        "slide_size_in": [prs.slide_width / 914400, prs.slide_height / 914400],
        "slides": slides,
    }


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    path = Path(argv[0]).expanduser()
    if not path.exists():
        print(json.dumps({"status": "error", "message": f"no such file: {path}"}))
        return 1
    try:
        report = extract(path)
    except Exception as exc:  # a corrupt deck or a missing python-pptx
        print(json.dumps({"status": "error", "message": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
