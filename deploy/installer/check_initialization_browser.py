"""Check the installed Chives UI in Chromium from an isolated browser profile."""
import sys

from playwright.sync_api import expect, sync_playwright

STEPS = (
    "添加模型", "完成用户画像评测问卷", "填写用户基本信息", "添加持仓股票",
    "添加关注股票", "连接微信", "创建盯盘任务", "创建每日投研简报任务",
)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page()
    page.goto(sys.argv[1], wait_until="domcontentloaded")
    dock = page.get_by_role("banner", name="启动台")
    initialize = dock.get_by_role("button", name="请先完成初始化")
    expect(initialize).to_be_visible(timeout=30000)
    initialize.click()
    panel = dock.get_by_role("dialog", name="请先完成初始化")
    expect(panel.get_by_role("button")).to_have_text(list(STEPS))
    print("Chromium shows all eight initialization actions in order.")
    browser.close()
