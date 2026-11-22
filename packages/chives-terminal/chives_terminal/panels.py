"""Menus, editable fields and readers share the launcher's input loop and focus."""
import asyncio
import time

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import DynamicContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.widgets import TextArea

from .reader import Paper
from .screen import ink, one, clip


class Panels:
    def __init__(self, desk):
        self.desk = desk
        self.kind = "loading"
        self.title = ""
        self.future = None
        self.index = self.offset = 0
        self.options = []
        self.paper = Paper()
        self.accept = self.paging = None
        self.editor = TextArea(multiline=False, height=1)
        self.body = Window(FormattedTextControl(self.render, focusable=True),
                           always_hide_cursor=True, wrap_lines=False)
        self.form_layout = self.body
        self.fields = []
        self.control = DynamicContainer(lambda: self.form_layout if self.kind == "form" else
                                        self.editor if self.kind == "field" else self.body)
        self.layout = HSplit([
            Window(FormattedTextControl(lambda: [ink("accent", "  CHIVES  /  "), ink("title", one(self.title))]),
                   height=1, style="class:band"),
            Window(height=1, char="─", style="class:line"),
            self.control, Window(height=1),
            Window(FormattedTextControl(self.hint), height=1, style="class:band"),
        ], padding=0)
        self.keys = self.bindings()

    def loading(self, title):
        self.title, self.kind = title, "loading"
        self.desk.app.layout.focus(self.body)
        self.desk.app.invalidate()

    async def present(self, kind, title):
        self.kind, self.title = kind, title
        self.future = asyncio.get_running_loop().create_future()
        self.desk.app.layout.focus(self.fields[0][1] if kind == "form" else self.editor if kind == "field" else self.body)
        self.desk.app.invalidate()
        try:
            return await self.future
        finally:
            self.future = None
            self.loading(title)

    def finish(self, value):
        if self.future and not self.future.done():
            self.future.set_result(value)

    async def select(self, title, options, initial=None):
        if not options:
            return await self.info(title, "暂无可用选项")
        self.options = list(options)
        self.index = next((n for n, (key, _) in enumerate(options) if key == initial), 0)
        self.offset = 0
        return await self.present("choice", title)

    async def field(self, title, initial="", password=False):
        self.editor = TextArea(text=initial, multiline=False, password=password, height=1,
                               prompt=[ink("accent", "  ❯  ")], style="class:field")
        self.editor.buffer.cursor_position = len(initial)
        return await self.present("field", title)

    async def form(self, title, specs, save_label="保存"):
        """All fields are visible together. Enum fields cycle in place."""
        self.fields = []
        controls = []
        choices = {}
        for key, label, initial, options in specs:
            if isinstance(options, list):
                choices[key] = [options, next((i for i,(v,_) in enumerate(options) if v == initial), 0)]
                def display(k=key, caption=label):
                    values, i = choices[k]
                    focus = self.desk.app.layout.has_focus(dict(self.fields)[k])
                    return [ink("selected" if focus else "dim", "  " + caption + "  "),
                            ink("accent", "‹ " + values[i][1] + " ›")]
                widget = Window(FormattedTextControl(display, focusable=True), height=1)
            else:
                widget = TextArea(text=initial, multiline=False, password=options == "password", height=1,
                                  prompt=[ink("accent", "  " + label + "  ")], style="class:field")
                widget.buffer.cursor_position = len(initial)
            controls.append(widget)
            self.fields.append((key, widget))
        def save_line():
            focus = self.desk.app.layout.has_focus(save)
            return [ink("selected" if focus else "strong", "  ✓ " + save_label + "  ")]
        save = Window(FormattedTextControl(save_line, focusable=True), height=1)
        self.fields.append((None, save))
        self.form_choices = choices
        self.form_layout = HSplit([*controls, Window(height=1), save, Window()])
        try:
            return await self.present("form", title)
        finally:
            self.fields = []
            self.form_layout = self.body
            self.form_choices = {}

    def form_move(self, steps):
        i = self.form_position()
        self.desk.app.layout.focus(self.fields[(i+steps) % len(self.fields)][1])

    def form_position(self):
        return next(i for i, (_, widget) in enumerate(self.fields) if self.desk.app.layout.has_focus(widget))

    def form_save(self):
        result = {}
        for key, widget in self.fields[:-1]:
            if key in self.form_choices:
                values, i = self.form_choices[key]
                result[key] = values[i][0]
            else:
                result[key] = widget.text.strip()
        self.finish(result)

    async def view(self, title, content, resume_label=None, *, paging=None):
        if isinstance(content, Paper):
            self.paper = content
        else:
            self.paper = Paper()
            self.paper.text(content)
        self.offset, self.accept, self.paging = 0, resume_label, paging
        return await self.present("reader", title)

    def replace_page(self, previous, updated):
        if self.kind == "reader" and self.paper is previous:
            self.paper = updated
            self.desk.app.invalidate()

    async def info(self, title, text):
        await self.view(title, text)

    def hint(self):
        if self.kind == "loading":
            text = "正在处理…"
        elif self.kind == "form":
            text = "Tab / ↑ ↓ 换行    ← → 切选项    Ctrl+S 保存    Esc 取消"
        elif self.kind == "field":
            text = "Enter 确认    Esc 返回"
        elif self.kind == "choice":
            text = "↑ ↓ 选择    Enter 确认    Esc 返回"
            if self.title == "更多设置":
                if self.desk.notice_until > time.monotonic():
                    text = "✓ " + self.desk.saved_notice + "    " + text
        else:
            text = "↑ ↓ / PgUp PgDn 翻阅"
            if self.paging:
                text += "    ← → 切换栏目"
            text += "    Enter " + (self.accept or "返回") + "    Esc 返回"
        return [ink("dim", "  " + text)]

    @property
    def height(self):
        return max(1, self.desk.height-4)

    def click(self, index):
        def handle(event):
            if event.event_type == MouseEventType.MOUSE_UP:
                self.index = index
                self.finish(self.options[index][0])
            else:
                return NotImplemented
        return handle

    def render(self):
        if self.kind == "loading":
            return [ink("dim", "  正在读取或保存，请稍候…")]
        width = max(1, self.desk.width-4)
        if self.kind == "choice":
            self.offset = max(0, min(self.offset, self.index))
            self.offset = max(self.offset, self.index-self.height+1)
            lines = []
            for i in range(self.offset, min(self.offset+self.height, len(self.options))):
                active = self.index == i
                line = ("▸ " if active else "  ") + clip(one(self.options[i][1]), max(1,width-2))
                lines.append([(*ink("selected" if active else "ink", line), self.click(i))])
        else:
            rows = self.paper.lines(width)
            self.offset = min(self.offset, max(0, len(rows)-self.height))
            lines = rows[self.offset:self.offset+self.height]
        result = []
        for i, spans in enumerate(lines):
            result.append(("", "\n  " if i else "  "))
            result.extend(spans)
        return result

    def bindings(self):
        keys = KeyBindings()
        active = Condition(lambda: self.desk.in_dialog)
        reading = active & Condition(lambda: self.kind == "reader")
        moving = active & Condition(lambda: self.kind in ("reader", "choice"))
        @keys.add("up", filter=moving)
        @keys.add("down", filter=moving)
        @keys.add("pageup", filter=moving)
        @keys.add("pagedown", filter=moving)
        @keys.add("home", filter=moving)
        @keys.add("end", filter=moving)
        def move(e):
            key = e.key_sequence[-1].key
            delta = {"up":-1,"down":1,"pageup":-self.height,"pagedown":self.height,
                     "home":-10**9,"end":10**9}[key]
            if self.kind == "choice":
                self.index = max(0, min(self.index+delta, len(self.options)-1))
            else:
                self.offset = max(0, min(self.offset+delta, len(self.paper.lines(max(1,self.desk.width-4)))-1))

        @keys.add("left", filter=reading)
        @keys.add("right", filter=reading)
        def page(e):
            if self.paging:
                self.finish("next" if e.key_sequence[-1].key == "right" else "prev")

        form = active & Condition(lambda: self.kind == "form")
        @keys.add("tab", filter=form)
        @keys.add("s-tab", filter=form)
        @keys.add("down", filter=form)
        @keys.add("up", filter=form)
        def field_move(e):
            self.form_move(-1 if e.key_sequence[-1].key in ("up", "s-tab") else 1)

        enum = form & Condition(lambda: self.fields[self.form_position()][0] in self.form_choices)
        @keys.add("left", filter=enum)
        @keys.add("right", filter=enum)
        @keys.add(" ", filter=enum)
        def cycle(e):
            key = self.fields[self.form_position()][0]
            choices = self.form_choices[key]
            choices[1] = (choices[1] + (-1 if e.key_sequence[-1].key == "left" else 1)) % len(choices[0])

        @keys.add("c-s", filter=form)
        def save(e):
            self.form_save()

        @keys.add("enter", filter=active, eager=True)
        def enter(e):
            if self.kind == "form":
                if self.form_position() == len(self.fields)-1:
                    self.form_save()
                else:
                    self.form_move(1)
            elif self.kind == "choice":
                self.finish(self.options[self.index][0])
            elif self.kind == "field":
                self.finish(self.editor.text)
            elif self.kind == "reader":
                self.finish(bool(self.accept))

        @keys.add("escape", filter=active, eager=True)
        @keys.add("c-c", filter=active)
        def back(e):
            self.finish(None)
            if self.kind == "loading" and self.desk.read_task:
                self.desk.read_task.cancel()
        return keys
