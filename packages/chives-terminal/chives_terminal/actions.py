"""Terminal settings and commands backed by the workbench API."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import webbrowser
from urllib.parse import quote

from .screen import clean, context_label

PAGES = (("热门榜单", "trends"), ("行情看板", "market"),
         ("用户持仓", "holdings"), ("风格评估", "portrait"))
CHANNEL_NAMES = dict(weixin="微信", wecom="企业微信", feishu="飞书", telegram="Telegram", slack="Slack", discord="Discord")
COMMANDS = {
    "/model": "切换模型", "/history": "浏览并续接历史研究", "/new": "另开研究",
    "/files": "查看交付文件", "/context": "查看上下文", "/stop": "停止当前任务",
    "/bot": "选择 Bot", "/settings": "打开设置", "/help": "命令与快捷键",
    "/exit": "退出终端", "/allow": "允许工具", "/deny": "拒绝工具",
}
PREFS = Path.home() / ".config/chives/terminal.json"
APPEARANCE = {
    "contrast": ("高对比", False), "compact": ("紧凑排版", False),
    "reasoning": ("展开思考摘要", True), "tools": ("详细工具记录", True),
    "timestamps": ("显示时间戳", True),
}


def open_page(fragment=""):
    url = "http://127.0.0.1:8888/" + fragment
    if os.environ.get("SSH_CONNECTION") or not webbrowser.open(url):
        print(f"工作台地址 {url}", flush=True)
        return False
    return True


def preferences():
    try:
        saved = json.loads(PREFS.read_text())
    except (OSError, ValueError):
        saved = {}
    return {key: saved.get(key, default) if isinstance(saved, dict) else default
            for key, (_, default) in APPEARANCE.items()}


class Actions:
    def __init__(self, desk, stop_service):
        self.desk = desk
        self.ui = desk.panels
        self.stop_service = stop_service
        self.prefs = preferences()

    async def api(self, path, body=None, method=None):
        return await asyncio.to_thread(self.desk.api.json, path, body, method)

    async def browse(self, page):
        from .pages import browse
        await browse(self.api, self.ui.view, page, replace_page=self.ui.replace_page)

    async def page(self, fragment):
        opened = await asyncio.to_thread(open_page, fragment)
        if not opened:
            await self.ui.info("网页工作台", "从客户端建立 SSH 转发（本地 8888 → 服务器 127.0.0.1:8888）后访问\nhttp://127.0.0.1:8888/" + fragment)

    async def model(self, bot=None):
        if bot:
            path = "/api/bots/" + quote(bot["id"], safe="") + "/model"
            data = await self.api(path)
            choices = [("", "跟随全局默认 · " + (data.get("defaultModel") or "待配置"))]
            choices += [(item["id"], item["label"] + (" · 当前" if item["id"] == data.get("connection") else ""))
                        for item in data["models"]]
            value = await self.ui.select("切换 " + bot["name"] + " 的模型", choices)
            if value is not None:
                await self.api(path, {"connection": value}, "PUT")
                fresh = await self.api("/api/bots")
                bot.update(next(item for item in fresh if item["id"] == bot["id"]))
        else:
            path = "/api/settings/desk/models"
            data = await self.api(path)
            if not data:
                return await self.ui.info("全局默认模型", "请先添加模型连接")
            items = [(item["id"], clean(item.get("displayName") or item["model"]) +
                       (" · 当前" if item.get("active") else "")) for item in data]
            value = await self.ui.select("全局默认模型", items, next((m["id"] for m in data if m.get("active")), None))
            if value is not None:
                saved = await self.api(path, {"action": "activate", "id": value})
                active = next((m for m in saved if m.get("active") and m["id"] == value), None)
                if not active:
                    raise RuntimeError("服务未确认默认模型变更")
                self.desk.default_model = active.get("displayName") or active["model"]
                self.desk.saved("默认模型已设为 " + self.desk.default_model)

    def toggle_label(self, key):
        return APPEARANCE[key][0] + (" · 开" if self.prefs[key] else " · 关")

    def primary_settings(self):
        name = self.desk.default_model
        return [("default", "默认模型" + (" · " + name if name else "")),
                *((k, self.toggle_label(k)) for k in ("compact", "reasoning", "tools")),
                ("more", "更多设置…")]

    def toggle(self, key):
        # Read current preferences first so other terminals' unrelated changes survive.
        updated = preferences()
        updated[key] = not self.prefs[key]
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=PREFS.parent, mode="w", delete=False) as stream:
            json.dump(updated, stream)
        os.replace(stream.name, PREFS)
        self.prefs = updated
        self.desk.dirty = True
        self.desk.saved(self.toggle_label(key))

    async def add_model(self):
        types = [("openai-completions", "OpenAI 兼容"), ("openai-responses", "OpenAI Responses"),
                 ("anthropic-messages", "Anthropic Messages")]
        values = await self.ui.form("添加模型连接", [
            ("api", "接口类型", types[0][0], types),
            ("baseURL", "服务地址", "", None), ("model", "模型 ID", "", None),
            ("key", "API Key", "", "password")], "验证并保存")
        if values is None:
            return
        key = values.pop("key")
        body = {"config": {**values, "deepseekThinking":False}, "key":key}
        path = "/api/settings/desk/models"
        await self.api(path, {"action":"probe", **body})
        saved = await self.api(path, {"action":"save", **body})
        self.desk.default_model = next((m.get("displayName") or m["model"] for m in saved if m.get("active")), "待配置")
        self.desk.saved("已验证并保存 " + values["model"])

    async def channel(self, item):
        key = item["id"]
        fields = []
        if key in ("weixin", "wecom", "feishu"):
            fields.append(("account", "App ID" if key == "feishu" else "Bot ID", item.get("account") or "", None))
        fields.extend([("key", "密钥（留空沿用）", "", "password"),
                       ("target", "接收会话 ID", item.get("target") or "", None),
                       ("enabled", "主动提醒", bool(item.get("enabled")), [(False,"关闭"),(True,"启用")])])
        values = await self.ui.form(CHANNEL_NAMES.get(key,key) + " · 通讯频道", fields)
        if values is not None:
            await self.api("/api/settings/desk/channels", {"action":"save", "id":key, "account":item.get("account") or "", **values})
            self.desk.saved(CHANNEL_NAMES.get(key,key) + " 配置已保存")

    async def more(self):
        current = None
        while True:
            # A failing channel service must not hide local settings.
            error = None
            try:
                channels = {r["id"]:r for r in await self.api("/api/settings/desk/channels")}
            except (RuntimeError, OSError, ValueError) as exc:
                channels, error = {}, exc
            options = [(k,self.toggle_label(k)) for k in ("contrast","timestamps")]
            options += [("add","添加模型连接"), ("auth","模型授权与连接管理 ↗ 网页")]
            for key,item in channels.items():
                state = "已启用" if item.get("enabled") else "已配置" if item.get("configured") else "待接入"
                options.append(("channel/"+key, CHANNEL_NAMES.get(key,key) + " · " + state))
            if error:
                options.append(("retry","频道读取失败 · 重试"))
            options += [("pair","频道扫码配对 ↗ 网页"), ("web","打开网页版"),
                        ("logs","查看服务日志")]
            if self.stop_service:
                options.append(("stop","停止本地服务并退出"))
            current = await self.ui.select("更多设置", options, current)
            if current is None:
                return
            try:
                if current in APPEARANCE:
                    self.toggle(current)
                elif current == "add":
                    await self.add_model()
                elif current.startswith("channel/"):
                    await self.channel(channels[current.partition("/")[2]])
                elif current in ("auth","pair","web"):
                    await self.page({"auth":"#/settings?tab=models", "pair":"#/settings?tab=channels", "web":""}[current])
                elif current == "logs":
                    await self.ui.view("本地服务日志", await asyncio.to_thread(self.read_log))
                elif current == "stop":
                    bots = await self.api("/api/bots")
                    busy = "、".join(b["name"] for b in bots if b.get("runningTaskId"))
                    title = "确认停止本地服务" + (" · 正在运行 " + busy if busy else "")
                    if await self.ui.view(title, "停止后，网页和终端对话都会中断。Esc 返回。", "确认停止"):
                        await asyncio.to_thread(self.stop_service)
                        self.desk.leave()
                        return
            except (OSError, ValueError, RuntimeError) as exc:
                await self.ui.info("设置未保存" if current != "logs" else "服务日志", str(exc))

    @staticmethod
    def read_log():
        root = Path.home() / ".chives"
        for path in (root / "logs/supervisor.log", root / "runtime/workbench.log"):
            if path.is_file():
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size-32768))
                    return stream.read().decode("utf-8", errors="replace")
        return "当前安装未找到服务日志。"

    async def settings(self, key=None):
        if key is None:
            key = await self.ui.select("设置", self.primary_settings())
        if key in APPEARANCE:
            self.toggle(key)
        elif key == "default":
            await self.model()
        elif key == "more":
            await self.more()

    async def history(self):
        query = await self.ui.field("查找研究 · 输入关键词，留空查看近期研究")
        if query is None:
            return
        bot = self.desk.bot
        path = "/api/bots/" + quote(bot["id"], safe="")
        tasks = {}
        cursor = None
        for _ in range(5 if query.strip() else 1):
            page = await self.api(path + "/timeline?limit=80" + (f"&beforeSeq={cursor}" if cursor else ""))
            for task in reversed(page["tasks"]):
                key = task["id"]
                if not query.strip() or query.casefold() in " ".join(
                    str(m["content"]) for m in page["messages"] if m["taskId"] == key
                ).casefold():
                    tasks[key] = task
            cursor = page.get("nextBeforeSeq")
            if not cursor:
                break
        if not tasks:
            return await self.ui.info("历史研究", "没有找到匹配的记录")
        key = await self.ui.select("历史研究", [(k, t["startedAt"][:10] + "  " + clean(t.get("title") or "未命名"))
                                       for k, t in tasks.items()])
        if key is None:
            return
        task_path = "/api/tasks/" + quote(key, safe="")
        detail = await self.api(task_path)
        content = "\n\n".join(f"{'你' if m['role'] == 'user' else bot['name']}\n{clean(m['content'])}"
                               for m in detail["messages"] if m["role"] in ("user", "bot"))
        if await self.ui.view("原问答", content, "继续研究"):
            await self.api(task_path + "/reopen", {})
            self.desk.task_id = key
            self.desk.new_topic = False
            self.desk.note("下一问将续接选中的研究")

    async def command(self, command):
        desk = self.desk
        if command == "/model":
            await self.model(desk.bot)
        elif command == "/history":
            await self.history()
        elif command == "/settings":
            await self.settings()
        elif command == "/context":
            await self.ui.info("上下文", desk.model(desk.bot) + "\n" + context_label(desk.used, desk.size))
        elif command == "/stop":
            if desk.busy and desk.active_task:
                path = "/api/bots/" + quote(desk.bot["id"], safe="")
                active = desk.active_task
                bots = await self.api("/api/bots")
                if not any(item["id"] == desk.bot["id"] and item["runningTaskId"] == active
                           for item in bots):
                    return desk.note("本轮已结束")
                await self.api(path + "/cancel", {})
                desk.note("已请求停止本轮")
            else:
                desk.note("当前没有可停止的任务")
        elif command == "/files":
            path = "/api/bots/" + quote(desk.bot["id"], safe="")
            files = await self.api(path + "/deliverables?limit=30")
            if desk.task_id:
                files = [item for item in files if item["taskId"] == desk.task_id]
            if not files:
                return await self.ui.info("交付文件", "当前研究还没有交付文件")
            key = await self.ui.select("交付文件", [(i, clean(item["path"])) for i, item in enumerate(files)])
            if key is not None:
                item = files[key]
                if item["kind"] in ("markdown", "md", "text"):
                    def read():
                        path = "/api/deliverables/" + quote(item["id"], safe="") + "/content"
                        with desk.api.open(path) as response:
                            return response.read(1024 * 1024).decode("utf-8", errors="replace")
                    await self.ui.view(item["path"], await asyncio.to_thread(read))
                else:
                    await self.ui.info("交付文件", item["kind"] + "\n" + item["path"])
        elif command == "/help":
            await self.ui.info("命令与快捷键", "\n".join(k + "  " + v for k, v in COMMANDS.items()))
