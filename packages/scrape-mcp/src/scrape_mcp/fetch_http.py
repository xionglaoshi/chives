"""The fast layer: plain HTTP with no JavaScript execution.

Design notes:

* every hop is validated by :mod:`scrape_mcp.ssrf` and the socket is opened to
  the validated IP literal, with the original hostname preserved in the Host
  header and in TLS SNI (``sni_hostname``) so certificate checks still run
  against the real hostname;
* redirects are followed manually (at most five), so each target is validated
  before it is requested;
* no cookies, no proxy environment, no credentials, no login;
* bodies are capped at 5 MB and non-text responses are rejected.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urljoin

import httpx

from scrape_mcp.config import Settings
from scrape_mcp.robots import DomainPacer
from scrape_mcp.ssrf import Target, UrlError, default_resolver, parse_target

MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

TEXT_CONTENT_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "application/xml",
        "application/json",
        "application/ld+json",
        "application/rss+xml",
        "application/atom+xml",
        "application/markdown",
    }
)

_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?([A-Za-z0-9._:-]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(
    rb"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9._:-]+)", re.IGNORECASE
)

_STRONG_CHALLENGE_MARKERS = (
    "attention required! | cloudflare",
    "cf-chl-",
    "cf_chl_opt",
    "challenge-platform",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
    "please verify you are a human",
    "please complete the security check",
    "unusual traffic from your computer network",
    "access to this page has been denied",
    "ddos-guard",
)

# "Just a moment..." is ordinary English, so it only counts on a short page and
# only near the top, where Cloudflare's interstitial puts it.
_WEAK_CHALLENGE_MARKERS = ("just a moment...",)
_CAPTCHA_RE = re.compile(r"(g-recaptcha|hcaptcha|recaptcha/api|cf-turnstile)", re.IGNORECASE)


class FetchError(RuntimeError):
    """A fetch failed; ``code`` is one of the MCP error codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FetchedResponse:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    redirects: int = 0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Raw:
    status: int
    content_type: str
    body: bytes
    location: str


def looks_like_challenge(text: str) -> bool:
    """Heuristic for bot-verification / challenge interstitials (never bypassed)."""

    lowered = text[:200_000].lower()
    if any(marker in lowered for marker in _STRONG_CHALLENGE_MARKERS):
        return True
    head = lowered[:2000]
    if len(lowered) < 20_000 and any(marker in head for marker in _WEAK_CHALLENGE_MARKERS):
        return True
    return bool(_CAPTCHA_RE.search(lowered)) and (
        "verify" in lowered or "not a robot" in lowered
    ) and len(lowered) < 20_000


def _is_text(content_type: str) -> bool:
    media_type = (content_type or "").split(";")[0].strip().lower()
    if media_type.startswith("text/"):
        return True
    return media_type in TEXT_CONTENT_TYPES


def _decode_body(body: bytes, content_type: str) -> str:
    charset_match = _CHARSET_RE.search(content_type or "")
    candidates: list[str] = []
    if charset_match:
        candidates.append(charset_match.group(1))
    candidates.append("utf-8")
    for charset in candidates:
        try:
            return body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    meta_match = _META_CHARSET_RE.search(body[:4096])
    if meta_match:
        try:
            return body.decode(meta_match.group(1).decode("ascii", "ignore"))
        except (LookupError, UnicodeDecodeError):
            pass
    return body.decode("utf-8", errors="replace")


def _pinned_url(target: Target, address: str) -> str:
    host = f"[{address}]" if ":" in address else address
    return f"{target.scheme}://{host}:{target.port}{target.request_path}"


class HttpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        resolver: Callable[[str, int], tuple[str, ...]] = default_resolver,
        pacer: DomainPacer | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._resolver = resolver
        self._pacer = pacer or DomainPacer(settings.min_interval_seconds)
        self._transport = transport
        self._clock = clock

    def get(
        self,
        url: str,
        *,
        timeout: float,
        guard: Callable[[Target], None] | None = None,
    ) -> FetchedResponse:
        current = url
        visited: list[str] = []
        redirects = 0
        while True:
            if current in visited:
                raise FetchError("fetch_failed", "redirect loop detected")
            visited.append(current)
            try:
                target = parse_target(
                    current,
                    resolver=self._resolver,
                    allow_hosts=self._settings.allow_hosts,
                    allow_loopback=self._settings.allow_loopback,
                )
            except UrlError as exc:
                raise FetchError(exc.code, exc.message) from exc
            if guard is not None:
                guard(target)
            self._pace(target)
            raw = self._request(target, timeout)
            if raw.status in REDIRECT_STATUSES:
                if not raw.location:
                    raise FetchError("fetch_failed", f"HTTP {raw.status} redirect without a Location header")
                if redirects >= MAX_REDIRECTS:
                    raise FetchError("fetch_failed", f"too many redirects (maximum {MAX_REDIRECTS})")
                redirects += 1
                current = urljoin(current, raw.location.strip())
                continue
            text = _decode_body(raw.body, raw.content_type)
            if looks_like_challenge(text):
                raise FetchError(
                    "blocked",
                    "the response looks like a bot-verification or challenge page; "
                    "this tool does not attempt to bypass it",
                )
            return FetchedResponse(
                url=url,
                final_url=target.url,
                status=raw.status,
                content_type=raw.content_type,
                text=text,
                redirects=redirects,
            )

    def _pace(self, target: Target) -> None:
        # Waiting for the per-domain interval is politeness, not part of the
        # request timeout; it is never skipped.
        self._pacer.wait(target.origin)

    def _request(self, target: Target, timeout: float) -> _Raw:
        last_error: Exception | None = None
        for address in target.ips[:3]:
            try:
                return self._request_once(target, address, timeout)
            except httpx.TimeoutException as exc:
                raise FetchError("timeout", f"request to {target.host} timed out") from exc
            except httpx.ConnectError as exc:
                last_error = exc
                continue
            except httpx.HTTPError as exc:
                raise FetchError(
                    "fetch_failed", f"request to {target.host} failed ({type(exc).__name__})"
                ) from exc
        raise FetchError("fetch_failed", f"could not connect to {target.host}") from last_error

    def _request_once(self, target: Target, address: str, timeout: float) -> _Raw:
        headers = {
            "Host": target.host_header,
            "User-Agent": self._settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            "Connection": "close",
        }
        extensions: dict[str, Any] = {}
        if target.scheme == "https":
            extensions["sni_hostname"] = target.host
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        client = httpx.Client(
            trust_env=False,
            follow_redirects=False,
            http2=False,
            timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
            limits=limits,
            transport=self._transport,
        )
        started = self._clock()
        try:
            with client.stream(
                "GET",
                _pinned_url(target, address),
                headers=headers,
                extensions=extensions or None,
            ) as response:
                status = response.status_code
                content_type = response.headers.get("content-type", "")
                location = response.headers.get("location", "")
                if status in REDIRECT_STATUSES:
                    return _Raw(status=status, content_type=content_type, body=b"", location=location)
                if status in (403, 429):
                    raise FetchError(
                        "blocked",
                        f"the site returned HTTP {status}; this tool does not try to bypass blocks",
                    )
                if not 200 <= status < 300:
                    raise FetchError("fetch_failed", f"the site returned HTTP {status}")
                if status in (204, 205):
                    return _Raw(status=status, content_type="text/plain", body=b"", location="")
                if "attachment" in response.headers.get("content-disposition", "").lower():
                    raise FetchError("blocked", "the response is a file download; downloads are not supported")
                if not _is_text(content_type):
                    raise FetchError(
                        "extract_failed",
                        f"unsupported content-type: {content_type or 'missing'}",
                    )
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
                    raise FetchError("too_large", f"response exceeds {MAX_BODY_BYTES} bytes")

                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise FetchError("too_large", f"response exceeds {MAX_BODY_BYTES} bytes")
                    if self._clock() - started > timeout:
                        raise FetchError("timeout", f"request to {target.host} timed out")
                return _Raw(
                    status=status,
                    content_type=content_type,
                    body=bytes(body),
                    location="",
                )
        finally:
            client.close()
