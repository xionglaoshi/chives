"""T157: market-watch must only talk to the loopback data gateway."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from chives_compass.gateway import GatewayClient, SourceError
from tests.test_engine import OPEN, make_engine

SRC = Path(__file__).resolve().parents[1] / "src" / "chives_compass"
URL_RE = re.compile(r"https?://[^\s\"')]+")
ALLOWED_HOST = "127.0.0.1:8868"


def _source_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def test_sources_have_no_external_host():
    text = _source_text()
    for url in URL_RE.findall(text):
        host = url.split("://", 1)[1].split("/", 1)[0]
        assert host in {ALLOWED_HOST, "127.0.0.1"}, url


def test_sources_have_no_vendor_tokens():
    text = _source_text().lower()
    assert "push" + "2" not in text
    assert "eastmoney" not in text


def test_gateway_url_must_be_loopback():
    with pytest.raises(SourceError):
        GatewayClient("http://10.0.0.1:8868")
    with pytest.raises(SourceError):
        GatewayClient("ftp://127.0.0.1:8868")


class _Handler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def log_message(self, *args):  # noqa: D401 - silence test server
        return

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.calls.append(body)
        payload = {"status": "ok", "as_of": "2026-11-03T10:30:00+08:00", "data": {"echo": body["tool"]}}
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_gateway_client_posts_tool_and_args():
    _Handler.calls = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        client = GatewayClient(f"http://127.0.0.1:{httpd.server_address[1]}")
        assert client.data("market_quote", {"codes": ["600519"]}) == {"echo": "market_quote"}
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    assert _Handler.calls == [{"tool": "market_quote", "args": {"codes": ["600519"]}}]


class _Unavailable(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_POST(self):  # noqa: N802
        raw = json.dumps({"status": "unavailable", "message": "暂时取不到"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_gateway_client_unavailable_raises_source_error():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Unavailable)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        client = GatewayClient(f"http://127.0.0.1:{httpd.server_address[1]}")
        with pytest.raises(SourceError):
            client.call("market_overview")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_engine_blocks_come_from_gateway(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    health = engine.health_dict()
    for name in ("index", "breadth", "limit_pool", "industry", "movers", "flows", "daily_spark"):
        primary = health["sources"][name]["primary"]
        assert primary.startswith("gateway."), (name, primary)
