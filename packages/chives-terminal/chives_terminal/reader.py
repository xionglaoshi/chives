"""Text-only workbench documents measured in terminal cells."""
from functools import lru_cache

from prompt_toolkit.utils import get_cwidth

from .screen import clean, one


def cell(value, style="ink"):
    return ("class:" + style, clean(value))


def wrap(parts, width):
    """Wrap styled text without splitting double-width characters across rows."""
    lines = []
    row = []
    used = 0
    for style, text in parts:
        segment = ""
        for char in text.expandtabs(4):
            size = get_cwidth(char)
            if char == "\n" or (used and used + size > width):
                row.append((style, segment))
                lines.append(row)
                row, segment, used = [], "", 0
            if char != "\n":
                segment += char
                used += size
        row.append((style, segment))
    lines.append(row)
    return lines


class Paper:
    def __init__(self):
        self.blocks = []
        self._render = lru_cache(maxsize=2)(self._lines)

    def text(self, value, style="ink"):
        if value is not None and value != "":
            self.blocks.append(("line", [cell(value, style)]))

    def heading(self, value):
        self.blocks.append(("break", None))
        self.text(value, "title")

    def table(self, headers, rows):
        if rows:
            self.blocks.append(("table", (headers, rows)))

    def lines(self, width):
        return self._render(max(1, width))

    def _lines(self, width):
        lines = []
        for kind, block in self.blocks:
            if kind == "break":
                if lines:
                    lines.append([])
            elif kind == "line":
                lines.extend(wrap(block, width))
            else:
                headers, rows = block
                labels = [cell(h, "dim") for h in headers]
                sizes = [max(get_cwidth(r[i][1]) for r in [labels, *rows]) for i in range(len(headers))]
                if sum(sizes) + 2 * (len(headers)-1) <= width:
                    for row in [labels, *rows]:
                        spans = []
                        for i, (style, value) in enumerate(row):
                            spans.append((style, value))
                            if i < len(row)-1:
                                spans.append(("", " " * (2 + sizes[i] - get_cwidth(value))))
                        lines.append(spans)
                else:
                    for row in rows:
                        for i, (label, value) in enumerate(zip(headers, row)):
                            lines.extend(wrap([cell(("" if i == 0 else "  ") + one(label) + "  ", "dim"), value], width))
                        lines.append([])
        return lines
