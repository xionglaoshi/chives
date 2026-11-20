"""Bounded interactions with a research page in one Chromium tab."""
from __future__ import annotations

from pathlib import Path
from time import monotonic
from uuid import uuid4

from typing import TYPE_CHECKING

from scrape_mcp.private_browser import browser_api

if TYPE_CHECKING:
    from playwright.sync_api import Page
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from scrape_mcp.config import load_settings
from scrape_mcp.fetch_http import FetchError, looks_like_challenge
from scrape_mcp.service import ScrapeService


class BrowserStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["click", "fill", "select", "press", "wait", "read"]
    selector: str = Field(min_length=1, max_length=512, description="CSS or Playwright locator, e.g. text=年度报告")
    value: str = Field(default="", max_length=1500, description="Text for fill, option value for select, key name for press")


def research_page(url: str, steps: list[BrowserStep], screenshot_dir: Path | None) -> dict:
    if len(steps) > 12:
        raise ValueError("每次最多 12 步")
    PlaywrightError = browser_api().Error
    outcome = {}
    image = None

    def interact(page: Page) -> None:
        nonlocal image
        readings = []
        deadline = monotonic() + 30
        for index, step in enumerate(steps, 1):
            remaining = min(5000, int((deadline - monotonic()) * 1000))
            if remaining <= 0:
                raise ValueError("浏览器操作超过 30 秒")
            element = page.locator(step.selector)
            try:
                match step.action:
                    case "click":
                        element.click(timeout=remaining)
                    case "fill":
                        element.fill(step.value, timeout=remaining)
                    case "select":
                        element.select_option(value=step.value, timeout=remaining)
                    case "press":
                        element.press(step.value, timeout=remaining)
                    case "wait":
                        element.wait_for(state="visible", timeout=remaining)
                    case "read":
                        readings.append({"step": index, "text": element.inner_text(timeout=remaining)[:5000]})
                if looks_like_challenge(page.locator("body").inner_text(timeout=remaining)[:10000]):
                    raise FetchError("blocked", "网页要求人工验证")
            except PlaywrightError as exc:
                raise ValueError(f"第 {index} 步 {step.action} 失败，请检查页面和定位符") from exc
        body = page.locator("body")
        controls = page.locator('a[href],button,input:not([type="hidden"]),textarea,select,[role="button"]').evaluate_all(
            """nodes => nodes.filter(n => n.getClientRects().length).slice(0,80).map(n => ({
                tag: n.tagName.toLowerCase(), id: n.id, name: n.getAttribute('name') || '',
                label: (n.getAttribute('aria-label') || n.labels?.[0]?.innerText || n.innerText || n.placeholder || '').trim().slice(0,120)
            }))"""
        )
        outcome.update(title=page.title(), text=body.inner_text(timeout=4000)[:12000], controls=controls, readings=readings)
        if screenshot_dir is not None:
            image = page.screenshot(type="png", timeout=5000)

    service = ScrapeService(load_settings())
    response, warnings = service.interact(url, interact)
    result = {**outcome, "url": response.final_url, "untrusted_text": True, "warnings": warnings}
    if screenshot_dir is not None and image is not None:
        if screenshot_dir.resolve() != screenshot_dir:
            raise ValueError("截图目录不可用")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        name = f"browser-{uuid4().hex}.png"
        with (screenshot_dir / name).open("xb") as file:
            file.write(image)
        result["screenshot"] = "reports/" + name
    return result
