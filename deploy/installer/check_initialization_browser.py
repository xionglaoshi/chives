"""Check the installed Chives UI in Chromium from an isolated browser profile."""
import json
import sys
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import expect, sync_playwright

STEPS = (
    "添加模型", "完成用户画像评测问卷", "填写用户基本信息", "添加持仓股票",
    "添加关注股票", "连接微信", "创建盯盘任务", "创建每日投研简报任务",
)

def numbered(labels):
    return [f"待办项{index}：{label}" for index, label in enumerate(labels, 1)]


def desk(page, method, section, data=None, status=200):
    response = page.request.fetch(
        f"/api/settings/desk/{section}", method=method, data=data,
        headers={"X-Chives-Kernel-Manager": "local"},
    )
    assert response.status == status, (section, response.status, response.text())
    return response.json()


@contextmanager
def model_provider():
    class Handler(BaseHTTPRequestHandler):
        def respond(self, expected_path, body):
            if self.path != expected_path or self.headers.get("Authorization") != "Bearer ci-mock-key":
                self.send_error(403)
                return
            raw = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.respond("/v1/models", {"data": [{"id": "ci-model"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("model") != "ci-model":
                self.send_error(400)
                return
            self.respond("/v1/chat/completions", {"choices": [{"message": {"content": "OK"}}]})

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1"
        finally:
            server.shutdown()
            thread.join()


with model_provider() as model_url, sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(base_url=sys.argv[1])
    page.goto(sys.argv[1], wait_until="domcontentloaded")
    dock = page.get_by_role("banner", name="启动台")
    initialize = dock.get_by_role("button", name="请先完成初始化")
    expect(initialize).to_be_visible(timeout=30000)
    initialize.click()
    panel = dock.get_by_role("dialog", name="请先完成初始化")
    expect(panel.get_by_role("button")).to_have_text(numbered(STEPS))
    print("Chromium shows all eight initialization actions in order.")
    # Save through the same APIs as the UI. The Dock must refresh from persisted backend state.
    desk(page, "PATCH", "prefs", {
        "name": "CI User", "email": "ci@example.invalid", "phone": "13500000000",
        "avatar": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGMsAAAAASUVORK5CYII=",
    })
    desk(page, "POST", "holdings", {
        "action": "add", "row": {"code": "600519.SH", "name": "贵州茅台", "quantity": 100, "cost": 1000},
    })
    desk(page, "POST", "watchlist", {"action": "add", "code": "600519.SH"})
    desk(page, "POST", "initial-briefing", {"action": "start"})
    state = desk(page, "GET", "initialization")
    assert state["briefingPending"] and not state["briefing"]
    desk(page, "POST", "initial-briefing", {"action": "confirm", "reply": ""}, status=400)
    state = desk(page, "GET", "initialization")
    assert state["briefingPending"] and not state["briefing"]
    desk(page, "POST", "initial-briefing", {"action": "confirm", "reply": "没有"})
    state = desk(page, "GET", "initialization")
    assert not state["briefingPending"] and state["briefing"]
    expect(panel.get_by_role("button")).to_have_text(numbered(STEPS[i] for i in (0, 1, 5, 6)), timeout=25000)
    print("Profile, holdings, watchlist, and confirmed briefing disappear from the Dock after saving.")
    panel.get_by_role("button", name=numbered(STEPS[:1])[0]).click()
    page.get_by_label("API 地址", exact=True).fill(model_url)
    page.get_by_label("协议", exact=True).select_option("openai-completions")
    page.get_by_label("API Key", exact=True).fill("ci-mock-key")
    page.get_by_role("button", name="验证并保存").click()
    expect(page.get_by_role("button", name="验证并保存")).to_have_count(0, timeout=40000)
    assert desk(page, "GET", "initialization")["model"]
    initialize.click()
    expect(panel.get_by_role("button")).to_have_text(numbered(STEPS[i] for i in (1, 5, 6)), timeout=25000)
    print("Model discovery, API probe, and activation complete through the installed UI.")
    browser.close()
