"""Full-screen selection board and chat. The workbench API owns every conversation."""
import asyncio
from concurrent.futures import Future
import json
import os
import socket
import threading
import time
from urllib.parse import quote

from prompt_toolkit.application import Application
from prompt_toolkit.document import Document
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.containers import Float, FloatContainer
from .actions import Actions, COMMANDS, PAGES
from .panels import Panels
from .pages import DESK
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import ConditionalContainer, DynamicContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import TextArea

from .screen import STYLE, TerminalTheme, TranscriptLexer, body_lines, clean, clip, context_label, ink, masthead, one, timestamp, tool_line


def panel(content, height=1, style="", **kwargs):
    return Window(FormattedTextControl(content), height=height, style=style, **kwargs)


class TurnView:
    """Bridge the blocking HTTP stream to the terminal's UI thread."""
    def __init__(self, desk, loop):
        self.desk = desk
        self.loop = loop

    def post(self, fn, *args):
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(fn, *args)

    def accepted(self, task_id):
        self.post(self.desk.accepted, task_id)

    def event(self, event):
        self.post(self.desk.handle_event, event)

    def result(self, answers, task):
        self.post(self.desk.show_result, answers, task)

    def notice(self, text):
        self.post(self.desk.note, text)

    def approve(self, item):
        answer = Future()
        self.post(self.desk.show_approval, item, answer)
        return answer.result()


class SlashMenu(Completer):
    def __init__(self, desk):
        self.desk = desk

    def get_completions(self, document, complete_event):
        text = document.text
        if not text.startswith("/") or document.cursor_position != len(text):
            return
        commands = list(COMMANDS)
        if self.desk.pending:
            commands = ["/allow", "/deny"] + commands[:-2]
        else:
            commands = commands[:-2]
        query = text[1:].casefold()
        for command in commands:
            if command[1:].startswith(query) or query in COMMANDS[command]:
                yield Completion(command, start_position=-len(text), display_meta=COMMANDS[command])


class Workbench:
    def __init__(self, api, bots, reply, stop_service=None, **terminal):
        self.api, self.reply = api, reply
        self.bots = [b for b in bots if b.get("hired", True)]
        self.roster_generation = 0
        self.panels = Panels(self)
        self.actions = Actions(self, stop_service)
        self.boards = []
        self.board_status = "读取榜单中…"
        self.default_model = ""
        self.saved_notice = ""
        self.notice_until = 0.0
        self.read_task = None
        self.column = 0
        self.section_row = 0
        self.in_dialog = False
        self.new_topic = False
        self.task_id = None
        self.active_task = None
        self.host = one(socket.gethostname().split(".")[0])
        self.generation = 0
        self.bot = None
        self.selected = next((i for i, b in enumerate(self.bots) if b.get("permanent", b["id"] == "operator")), 0)
        self.busy = self.loading = False
        self.pending = None
        self.message = ""
        self.used = self.size = None
        self.started = 0
        self.activity = ""
        self.history_rows = []
        self.previous = None
        self.logged_tools = set()
        self.rows = []
        self.live = []
        self.dirty = self.follow = True
        self.lexer = TranscriptLexer()
        self.transcript = TextArea(read_only=True, focusable=False, scrollbar=False, lexer=self.lexer,
                                   wrap_lines=True, style="class:ink")
        self.search = TextArea(multiline=False, height=1, prompt="  ⌕  ", style="class:field")
        self.search.buffer.on_text_changed += self.filter_changed
        self.editor = TextArea(multiline=True, height=D(min=1, max=5), dont_extend_height=True,
                               completer=SlashMenu(self), complete_while_typing=True,
                               prompt=[ink("accent", " ❯  ")], style="class:field", wrap_lines=True)
        self.menu_list = Window(FormattedTextControl(self.menu_rows), always_hide_cursor=True,
                                width=D(min=1, preferred=1, weight=1))
        self.picker = self.picker_layout()
        self.chat = self.chat_layout()
        shared = HSplit([panel(self.topline, style="class:band"),
                         DynamicContainer(lambda: self.picker if self.bot is None else self.chat)])
        self.app = Application(layout=Layout(FloatContainer(DynamicContainer(lambda: self.panels.layout if self.in_dialog else shared), [Float(xcursor=True, ycursor=True,
                               allow_cover_cursor=False, content=CompletionsMenu(max_height=9, scroll_offset=1, display_arrows=True))]),
                               focused_element=self.search), key_bindings=merge_key_bindings([self.bindings(), self.panels.keys]),
                               style=STYLE, full_screen=True, mouse_support=Condition(lambda: self.bot is None),
                               style_transformation=TerminalTheme(lambda: self.actions.prefs["contrast"]),
                               min_redraw_interval=1/30,
                               refresh_interval=.5, before_render=self.prepare,
                               color_depth=ColorDepth.DEPTH_1_BIT if "NO_COLOR" in os.environ else None,
                               **terminal)
        self.app.ttimeoutlen = .25
        self.app.pre_run_callables.append(self.start_catalog)

    @property
    def width(self):
        return self.app.output.get_size().columns if hasattr(self, "app") else 80

    @property
    def height(self):
        return self.app.output.get_size().rows

    @property
    def list_width(self):
        return min(48, max(30, self.width * 2 // 5))

    def run(self):
        self.app.run()

    def topline(self):
        where = "快速启动" if self.bot is None else one(self.bot["name"])
        left = [ink("accent", "  ✦  CHIVES"), ink("dim", "    /    "), ink("ink", where)]
        host = "●  " + clip(self.host, 24)
        gap = self.width - sum(get_cwidth(s) for _, s in left) - get_cwidth(host) - 2
        return left + ([ink("green", " "*gap + host)] if gap > 2 else [])

    def picker_layout(self):
        bot_column = HSplit([self.menu_list, Window(height=1, char="─", style="class:line"),
                             panel(self.employment_row)], width=D(min=1, preferred=1, weight=1))
        self.launch_windows = [bot_column] + [
            Window(FormattedTextControl(lambda c=c: self.section_items(c), focusable=True),
                   width=D(min=1, preferred=1, weight=1), always_hide_cursor=True)
            for c in (1, 2)]
        self.launch_columns = VSplit(self.launch_windows, padding=2, padding_char="│", padding_style="class:line")
        return HSplit([
            Window(height=1), panel(lambda: masthead(self.width, self.height, len(self.bots)),
                                    height=lambda: 6 if self.width >= 49 and self.height >= 22 else 1),
            panel(self.section_tabs),
            Window(char="─", height=1, style="class:line"),
            DynamicContainer(lambda: self.launch_columns if self.width >= 76 else self.launch_windows[self.column]),
            ConditionalContainer(HSplit([panel(lambda: [ink("dim", "  查找名称、职责或编号")]), self.search]),
                                 Condition(lambda: self.column == 0)),
            panel(self.launch_hint),
        ])

    def saved(self, notice):
        self.saved_notice = notice
        self.notice_until = time.monotonic()+4
        self.app.invalidate()

    def launch_hint(self):
        if self.notice_until > time.monotonic():
            return [ink("strong", "  ✓ " + self.saved_notice)]
        return [ink("accent", "  ↑ ↓"), ink("dim", " 选择    Tab 切栏    "),
                ink("accent", "Enter"), ink("dim", " 打开或切换    Esc 退出")]

    def launch_click(self, column, row=None):
        def select(event):
            if event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            self.switch_column(column)
            self.section_row = row or 0
            if row is not None:
                if column == 0:
                    self.selected = row
                self.open_selected()
        return select

    def employment_row(self):
        row = len(self.matches())
        active = self.column == 0 and self.selected == row
        return [(*ink("selected" if active else "accent", ("  ▸ " if active else "    ") + "聘用管理"),
                 self.launch_click(0, row))]

    async def reload_bots(self):
        self.roster_generation += 1
        generation = self.roster_generation
        roster = await self.actions.api("/api/bots")
        if generation != self.roster_generation:
            return
        current = self.current()
        self.bots = [b for b in roster if b.get("hired", True)]
        items = self.matches()
        if current is None:
            self.selected = len(items)
        else:
            self.selected = next((i for i, (_,b) in enumerate(items) if b["id"] == current["id"]), 0)
        self.app.invalidate()

    async def watch_roster(self):
        while True:
            await asyncio.sleep(4)
            if self.in_dialog or self.bot is not None:
                continue
            try:
                roster = await self.actions.api("/api/settings/desk/employment")
                if {b["id"] for b in roster if b["hired"]} != {b["id"] for b in self.bots}:
                    await self.reload_bots()
            except (OSError, RuntimeError, ValueError):
                continue

    def start_catalog(self):
        async def refresh_boards():
            while True:
                try:
                    await self.load_boards()
                except (OSError, RuntimeError, ValueError):
                    self.board_status = "暂未取得榜单 · 回车重试"
                self.app.invalidate()
                await asyncio.sleep(60)
        async def load_model():
            try:
                items = await self.actions.api(DESK+"models")
                self.default_model = next((r.get("displayName") or r["model"] for r in items if r.get("active")), "待配置")
                self.app.invalidate()
            except (OSError, RuntimeError, ValueError):
                pass
        self.app.create_background_task(self.watch_roster())
        self.app.create_background_task(refresh_boards())
        self.app.create_background_task(load_model())

    async def load_boards(self):
        payload = await self.actions.api(DESK+"hotspots")
        boards = (payload.get("snapshot") or {}).get("boards") or {}
        old_key = self.page_items()[self.section_row][0] if self.column == 1 else None
        self.boards = [("board/"+key, one(board["title"])) for key, board in boards.items()]
        self.board_status = "等待首版榜单 · 回车刷新"
        if old_key is not None:
            self.section_row = next((i for i,(key,_) in enumerate(self.page_items()) if key == old_key), 0)

    def page_items(self):
        return (self.boards or [("trends", self.board_status)]) + [(key, label) for label,key in PAGES if key != "trends"]

    def switch_column(self, column):
        self.column = column
        self.section_row = 0
        self.app.layout.focus(self.launch_windows[column] if column else self.search)

    def open_selected(self):
        if self.column == 1:
            key, title = self.page_items()[self.section_row]
            action = self.load_boards() if key == "trends" else self.actions.browse(key)
            self.dialog(action, title, read_only=True)
        elif self.column == 2:
            key, title = self.actions.primary_settings()[self.section_row]
            self.dialog(self.actions.settings(key), title)
        elif self.current():
            self.enter(self.current())
        else:
            self.dialog(self.actions.employment(), "聘用管理")

    def section_tabs(self):
        result = []
        wide = self.width >= 76
        for i, title in enumerate(("选 Bot", "工作台", "设置")):
            label = "  " + title + "  "
            if wide and i < 2:
                label += " " * max(0, (self.width-4)//3 + 2 - get_cwidth(label))
            result.append((*ink("selected" if self.column == i else "accent", label), self.launch_click(i)))
        return result

    def section_items(self, column):
        options = self.page_items() if column == 1 else self.actions.primary_settings()
        width = (self.width-4)//3 if self.width >= 76 else self.width
        spans = [ink("title", "  热门榜单"), ("", "\n")] if column == 1 else []
        for i,(key, label) in enumerate(options):
            active = self.column == column and i == self.section_row
            if i:
                spans.append(("", "\n"))
            child = column == 1 and (key.startswith("board/") or key == "trends")
            prefix = ("    " if child else " ") + ("▸ " if active else "  ")
            if active:
                spans.append(("[SetCursorPosition]", ""))
            spans.append((*ink("selected" if active else "ink", prefix + clip(label, max(1,width-get_cwidth(prefix)))),
                          self.launch_click(column, i)))
        return spans

    def dialog(self, operation, title="工作台", read_only=False):
        if self.in_dialog:
            operation.close()
            return
        self.in_dialog = True
        self.panels.loading(title)

        async def run():
            try:
                await operation
            except Exception as exc:
                await self.panels.info("操作未完成", str(exc) or type(exc).__name__)
            finally:
                self.in_dialog = False
                self.read_task = None
                self.app.layout.focus(self.editor if self.bot else self.launch_windows[self.column] if self.column else self.search)
                self.app.invalidate()
        task = self.app.create_background_task(run())
        if read_only:
            self.read_task = task

    def chat_layout(self):
        return HSplit([
            self.transcript,
            panel(self.activity_bar),
            VSplit([Window(char="│", width=1, style="class:line"), self.editor,
                    Window(char="│", width=1, style="class:line")]),
            panel(lambda: [ink("line", "╰"+"─"*max(0, self.width-2)+"╯")]),
            panel(self.status, style="class:band", height=lambda: 2 if self.width < 76 else 1, wrap_lines=True),
            panel(self.keys_line),
        ])

    def matches(self):
        query = one(self.search.text).casefold().strip()
        return [(i, b) for i, b in enumerate(self.bots, 1) if not query or str(i) == query
                or query in (b["name"]+" "+b["id"]+" "+b["role"]).casefold()]

    def current(self):
        items = self.matches()
        return items[self.selected][1] if 0 <= self.selected < len(items) else None

    def filter_changed(self, _):
        self.selected = 0
        self.message = ""

    def menu_rows(self):
        items = self.matches()
        if not items:
            return [ink("dim", "  没有匹配的 Bot，删减关键词再试。")]
        spans = []
        for j, (i, b) in enumerate(items):
            active = self.column == 0 and j == self.selected
            if j:
                spacious = len(items) * 3 <= self.height - 15
                spans.append(("", "\n\n" if spacious else "\n"))
            if active:
                spans.append(("[SetCursorPosition]", ""))
            sel = "selected" if active else "ink"
            limit = max(18, (self.width-4)//3) if self.width >= 76 else self.width-1
            name = clip(f"{i:02}   {b['name']}" + ("  · 默认" if b.get("permanent", b["id"] == "operator") else ""), limit-7)
            row = f"  {'▸' if active else ' '}  " + name
            spans.extend([(*ink(sel, row + " "*max(0, limit-get_cwidth(row))), self.launch_click(0, j)),
                          ink("dim", "\n          " + clip(b["id"], limit - 11))])
        return spans

    def details(self):
        bot = self.current()
        if not bot:
            return []
        state = {"idle": "待命", "working": "工作中", "starting": "启动中",
                 "awaiting_approval": "等待审批", "error": "需要检查"}.get(bot.get("status"), "待命")
        return [ink("accent", f"   ✦  {bot['name']}\n\n"),
                ink("ink", "   " + one(bot["role"])+"\n\n"),
                ink("dim", "   模型   "), ink("ink", self.model(bot)+"\n"),
                ink("dim", "   状态   "), ink("green", state+"\n"),
                ink("dim", f"   已配置 {len(bot.get('skills', []))} 项技能 · {len(bot.get('mcp', []))} 个 MCP")]

    @staticmethod
    def model(bot):
        value = one(bot.get("modelDisplayName") or bot.get("model") or "待配置")
        return "工作台默认模型" if value == "default" else value

    def activity_bar(self):
        label = self.message or self.activity or ("正在读取会话" if self.loading else "就绪")
        if self.busy:
            label = f"{label} · {int(time.monotonic()-self.started)}s"
        prefix = "审批" if self.pending else "输入"
        text = clip(f"╭─ {prefix}  ·  {label}", self.width - 4)
        return [ink("accent", text + " "), ink("line", "─" * max(0, self.width - get_cwidth(text)-2) + "╮")]

    def status(self):
        model = self.model(self.bot)
        compact = self.width < 76
        label = context_label(self.used, self.size, compact=False)
        if compact:
            return [ink("accent", "  ◈ " + clip(model, self.width-6)), ("","\n"),
                    ink("green", "  " + clip(label, self.width-3))]
        return [ink("accent", "  ◈ " + clip(model, max(14, self.width-48))),
                ink("line", "    │    "), ink("green", label)]

    def keys_line(self):
        text = "Enter 发送   Alt+Enter 换行   PgUp/PgDn 翻阅   /history 更早记录   /bot 切换"
        if self.pending:
            text = "/allow 允许  ·  /deny 拒绝  ·  Ctrl+D 离开"
        elif self.width < 76:
            text = "Enter 发送   PgUp 翻阅   /help 帮助"
        return [ink("dim", "  " + text)]

    def bindings(self):
        kb = KeyBindings()
        picking = Condition(lambda: self.bot is None and not self.in_dialog)
        chatting = Condition(lambda: self.bot is not None and not self.in_dialog)
        @kb.add("tab", filter=picking)
        @kb.add("right", filter=picking)
        def next_column(e):
            self.switch_column((self.column + 1) % 3)
        @kb.add("s-tab", filter=picking)
        @kb.add("left", filter=picking)
        def previous_column(e):
            self.switch_column((self.column - 1) % 3)
        @kb.add("end", filter=picking & Condition(lambda: self.column == 0))
        def last_bot_action(e):
            self.selected = len(self.matches())

        @kb.add("up", filter=picking)
        def up(e):
            if self.column:
                self.section_row = max(0, self.section_row-1)
            else:
                self.selected = max(0, self.selected-1)
        @kb.add("down", filter=picking)
        def down(e):
            if self.column:
                count = len(self.page_items() if self.column == 1 else self.actions.primary_settings())
                self.section_row = min(count-1, self.section_row+1)
            else:
                self.selected = max(0, min(len(self.matches()), self.selected+1))
        @kb.add("enter", filter=picking)
        def choose(e):
            self.open_selected()
        @kb.add("enter", filter=chatting)
        def send(e):
            buffer = self.editor.buffer
            state = buffer.complete_state
            if state and state.completions:
                buffer.apply_completion(state.current_completion or state.completions[0])
            self.submit()
        @kb.add("escape", "enter", filter=chatting)
        @kb.add("c-j", filter=chatting)
        def newline(e):
            self.editor.buffer.insert_text("\n")
        @kb.add("pageup", filter=chatting)
        def older(e):
            self.scroll(-1)
        @kb.add("pagedown", filter=chatting)
        def newer(e):
            self.scroll(1)
        @kb.add("escape", filter=picking, eager=True)
        def exit_menu(e):
            self.app.exit()
        @kb.add("c-c", filter=picking|chatting)
        def clear(e):
            if e.current_buffer.text:
                e.current_buffer.reset()
            elif self.bot and not self.busy:
                self.pick()
            else:
                self.leave()
        @kb.add("c-d", filter=picking|chatting)
        def exit_now(e):
            self.leave()
        return kb

    def scroll(self, direction):
        buf = self.transcript.buffer
        info = self.transcript.window.render_info
        if info:
            visible = info.visible_line_to_row_col
            if not visible:
                return
            row, col = visible[min(visible) if direction < 0 else max(visible)]
            doc = buf.document
            budget = max(1, info.window_height-2)
            while budget > 0:
                # A wrapped paragraph can occupy several complete screens.
                line = doc.lines[row]
                span = line[:col] if direction < 0 else line[col:]
                if get_cwidth(span) >= budget * info.window_width:
                    chars = reversed(span) if direction < 0 else span
                    cells = 0
                    for char in chars:
                        col += direction
                        cells += get_cwidth(char)
                        if cells >= budget * info.window_width:
                            break
                    break
                budget -= max(1, (get_cwidth(span)+info.window_width-1)//max(1, info.window_width))
                next_row = row + direction
                if not 0 <= next_row < doc.line_count:
                    col = 0 if direction < 0 else len(line)
                    break
                row = next_row
                col = len(doc.lines[row]) if direction < 0 else 0
            buf.cursor_position = doc.translate_row_col_to_index(row, col)
            self.follow = buf.cursor_position == len(buf.text)

    def leave(self):
        if self.pending:
            self.pending.set_exception(RuntimeError("已离开审批"))
            self.pending = None
        self.app.exit()

    def pick(self):
        self.bot = None
        self.column = 0
        self.search.text = ""
        self.app.layout.focus(self.search)

    def enter(self, bot):
        self.generation += 1
        self.bot = bot
        self.used = self.size = self.previous = self.task_id = None
        self.new_topic = False
        self.message = self.activity = ""
        self.rows, self.history_rows, self.live = [], [], []
        self.logged_tools = set()
        self.follow = self.dirty = True
        self.editor.text = ""
        self.app.layout.focus(self.editor)
        self.load_history(first=True)

    def load_history(self, first=False):
        bot = self.bot
        generation = self.generation
        self.loading = True
        path = "/api/bots/" + quote(bot["id"], safe="") + "/timeline?limit=24"
        if not first:
            path += "&beforeSeq=" + str(self.previous)
        async def load():
            try:
                page = await asyncio.to_thread(self.api.json, path)
                if self.bot is not bot or self.generation != generation:
                    return
                self.previous = page.get("nextBeforeSeq") if page.get("hasMore") else None
                rows = []
                entries = [(m["createdAt"], m["seq"], m) for m in page["messages"]]
                for t in page.get("toolEvents", []):
                    if t["id"] not in self.logged_tools:
                        self.logged_tools.add(t["id"])
                        entries.append((t["startedAt"], float("inf"), t))
                for _, _, entry in sorted(entries, key=lambda x: x[:2]):
                    if "role" not in entry:
                        if self.actions.prefs["tools"]:
                            rows.append(tool_line(entry))
                    elif entry["role"] in ("user","bot") and entry["kind"] == "text":
                        user = entry["role"] == "user"
                        title = ("你" if user else bot["name"])+"   "+(timestamp(entry["createdAt"]) if self.actions.prefs["timestamps"] else "")
                        rows.extend(body_lines("user" if user else "agent", title, entry["content"]))
                    elif entry["kind"] == "notice":
                        rows.extend(body_lines("dim", "服务记录", entry["content"]))
                self.history_rows = rows + self.history_rows
                self.dirty = True
                if first:
                    tid = next((m["taskId"] for m in reversed(page["messages"]) if m.get("taskId")), None)
                    self.task_id = tid
                    task = next((t for t in page["tasks"] if t["id"] == tid), {})
                    self.usage(task.get("lastContextUsed"), task.get("lastContextSize"))
                else:
                    self.follow = False
                    self.transcript.buffer.cursor_position = 0
                self.message = ""
            except Exception as exc:
                if self.bot is bot and self.generation == generation:
                    self.note("读取会话失败 · " + str(exc))
            finally:
                if self.bot is bot and self.generation == generation:
                    self.loading = False
                self.app.invalidate()
        self.app.create_background_task(load())

    def prepare(self, app):
        if not self.bot or not self.dirty:
            return
        self.dirty = False
        rows = self.history_rows + self.rows
        for block in self.live:
            if block[0] == "tool":
                rows.append(tool_line(block[1]))
            else:
                kind, title, text = block
                rows.extend(body_lines(kind, title, text))
        if not rows:
            rows = [("accent", "  ✦  " + one(self.bot["name"])), ("dim", ""),
                    ("ink", "  " + one(self.bot["role"]))]
        if self.actions.prefs["compact"]:
            rows = [row for row in rows if row[1]]
        self.lexer.rows = rows
        text = "\n".join(s for _, s in rows)
        pos = len(text) if self.follow else min(len(text), self.transcript.buffer.cursor_position)
        self.transcript.buffer.set_document(Document(text, pos), bypass_readonly=True)

    def note(self, msg):
        self.message = one(msg)
        self.app.invalidate()

    def usage(self, used, size):
        if isinstance(used, int) and isinstance(size, int) and size > 0:
            self.used, self.size = used, size

    def submit(self):
        text = self.editor.text.strip()
        if not text:
            return
        if self.pending and text in ("/allow", "/deny"):
            self.pending.set_result("allow" if text == "/allow" else "reject")
            self.pending = None
            self.editor.text = ""
            self.note("已提交审批决定")
            return
        if text in ("/exit","/quit"):
            self.leave()
            return
        if text.startswith("/") and text not in COMMANDS:
            self.note("未识别的命令，输入 / 查看可用操作")
            return
        if text == "/stop":
            self.editor.text = ""
            self.dialog(self.actions.command(text))
            return
        if self.busy or self.loading:
            self.note("等待本轮结束后发送，草稿已保留" if not self.pending else "请先输入 /allow 或 /deny")
            return
        self.editor.buffer.append_to_history()
        self.editor.text = ""
        if text == "/bot":
            self.pick()
        elif text == "/new":
            self.new_topic = True
            self.note("下一条问题将另开研究")
        elif text.startswith("/"):
            self.dialog(self.actions.command(text))
        else:
            self.start_turn(text)

    def start_turn(self, text):
        self.busy = self.follow = self.dirty = True
        self.started = time.monotonic()
        self.message, self.activity = "", "正在提交"
        self.rows.extend(body_lines("user", "你", text))
        self.live = []
        view = TurnView(self, asyncio.get_running_loop())
        bot = self.bot
        new_topic = self.new_topic
        def work():
            error = None
            try:
                self.reply(self.api, bot, "新问题：" + text if new_topic else text, view=view)
            except Exception as exc:
                error = str(exc)
            finally:
                view.post(self.end_turn, error)
        threading.Thread(target=work, daemon=True).start()

    def show_approval(self, item, answer):
        self.pending = answer
        self.rows.extend(body_lines("user", "工具请求审批 · " + one(item.get("title") or item["toolCallId"]),
                                    json.dumps(item["rawInput"], ensure_ascii=False, indent=2)))
        self.dirty = True
        self.note("等待你的决定 · /allow 或 /deny")

    def accepted(self, task_id):
        self.active_task = self.task_id = task_id
        self.new_topic = False

    def handle_event(self, event):
        kind = event["type"]
        if kind == "draft.delta":
            reason = event["kind"] == "reasoning"
            style, title = ("reason","思考摘要") if reason else ("agent",self.bot["name"])
            if reason and not self.actions.prefs["reasoning"]:
                self.activity = "正在分析"
                self.app.invalidate()
                return
            if not self.live or self.live[-1][0] != style:
                self.live.append([style, title, ""])
            self.live[-1][2] += clean(event["text"])
            self.activity = "正在分析" if reason else "正在回复"
        elif kind == "draft.reset":
            self.live = [b for b in self.live if b[0] == "tool"]
            self.activity = "正在分析"
        elif kind == "draft.commit" and event.get("text"):
            self.live = [b for b in self.live if b[0] != "agent"]
            self.live.append(["agent", self.bot["name"], clean(event["text"])])
        elif kind in ("tool.started","tool.ended"):
            tool = event["tool"]
            for block in self.live:
                if block[0] == "tool" and block[1]["id"] == tool["id"]:
                    block[1] = tool
                    break
            else:
                self.live.append(["tool", tool])
            self.activity = one(tool["title"]) if kind == "tool.started" else "正在整理"
            if not self.actions.prefs["tools"]:
                self.live = [block for block in self.live if block[0] != "tool"]
        elif kind == "usage":
            self.usage(event["usage"]["used"], event["usage"]["size"])
        elif kind == "task.started":
            self.used = self.size = None
            self.activity = "正在处理"
        elif kind == "task.updated":
            self.activity = "正在处理"
        self.dirty = True
        self.app.invalidate()

    def show_result(self, answers, task):
        self.usage(task.get("lastContextUsed"), task.get("lastContextSize"))
        # Replace tentative text with the persisted answer only once.
        self.live = [b for b in self.live if b[0] != "agent"]
        for answer in answers:
            self.live.append(["agent", self.bot["name"], answer])

    def end_turn(self, error):
        for b in self.live:
            if b[0] == "tool":
                self.rows.append(tool_line(b[1]))
            else:
                self.rows.extend(body_lines(*b))
        self.live = []
        if error:
            self.rows.extend(body_lines("error", "本轮提示", error))
        self.rows.append(("dim", f"     ─  {time.monotonic()-self.started:.1f}s"))
        self.busy = False
        self.active_task = None
        self.message = self.activity = ""
        self.dirty = True
        self.app.invalidate()
