"""Chives' terminal palette, selection board and conversation typography."""
import re
from datetime import datetime

from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style, StyleTransformation
from prompt_toolkit.utils import get_cwidth

# Named ANSI colors use the user's terminal palette on both light and dark themes.
STYLE = Style.from_dict({
    "title": "ansigreen bold", "accent": "ansigreen", "leaf": "ansigreen",
    "brand-shadow": "ansigreen", "green": "ansigreen",
    "up": "ansired bold", "down": "ansigreen bold", "error": "ansired bold",
    "selected": "ansigreen bold noreverse", "user": "ansigreen bold",
    "agent": "ansigreen bold", "strong": "bold",
    "completion-menu.completion.current": "ansigreen bold underline noreverse",
    "completion-menu.meta.completion.current": "ansigreen bold noreverse",
})


class TerminalTheme(StyleTransformation):
    """Apply the host palette after prompt-toolkit merges its own widget styles."""
    def __init__(self, high_contrast):
        self.high_contrast = high_contrast

    def invalidation_hash(self):
        return self.high_contrast()

    def transform_attrs(self, attrs):
        # Built-in completions, scrollbars and text selections have their own fills.
        color = attrs.color if attrs.color in ("ansigreen", "ansired") else ""
        strong = self.high_contrast() and bool(color)
        return attrs._replace(color=color, bgcolor="", reverse=False,
                              bold=attrs.bold or attrs.reverse or strong,
                              underline=attrs.underline or attrs.reverse)


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]|[\u202a-\u202e\u2066-\u2069]")


def clean(text):
    return CONTROL.sub("", str(text))


def one(text):
    return " ".join(clean(text).split())


def clip(text, cells):
    text = one(text)
    if get_cwidth(text) <= cells:
        return text
    n = 0
    for i, char in enumerate(text):
        n += get_cwidth(char)
        if n >= cells:
            return text[:i] + "…"
    return text


def ink(style, text):
    return ("class:" + style, clean(text))


WORDMARK = (
    " ██████╗██╗  ██╗██╗██╗   ██╗███████╗███████╗",
    "██╔════╝██║  ██║██║██║   ██║██╔════╝██╔════╝",
    "██║     ███████║██║██║   ██║█████╗  ███████╗",
    "██║     ██╔══██║██║╚██╗ ██╔╝██╔══╝  ╚════██║",
    "╚██████╗██║  ██║██║ ╚████╔╝ ███████╗███████║",
    " ╚═════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝╚══════╝",
)


def masthead(width, height, count):
    if width < 49 or height < 22:
        return [ink("title", "  CHIVES"), ink("accent", "   老韭菜 · 选择 Bot")]
    result = []
    side = ["", "老 韭 菜", "终 端 投 研 工 作 台", "", f"{count} 位 Bot  /  本地服务", ""]
    for i, row in enumerate(WORDMARK):
        result.append(ink(("title", "accent", "accent", "leaf", "leaf", "brand-shadow")[i], "  " + row))
        if width >= 73:
            result.append(ink("title" if i == 1 else "dim", "     " + side[i]))
        if i < len(WORDMARK)-1:
            result.append(("", "\n"))
    return result


def timestamp(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return ""


def context_label(used, size, compact=False):
    if not isinstance(used, (float, int)) or not isinstance(size, (float, int)) or size <= 0 or used < 0:
        return "上下文 · 待上报"
    pct = round(used * 100 / size)
    if compact:
        return f"上下文 {pct}%"
    filled = max(0, min(8, round(used * 8 / size)))
    return f"上下文 {'━'*filled}{'┄'*(8-filled)} {pct}%  {used:,}/{size:,}"


def body_lines(kind, title, text):
    label = {"user": "❯", "agent": "✦", "reason": "∴", "error": "!", "dim": "·"}[kind]
    rows = [("dim", ""), (kind, f"  {label}  {one(title)}")]
    in_code = False
    for line in clean(text).expandtabs(4).splitlines():
        style = {"user": "ink", "agent": "ink"}.get(kind, kind)
        if kind == "agent":
            if line.lstrip().startswith("```"):
                in_code = not in_code
                style = "dim"
            elif in_code:
                style = "code"
            elif re.match(r"^#{1,6} ", line):
                style, line = "strong", line.lstrip("# ")
        rows.append((style, ("  ┊  " if kind == "reason" else "     ") + line))
    return rows


def tool_line(tool):
    status = tool.get("status", "running")
    symbol = {"completed": "✓", "failed": "×"}.get(status, "›")
    title = one(tool.get("title") or tool.get("toolCallId") or "工具")
    label = {"completed": "完成", "failed": "失败"}.get(status, "调用中")
    return ("error" if status == "failed" else "green", f"     {symbol}  {title}  ·  {label}")


class TranscriptLexer(Lexer):
    def __init__(self):
        self.rows = []

    def lex_document(self, document):
        rows = self.rows
        def line(index):
            if index >= len(rows):
                return []
            style, content = rows[index]
            if style != "ink":
                return [ink(style, content)]
            return [ink("strong" if word.startswith("**") and word.endswith("**") else style, word)
                    for word in re.split(r"(\*\*[^*\n]+\*\*)", content) if word]
        return line

    def invalidation_hash(self):
        return id(self.rows)
