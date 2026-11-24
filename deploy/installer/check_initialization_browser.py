"""Check the installed Chives UI in Chromium from an isolated browser profile."""
import sys

from playwright.sync_api import expect, sync_playwright

STEPS = (
    "添加模型", "完成用户画像评测问卷", "填写用户基本信息", "添加持仓股票",
    "添加关注股票", "连接微信", "创建盯盘任务", "创建每日投研简报任务",
)

def desk(page, method, section, data=None, status=200):
    response = page.request.fetch(
        f"/api/settings/desk/{section}", method=method, data=data,
        headers={"X-Chives-Kernel-Manager": "local"},
    )
    assert response.status == status, (section, response.status, response.text())
    return response.json()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(base_url=sys.argv[1])
    page.goto(sys.argv[1], wait_until="domcontentloaded")
    dock = page.get_by_role("banner", name="启动台")
    initialize = dock.get_by_role("button", name="请先完成初始化")
    expect(initialize).to_be_visible(timeout=30000)
    initialize.click()
    panel = dock.get_by_role("dialog", name="请先完成初始化")
    expect(panel.get_by_role("button")).to_have_text(list(STEPS))
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
    expect(panel.get_by_role("button")).to_have_text([STEPS[i] for i in (0, 1, 5, 6)], timeout=25000)
    print("Profile, holdings, watchlist, and confirmed briefing disappear from the Dock after saving.")
    browser.close()
