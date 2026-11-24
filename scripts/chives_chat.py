"""Terminal conversations using the same loopback API, turns and storage as the web UI."""
import argparse
from contextlib import contextmanager
import http.client
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from urllib.parse import quote

DEFAULT_BOT = "operator"
# Model and tool output is untrusted terminal text. Preserve normal line breaks.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
NETWORK_ERRORS = (OSError, http.client.HTTPException)


def clean(value):
    return CONTROL.sub("", str(value))


def hint(text):
    print(clean(text), file=sys.stderr, flush=True)


def colored(text, tone="accent", stream=None):
    stream = sys.stderr if stream is None else stream
    if not stream.isatty() or "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return clean(text)
    if tone == "muted":
        return clean(text)
    colors = {"accent": "1;32", "emphasis": "32", "failed": "31"}
    return f"\033[{colors[tone]}m{clean(text)}\033[0m"


def width():
    return min(88, shutil.get_terminal_size().columns)


def fit(text, columns):
    cells = 0
    for index, char in enumerate(text):
        cells += 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if cells > columns - 1:
            return text[:index] + "…"
    return text


def banner(title):
    if not sys.stderr.isatty():
        return
    if width() >= 52:
        rows = ("███ █ █ ███ █ █ ███ ███", "█   █ █  █  █ █ █   █",
                "█   ███  █  █ █ ██  ███", "█   █ █  █  █ █ █     █", "███ █ █ ███  █  ███ ███")
        for row, caption in zip(rows, ("", "", "   老韭菜", "   " + title, "")):
            print("  " + colored(row) + caption, file=sys.stderr)
    else:
        print(colored("CHIVES") + "  " + title, file=sys.stderr)
    print(colored("─" * max(1, width() - 1), "muted"), file=sys.stderr)


def prompt(label):
    print(colored(label, "emphasis"), end="", file=sys.stderr, flush=True)
    return input().strip()


def print_answer(text):
    text = clean(text)
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        print(text, flush=True)
        return
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            print(colored(line, "muted", sys.stdout))
        elif not in_code and re.match(r"^#{1,6} ", line):
            print(colored(line.lstrip("# "), stream=sys.stdout))
        elif not in_code:
            print(re.sub(r"\*\*([^*]+)\*\*", lambda m: colored(m[1], "emphasis", sys.stdout), line))
        else:
            print(line)
    sys.stdout.flush()


class LocalAPI:
    def __init__(self):
        self.port = int(os.environ.get("CHIVES_PORT") or 8880)
        if not 1 <= self.port <= 65535:
            raise ValueError("CHIVES_PORT 超出范围")

    @contextmanager
    def open(self, path, body=None, method=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
            conn.request(method or ("GET" if body is None else "POST"), path, data,
                         {"Content-Type": "application/json", "X-Chives-Kernel-Manager": "local"})
            res = conn.getresponse()
            if res.status >= 400:
                raw = res.read()
                try:
                    error = json.loads(raw)["error"]
                    message = error["message"]
                    if error["code"] == "bot_busy":
                        message = "这位 Bot 正在处理另一轮任务，请稍后再问。"
                except (ValueError, KeyError, TypeError):
                    message = res.reason
                raise RuntimeError(f"HTTP {res.status} · {clean(message)}")
            yield res
        finally:
            conn.close()

    def json(self, path, body=None, method=None):
        with self.open(path, body, method) as res:
            return json.load(res)


def bot_path(bot_id):
    return "/api/bots/" + quote(bot_id, safe="")


def select_bot(bots, name):
    for bot in bots:
        if bot["id"] == name:
            return bot
    matches = [bot for bot in bots if bot["name"] == name]
    if len(matches) == 1:
        return matches[0]
    raise ValueError("Bot 名称有重名或不存在，请用 chives bot 查看编号和标识。")


def menu(bots):
    banner("选择 Bot")
    for i, bot in enumerate(bots, 1):
        default = " · 默认" if bot["id"] == DEFAULT_BOT else ""
        print(colored(f"{i:2}. {bot['name']}", stream=sys.stdout) +
              f"  {clean(bot['id'])}{default}", flush=True)
        if sys.stdout.isatty():
            print("    " + colored(fit(bot["role"], width() - 5), "muted", sys.stdout))
    while True:
        choice = prompt("选择 Bot（编号或名称，回车退出）> ")
        if not choice:
            return None
        if choice.isascii() and choice.isdecimal() and 1 <= int(choice) <= len(bots):
            return bots[int(choice) - 1]
        try:
            return select_bot(bots, choice)
        except ValueError:
            hint("请选择列表中的编号、名称或标识。")


def history(api, bot):
    page = api.json(bot_path(bot["id"]) + "/timeline?limit=16")
    recent = [m for m in page["messages"] if m["role"] in ("user", "bot") and m["kind"] == "text"][-4:]
    if recent:
        print(colored("最近对话", "muted"), file=sys.stderr)
    for m in recent:
        by = "你" if m["role"] == "user" else bot["name"]
        brief = " ".join(m["content"].split())
        hint(f"{by} › {brief[:160]}{'…' if len(brief) > 160 else ''}")


def approval(api, item, view=None):
    if view is not None:
        decision = view.approve(item)
        api.json("/api/approvals/" + quote(item["id"], safe=""), {"decision": decision})
        return
    if not sys.stdin.isatty():
        raise RuntimeError("本轮等待审批。请在网页工作台处理，回复会保存在同一条会话中。")
    hint(f"工具请求审批 · {item['sourceBotName']} · {item['title'] or item['toolCallId']}")
    hint(json.dumps(item["rawInput"], ensure_ascii=False, indent=2))
    try:
        choice = prompt("允许输入 y，拒绝输入 n，回车留待网页处理 > ").lower()
    except EOFError:
        choice = ""
    if choice not in ("y", "n"):
        raise RuntimeError("已离开等待，本次审批仍可在网页处理。")
    api.json("/api/approvals/" + quote(item["id"], safe=""),
             {"decision": "allow" if choice == "y" else "reject"})


def persisted_result(api, task_id, message_id, bot_name, finished=None, view=None):
    """A task can be reused. Only the rows between this question and the next belong to us."""
    detail = api.json("/api/tasks/" + quote(task_id, safe=""))
    rows = iter(detail["messages"])
    if not any(row["id"] == message_id for row in rows):
        raise RuntimeError("任务中找不到刚提交的问题，请在网页工作台查看。")
    answers, notices = [], []
    status = finished or detail["task"]["status"]
    for row in rows:
        if row["role"] == "user":
            status = finished or ("done" if answers else "interrupted")
            break
        if row["role"] == "bot" and row["kind"] == "text":
            answers.append(row["content"])
        if row["role"] == "system" and row["kind"] == "notice":
            notices.append(row["content"])
    if status == "running":
        return False
    if view is not None:
        view.result(answers, detail["task"])
    else:
        if answers and sys.stdout.isatty():
            print(colored("◆ " + bot_name, stream=sys.stdout), flush=True)
        for answer in answers:
            print_answer(answer)
    if status != "done" or not answers:
        reason = notices[-1] if notices else detail["task"].get("errorCode") or status
        raise RuntimeError(f"本轮未能正常返回答案（{clean(reason)}）。可在工作台查看任务详情和模型设置。")
    return True


def reply(api, bot, text, view=None):
    # Subscribe before submitting so an instant answer or reused task cannot race the CLI.
    with api.open("/api/events") as events:
        try:
            accepted = api.json(bot_path(bot["id"]) + "/messages", {"text": text})
        except NETWORK_ERRORS as error:
            raise RuntimeError("发送时连接中断，提交状态待确认。请查看该 Bot 的最近对话后再决定是否重发。") from error
        task_id, message_id = accepted["taskId"], accepted["messageId"]
        if view is not None:
            view.accepted(task_id)
        own_turn = False
        draft = ""
        interactive = view is None and sys.stderr.isatty() and sys.stdout.isatty()
        preview = interactive and os.environ.get("TERM") != "dumb" and "NO_COLOR" not in os.environ
        if interactive:
            print(colored("◇ " + bot["name"] + " · 处理中", "muted"), file=sys.stderr, flush=True)
        try:
            for line in events:
                if not line.startswith(b"data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("botId") != bot["id"] or event.get("taskId") != task_id:
                    continue
                kind = event["type"]
                if kind == "message.created" and event["message"]["role"] == "user":
                    if own_turn:
                        break
                    own_turn = event["message"]["id"] == message_id
                if not own_turn:
                    continue
                if kind == "task.updated" and event["task"]["status"] != "running":
                    if draft:
                        print("\r\033[2K", end="", file=sys.stderr, flush=True)
                        draft = ""
                    persisted_result(api, task_id, message_id, bot["name"], event["task"]["status"], view)
                    return
                if view is not None:
                    view.event(event)
                if interactive and kind in ("tool.started", "tool.ended"):
                    tool = event["tool"]
                    failed = tool["status"] == "failed"
                    mark = "›" if kind == "tool.started" else "×" if failed else "✓"
                    if draft:
                        print("\r\033[2K", end="", file=sys.stderr)
                        draft = ""
                    print(colored(f"  {mark} {fit(tool['title'], width() - 5)}",
                                  "failed" if failed else "muted"), file=sys.stderr, flush=True)
                if kind == "approval.requested":
                    approval(api, event["approval"], view)
                if preview and kind in ("draft.reset", "draft.delta"):
                    if kind == "draft.reset":
                        draft = ""
                    elif event["kind"] == "text":
                        draft = (draft + clean(event["text"]).replace("\n", " "))[-max(1, (width()-3)//2):]
                    print("\r\033[2K" + colored(draft, "muted"), end="", file=sys.stderr, flush=True)
        except NETWORK_ERRORS:
            pass
        finally:
            if draft:
                print("\r\033[2K", end="", file=sys.stderr, flush=True)
    # The POST was accepted. On a broken stream use persisted results; never resend the question.
    note = "实时连接已结束，正在读取已提交任务的结果。"
    if view is None:
        hint(note)
    else:
        view.notice(note)
    while not persisted_result(api, task_id, message_id, bot["name"], view=view):
        for item in api.json("/api/approvals?status=pending"):
            if item["rootTaskId"] == task_id:
                approval(api, item, view)
        time.sleep(1)


def run(args, start_service, stop_service=None):
    command = args[0]
    parser = argparse.ArgumentParser(prog="chives " + command)
    if command == "ask":
        parser.add_argument("--bot", default=DEFAULT_BOT, help="Bot 名称或标识，默认总调度")
        parser.add_argument("question", nargs="*", help="要提问的内容")
    options = parser.parse_args(args[1:])
    if command == "ask":
        question = " ".join(options.question).strip()
        if not question and not sys.stdin.isatty():
            question = sys.stdin.read().strip()
        if not question:
            parser.error('请输入问题，例如 echo "这家公司靠什么赚钱？" | chives')
    api = LocalAPI()
    if command != "ask" and api.port == 8880:
        start_service()
    try:
        bots = api.json("/api/bots")
    except ConnectionRefusedError:
        if command != "ask" or api.port != 8880:
            raise
        start_service()
        bots = api.json("/api/bots")
    bots = [bot for bot in bots if bot.get("hired", True)]
    if not bots:
        raise RuntimeError("工作台还没有已聘用的 Bot。")
    if command == "ask":
        reply(api, select_bot(bots, options.bot), question)
        return
    if sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb":
        from chives_terminal.workbench import Workbench
        Workbench(api, bots, reply, stop_service=stop_service).run()
        return
    bot = menu(bots)
    if bot is None:
        return
    print(colored("◆ " + bot["name"]) + "  " + colored(bot.get("modelDisplayName") or bot["model"], "muted"),
          file=sys.stderr)
    hint("输入问题可连续追问，/exit 退出。")
    history(api, bot)
    while True:
        text = prompt("你 ❯ ")
        if text in ("/exit", "/quit"):
            return
        if text:
            try:
                reply(api, bot, text)
            except RuntimeError as error:
                hint(str(error))
