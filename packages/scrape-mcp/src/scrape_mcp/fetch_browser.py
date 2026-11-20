"""Browser rendering with a fresh Playwright Chromium context per call.

Every request made by the page goes through a CDP interceptor that reuses the
same SSRF validator; main-frame navigations additionally go through the
robots guard.  Downloads are disabled, non-http(s) schemes are aborted, and
WebSockets are closed.  Page content is still untrusted text: an instruction
rendered by a page is data, never a command.
"""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urlsplit

from scrape_mcp.browser_network import browser_network
from scrape_mcp.config import Settings
from scrape_mcp.private_browser import browser_api, chromium_binary
from scrape_mcp.fetch_http import (
    MAX_BODY_BYTES,
    FetchError,
    FetchedResponse,
    looks_like_challenge,
)
from scrape_mcp.robots import DomainPacer
from scrape_mcp.ssrf import Target, UrlError, default_resolver, parse_target


class BrowserFetcher:
    def __init__(
        self,
        settings: Settings,
        *,
        resolver: Callable[[str, int], tuple[str, ...]] = default_resolver,
        pacer: DomainPacer | None = None,
    ) -> None:
        self._settings = settings
        self._resolver = resolver
        self._pacer = pacer or DomainPacer(settings.min_interval_seconds)

    def available(self) -> bool:
        try:
            with browser_api().sync_playwright() as driver:
                chromium_binary(driver.chromium)
            return True
        except (ImportError, OSError, RuntimeError):
            return False

    def get(
        self,
        url: str,
        *,
        timeout: float,
        guard: Callable[[Target], None] | None = None,
        interact: Callable[[Any], None] | None = None,
    ) -> FetchedResponse:
        try:
            api = browser_api()
        except (ImportError, OSError, RuntimeError) as exc:
            raise FetchError("browser_unavailable", "Chives browser runtime unavailable; run scripts/install-browser.sh") from exc
        PlaywrightError = api.Error
        PlaywrightTimeoutError = api.TimeoutError

        target = parse_target(
            url,
            resolver=self._resolver,
            allow_hosts=self._settings.allow_hosts,
            allow_loopback=self._settings.allow_loopback,
        )
        if guard is not None:
            guard(target)
        self._pace(target)

        resolve_cache: dict[tuple[str, int], tuple[str, ...]] = {}

        def cached_resolver(host: str, port: int) -> tuple[str, ...]:
            key = (host, port)
            if key not in resolve_cache:
                resolve_cache[key] = self._resolver(host, port)
            return resolve_cache[key]

        warnings: list[str] = []
        main_blocked: list[BaseException] = []

        with browser_network(self._settings, cached_resolver) as proxy, api.sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=chromium_binary(playwright.chromium),
                    chromium_sandbox=True,
                    args=[
                        f"--proxy-server={proxy}",
                        "--proxy-bypass-list=<-loopback>",
                        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                        "--disable-quic",
                        "--disable-background-networking",
                        "--disable-component-update",
                        "--disable-extensions",
                        "--disable-sync",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--metrics-recording-only",
                        "--disable-features=Translate,MediaRouter",
                    ],
                )
            except Exception as exc:
                raise FetchError(
                    "browser_unavailable",
                    f"could not start Chromium ({type(exc).__name__}); run scripts/install-browser.sh",
                ) from exc
            try:
                context = browser.new_context(
                    user_agent=self._settings.user_agent,
                    accept_downloads=False,
                    service_workers="block",
                    locale="en-US",
                )
                page = context.new_page()
                if interact is not None:
                    # All interactions and the CDP navigation guard belong to this tab.
                    def restrict_tabs(route: Any) -> None:
                        try:
                            foreign = route.request.is_navigation_request() and route.request.frame.page != page
                        except PlaywrightError:
                            foreign = True
                        if foreign:
                            route.abort()
                        else:
                            route.continue_()
                    context.route("**/*", restrict_tabs)
                    context.on("page", lambda popup: popup.close() if popup != page else None)
                subrequests: list[str] = []

                # Playwright's route handler never sees redirect hops (Chrome
                # follows them below the page layer), so interception uses the
                # CDP Fetch domain, which pauses every request including
                # redirect targets before it is sent.
                cdp = context.new_cdp_session(page)
                frame_tree = cdp.send("Page.getFrameTree")
                main_frame_id = frame_tree["frameTree"]["frame"]["id"]
                cdp.send(
                    "Fetch.enable",
                    {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
                )

                def handle_paused(event: dict[str, Any]) -> None:
                    try:
                        self._intercept(
                            event,
                            cdp,
                            main_frame_id,
                            guard,
                            cached_resolver,
                            subrequests,
                            main_blocked,
                        )
                    except Exception:
                        # Abort if the request guard cannot reach a decision.
                        try:
                            cdp.send(
                                "Fetch.failRequest",
                                {"requestId": event.get("requestId", ""), "errorReason":"BlockedByClient"},
                            )
                        except Exception:
                            pass

                cdp.on("Fetch.requestPaused", handle_paused)
                try:
                    context.route_web_socket("**/*", lambda ws: ws.close())
                except Exception:
                    pass

                response = None
                started = time.monotonic()
                try:
                    response = page.goto(
                        url, wait_until="domcontentloaded", timeout=int(timeout * 1000)
                    )
                except PlaywrightTimeoutError as exc:
                    if main_blocked:
                        raise main_blocked[0] from exc
                    raise FetchError("timeout", f"page {target.host} did not load in time") from exc
                except PlaywrightError as exc:
                    if main_blocked:
                        raise main_blocked[0] from exc
                    message = str(exc)
                    if "ERR_BLOCKED_BY_CLIENT" in message or "Download is starting" in message:
                        raise FetchError(
                            "blocked", "the browser refused this navigation or download"
                        ) from exc
                    if "ERR_NAME_NOT_RESOLVED" in message:
                        raise FetchError("fetch_failed", f"DNS resolution failed for {target.host}") from exc
                    raise FetchError(
                        "fetch_failed", f"browser navigation failed ({type(exc).__name__})"
                    ) from exc

                if main_blocked:
                    raise main_blocked[0]

                remaining = timeout - (time.monotonic() - started)
                try:
                    page.wait_for_load_state("networkidle", timeout=max(200, int(remaining * 1000)))
                except PlaywrightTimeoutError:
                    warnings.append("networkidle wait timed out; used the DOM as loaded")

                status = response.status if response is not None else 0
                content_type = response.headers.get("content-type", "") if response is not None else ""
                final_url = page.url or url
                if final_url.startswith("chrome-error:") or final_url == "about:blank":
                    raise FetchError("fetch_failed", "browser navigation failed")
                self._validate_final(final_url, target, guard, cached_resolver)

                if status in (403, 429):
                    raise FetchError(
                        "blocked",
                        f"the site returned HTTP {status}; this tool does not try to bypass blocks",
                    )
                if status and not 200 <= status < 300:
                    raise FetchError("fetch_failed", f"the site returned HTTP {status}")
                if status == 0:
                    raise FetchError("fetch_failed", "the browser did not receive a response")

                document = page.content()
                if len(document.encode("utf-8", "replace")) > MAX_BODY_BYTES:
                    raise FetchError("too_large", f"response exceeds {MAX_BODY_BYTES} bytes")
                if not content_type:
                    content_type = "text/html"
                media_type = content_type.split(";")[0].strip().lower()
                if not (media_type.startswith("text/") or media_type == "application/xhtml+xml"):
                    raise FetchError("extract_failed", f"unsupported content-type: {content_type}")
                if looks_like_challenge(document):
                    raise FetchError(
                        "blocked",
                        "the response looks like a bot-verification or challenge page; "
                        "this tool does not attempt to bypass it",
                    )
                if interact is not None:
                    interact(page)
                    if main_blocked:
                        raise main_blocked[0]
                    final_url = page.url
                    self._validate_final(final_url, target, guard, cached_resolver)
                if subrequests:
                    warnings.append(
                        f"blocked {len(subrequests)} subrequest(s) to disallowed addresses or schemes"
                    )
                return FetchedResponse(
                    url=url,
                    final_url=final_url,
                    status=status,
                    content_type=content_type,
                    text=document,
                    warnings=tuple(warnings),
                )
            finally:
                browser.close()

    def _pace(self, target: Target) -> None:
        # Waiting for the per-domain interval is politeness, not part of the
        # request timeout; it is never skipped.
        self._pacer.wait(target.origin)

    def _validate_final(
        self,
        final_url: str,
        original: Target,
        guard: Callable[[Target], None] | None,
        cached_resolver: Callable[[str, int], tuple[str, ...]],
    ) -> None:
        final = parse_target(
            final_url,
            resolver=cached_resolver,
            allow_hosts=self._settings.allow_hosts,
            allow_loopback=self._settings.allow_loopback,
        )
        if guard is not None and final.origin != original.origin:
            guard(final)

    def _intercept(
        self,
        event: dict[str, Any],
        cdp: Any,
        main_frame_id: str,
        guard: Callable[[Target], None] | None,
        resolver: Callable[[str, int], tuple[str, ...]],
        subrequests: list[str],
        main_blocked: list[BaseException],
    ) -> None:
        request_id = event.get("requestId", "")
        url = str(event.get("request", {}).get("url", ""))
        is_main = (
            event.get("resourceType") == "Document" and event.get("frameId") == main_frame_id
        )

        def reject(cause: BaseException) -> None:
            if is_main:
                main_blocked.append(cause)
            else:
                subrequests.append(url)
            cdp.send(
                "Fetch.failRequest",
                {"requestId": request_id, "errorReason": "BlockedByClient"},
            )

        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            if parts.scheme == "about" and url == "about:blank":
                cdp.send("Fetch.continueRequest", {"requestId": request_id})
                return
            reject(
                FetchError(
                    "ssrf_blocked", f"blocked a non-http(s) request ({parts.scheme or 'unknown'})"
                )
            )
            return
        try:
            target = parse_target(
                url,
                resolver=resolver,
                allow_hosts=self._settings.allow_hosts,
                allow_loopback=self._settings.allow_loopback,
            )
        except UrlError as exc:
            reject(exc)
            return
        if guard is not None and is_main:
            try:
                guard(target)
            except BaseException as exc:
                reject(exc)
                return
        cdp.send("Fetch.continueRequest", {"requestId": request_id})
