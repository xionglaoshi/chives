from __future__ import annotations


import pytest

from scrape_mcp.config import Settings
from scrape_mcp.service import ScrapeService

from scrape_mcp.fetch_browser import BrowserFetcher

pytestmark = pytest.mark.skipif(not BrowserFetcher(Settings()).available(), reason="Chives Chromium not installed")


def test_browser_renders_javascript(settings: Settings, site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_page(
        {"url": site.url("/js"), "mode": "browser", "extraction": "html"}
    )
    assert payload["status"] == "ready", payload
    assert '<div id="app">rendered-by-js</div>' in payload["data"]["content"]
    assert "before-js" not in payload["data"]["content"]
    assert payload["data"]["untrusted_text"] is True


def test_browser_marks_markdown(settings: Settings, site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_page(
        {"url": site.url("/js"), "mode": "browser", "extraction": "markdown"}
    )
    assert "rendered-by-js" in payload["data"]["content"]


def test_browser_blocks_private_subrequests(settings: Settings, site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_page({"url": site.url("/private-sub"), "mode": "browser"})
    assert payload["status"] == "ready", payload
    assert "subresource page" in payload["data"]["content"]
    assert any("subrequest" in warning for warning in payload["warnings"])


def test_browser_blocks_redirect_to_private(settings: Settings, site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_page(
        {
            "url": site.url("/redirect?to=http%3A%2F%2F10.255.255.1%2F"),
            "mode": "browser",
        }
    )
    assert payload["error"]["code"] == "ssrf_blocked", payload


def test_browser_timeout(settings: Settings, site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_page(
        {"url": site.url("/slow?delay=5"), "mode": "browser", "timeout": 1}
    )
    assert payload["error"]["code"] == "timeout"


def test_missing_chrome_is_browser_unavailable(settings: Settings, site, tmp_path, monkeypatch) -> None:
    from scrape_mcp import private_browser
    monkeypatch.setattr(private_browser, "RUNTIME", tmp_path / "missing")
    service = ScrapeService(settings)
    payload = service.scrape_page({"url": site.url("/article"), "mode": "browser"})
    assert payload["error"]["code"] == "browser_unavailable"
    fast = service.scrape_page({"url": site.url("/article")})
    assert fast["status"] == "ready"


def test_browser_respects_robots(settings: Settings, denied_site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_page({"url": denied_site.url("/article"), "mode": "browser"})
    assert payload["error"]["code"] == "robots_disallowed", payload
    assert "/article" not in denied_site.request_paths()


def test_browser_detects_challenge_page(settings: Settings, site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_page({"url": site.url("/challenge200"), "mode": "browser"})
    assert payload["error"]["code"] == "blocked", payload


def test_browser_batch_isolates_failures(settings: Settings, site) -> None:
    service = ScrapeService(settings)
    payload = service.scrape_pages(
        {
            "urls": [site.url("/js"), "http://10.0.0.1/", site.url("/js")],
            "mode": "browser",
        }
    )
    assert payload["status"] == "ready", payload
    assert payload["data"]["succeeded"] == 2
    assert payload["data"]["failed_count"] == 1
    assert payload["data"]["results"][1]["error"]["code"] == "ssrf_blocked"
