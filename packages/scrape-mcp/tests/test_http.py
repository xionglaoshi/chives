from __future__ import annotations

import shutil
import ssl
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from scrape_mcp.config import Settings
from scrape_mcp.fetch_http import FetchError, HttpClient
from scrape_mcp.service import ScrapeService


def test_fast_fetch_envelope(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/article")})
    assert payload["ok"] is True
    assert payload["source"] == "scrape"
    assert payload["status"] == "ready"
    assert payload["warnings"] == []
    data = payload["data"]
    assert data["url"] == site.url("/article")
    assert data["final_url"] == site.url("/article")
    assert data["http_status"] == 200
    assert data["title"] == "Test Article & Friends"
    assert "Body paragraph" in data["content"]
    assert data["truncated"] is False
    assert data["content_chars"] == len(data["content"])
    assert data["untrusted_text"] is True
    datetime.fromisoformat(data["fetched_at"])


def test_text_and_html_extractions(service: ScrapeService, site) -> None:
    text = service.scrape_page({"url": site.url("/article"), "extraction": "text"})
    assert "Body paragraph" in text["data"]["content"]
    raw = service.scrape_page({"url": site.url("/article"), "extraction": "html"})
    assert "<h1>Body heading</h1>" in raw["data"]["content"]
    plain = service.scrape_page({"url": site.url("/plain")})
    assert plain["data"]["content"] == "plain body text"
    assert plain["data"]["truncated"] is False


def test_empty_content_is_empty_status(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/empty")})
    assert payload["status"] == "empty"
    assert payload["ok"] is True
    assert payload["data"]["content"] == ""
    assert payload["data"]["content_chars"] == 0


def test_redirect_chain_updates_final_url(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/redirect-chain")})
    assert payload["status"] == "ready"
    assert payload["data"]["url"] == site.url("/redirect-chain")
    assert payload["data"]["final_url"] == site.url("/article")
    assert payload["data"]["http_status"] == 200


def test_redirect_to_private_network_is_blocked(service: ScrapeService, site) -> None:
    payload = service.scrape_page(
        {"url": site.url("/redirect?to=http%3A%2F%2F10.255.255.1%2F")}
    )
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["data"] == {}
    assert payload["error"]["code"] == "ssrf_blocked"


def test_redirect_loop_is_rejected(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/redirect-loop")})
    assert payload["error"]["code"] == "fetch_failed"
    assert "redirect loop" in payload["error"]["message"]


def test_403_is_blocked_and_not_retried(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/challenge")})
    assert payload["error"]["code"] == "blocked"
    paths = site.request_paths()
    assert paths.count("/challenge") == 1


def test_challenge_page_with_200_is_blocked(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/challenge200")})
    assert payload["error"]["code"] == "blocked"
    assert "challenge" in payload["error"]["message"]


def test_oversized_response_is_too_large(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/big")})
    assert payload["error"]["code"] == "too_large"


def test_slow_response_times_out(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/slow?delay=3"), "timeout": 1})
    assert payload["error"]["code"] == "timeout"


def test_non_text_content_type_is_rejected(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/binary")})
    assert payload["error"]["code"] == "extract_failed"


def test_attachment_is_not_downloaded(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/download")})
    assert payload["error"]["code"] == "blocked"


def test_robots_disallowed(service: ScrapeService, denied_site) -> None:
    payload = service.scrape_page({"url": denied_site.url("/article")})
    assert payload["error"]["code"] == "robots_disallowed"
    assert "/article" not in denied_site.request_paths()


def test_long_page_is_truncated(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/truncate")})
    data = payload["data"]
    assert data["truncated"] is True
    assert data["content_chars"] == 100_000
    assert len(data["content"]) == 100_000
    assert any("truncated" in warning for warning in payload["warnings"])


def test_prompt_injection_is_returned_as_untrusted_text(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/injection")})
    data = payload["data"]
    assert "Ignore all previous instructions" in data["content"]
    assert data["untrusted_text"] is True
    assert payload["ok"] is True


def test_user_agent_and_no_cookies(service: ScrapeService, site, settings: Settings) -> None:
    service.scrape_page({"url": site.url("/article")})
    article_requests = [
        request for request in site.requests if request["path"] == "/article"
    ]
    assert article_requests
    headers = article_requests[-1]["headers"]
    assert headers["user-agent"] == settings.user_agent == "dsh-finance-scrape/0.1.0"
    assert "cookie" not in headers
    assert headers["host"] == f"127.0.0.1:{site.port}"


def test_sensitive_query_parameters_are_redacted(service: ScrapeService, site) -> None:
    payload = service.scrape_page(
        {"url": site.url("/article?token=SUPERSECRET&key=abc&q=1")}
    )
    assert "SUPERSECRET" not in payload["data"]["url"]
    assert "token=***" in payload["data"]["url"]
    assert "SUPERSECRET" not in payload["data"]["final_url"]
    assert "SUPERSECRET" not in str(payload)


def test_redaction_in_error_messages(service: ScrapeService, denied_site) -> None:
    payload = service.scrape_page({"url": denied_site.url("/private?password=HUNTER2")})
    assert payload["error"]["code"] == "robots_disallowed"
    assert "HUNTER2" not in payload["error"]["message"]


def test_batch_partial_failure(service: ScrapeService, site) -> None:
    payload = service.scrape_pages(
        {"urls": [site.url("/article"), "http://10.0.0.1/", site.url("/plain")]}
    )
    assert payload["status"] == "ready"
    assert payload["ok"] is True
    data = payload["data"]
    assert data["count"] == 3
    assert data["succeeded"] == 2
    assert data["failed_count"] == 1
    assert len(data["failed"]) == 1
    assert data["results"][0]["ok"] is True
    assert "Body paragraph" in data["results"][0]["content"]
    assert data["results"][1]["ok"] is False
    assert data["results"][1]["error"]["code"] == "ssrf_blocked"
    assert data["results"][2]["ok"] is True


def test_batch_all_failed_keeps_per_url_results(service: ScrapeService) -> None:
    payload = service.scrape_pages({"urls": ["http://10.0.0.1/", "http://192.168.1.1/"]})
    assert payload["status"] == "error"
    assert payload["ok"] is False
    assert payload["data"]["succeeded"] == 0
    assert len(payload["data"]["results"]) == 2
    assert payload["data"]["results"][0]["error"]["code"] == "ssrf_blocked"
    assert payload["error"]["code"] == "ssrf_blocked"


def test_batch_concurrency_is_capped(service: ScrapeService, site) -> None:
    service.scrape_page({"url": site.url("/article")})
    with site.lock:
        site.max_active = 0
    payload = service.scrape_pages(
        {"urls": [site.url(f"/slow?delay=0.3&i={index}") for index in range(8)]}
    )
    assert payload["data"]["succeeded"] == 8
    assert site.max_active <= 4


def test_rate_limit(settings: Settings, site) -> None:
    service = ScrapeService(
        Settings(
            allow_loopback=True,
            min_interval_seconds=0.0,
            requests_per_minute=2,
        )
    )
    assert service.scrape_page({"url": site.url("/article")})["status"] == "ready"
    assert service.scrape_page({"url": site.url("/article")})["status"] == "ready"
    payload = service.scrape_page({"url": site.url("/article")})
    assert payload["error"]["code"] == "rate_limited"


def test_stealth_mode_returns_invalid_argument(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": site.url("/article"), "mode": "stealth"})
    assert payload["error"]["code"] == "invalid_argument"
    payload = service.scrape_page({"url": site.url("/article"), "mode": "solve_cloudflare"})
    assert payload["error"]["code"] == "invalid_argument"


def test_invalid_url_is_reported_without_fetching(service: ScrapeService, site) -> None:
    payload = service.scrape_page({"url": "ftp://example.com/file"})
    assert payload["error"]["code"] == "invalid_url"
    assert site.request_paths() == []


def test_connection_is_pinned_to_the_resolved_ip() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host_header"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        seen["cookie"] = request.headers.get("cookie")
        return httpx.Response(
            200,
            text="<html><body><p>pinned</p></body></html>",
            headers={"content-type": "text/html"},
        )

    client = HttpClient(
        Settings(allow_loopback=False, min_interval_seconds=0.0),
        resolver=lambda host, port: ("93.184.216.34",),
        transport=httpx.MockTransport(handler),
    )
    response = client.get("https://example.com/page", timeout=5)
    assert response.status == 200
    assert seen["url"] == "https://93.184.216.34/page"
    assert seen["host_header"] == "example.com"
    assert seen["sni"] == "example.com"
    assert seen["cookie"] is None


def test_cross_host_redirect_is_revalidated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            return httpx.Response(
                302, headers={"location": "https://evil.example/", "content-type": "text/plain"}
            )
        return httpx.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})

    client = HttpClient(
        Settings(allow_loopback=False, min_interval_seconds=0.0),
        resolver=lambda host, port: (
            ("93.184.216.34",) if host == "example.com" else ("10.0.0.7",)
        ),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError) as excinfo:
        client.get("https://example.com/", timeout=5)
    assert excinfo.value.code == "ssrf_blocked"


def test_too_many_redirects() -> None:
    counter = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["value"] += 1
        return httpx.Response(
            302,
            headers={"location": f"/hop{counter['value']}", "content-type": "text/plain"},
        )

    client = HttpClient(
        Settings(allow_loopback=False, min_interval_seconds=0.0),
        resolver=lambda host, port: ("93.184.216.34",),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError) as excinfo:
        client.get("https://example.com/start", timeout=5)
    assert excinfo.value.code == "fetch_failed"
    assert counter["value"] == 6


def test_allow_hosts_is_enforced_at_fetch_time() -> None:
    client = HttpClient(
        Settings(allow_loopback=False, min_interval_seconds=0.0, allow_hosts=("example.com",)),
        resolver=lambda host, port: ("93.184.216.34",),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})
        ),
    )
    with pytest.raises(FetchError) as excinfo:
        client.get("https://other.example/", timeout=5)
    assert excinfo.value.code == "ssrf_blocked"


class _TLSHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        body = b"<html><body><p>tls ok</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def test_https_uses_sni_and_verifies_the_hostname(tmp_path) -> None:
    if not shutil.which("openssl"):
        pytest.skip("openssl is not available")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    made = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=scrape-test.example",
            "-addext",
            "subjectAltName=DNS:scrape-test.example",
        ],
        capture_output=True,
        text=True,
    )
    if made.returncode != 0:
        pytest.skip("openssl could not create a test certificate")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _TLSHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    transport = httpx.HTTPTransport(verify=ssl.create_default_context(cafile=str(cert)))
    client = HttpClient(
        Settings(allow_loopback=True, min_interval_seconds=0.0),
        resolver=lambda host, port: ("127.0.0.1",),
        transport=transport,
    )
    try:
        response = client.get(f"https://scrape-test.example:{port}/", timeout=5)
        assert response.status == 200
        assert "tls ok" in response.text
        with pytest.raises(FetchError):
            # The certificate is not valid for this name: hostname verification
            # must be done against the URL host, not the pinned IP.
            client.get(f"https://wrong.example:{port}/", timeout=5)
    finally:
        transport.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_loopback_is_blocked_without_the_test_switch(site) -> None:
    service = ScrapeService(Settings(min_interval_seconds=0.0))
    payload = service.scrape_page({"url": site.url("/article")})
    assert payload["error"]["code"] == "ssrf_blocked"
    assert site.request_paths() == []


def test_batch_reports_invalid_url_per_item(service: ScrapeService, site) -> None:
    payload = service.scrape_pages({"urls": [site.url("/article"), "ftp://example.com/x"]})
    assert payload["status"] == "ready"
    assert payload["data"]["results"][1]["error"]["code"] == "invalid_url"
    assert payload["data"]["failed_count"] == 1
