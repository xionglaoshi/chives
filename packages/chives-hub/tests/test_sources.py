from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from chives_hub.config import load_config
from chives_hub.sources import HttpClient, SourceError, Sources
from tests.support import NOW, write_config


class FakeClient:
    def __init__(self) -> None:
        self.json_payloads: dict[tuple[str, str], object] = {}
        self.text_payload = ""
        self.calls: list[tuple[str, str, dict]] = []
        self.health_payload: dict[str, dict] = {}

    def get_json(self, name, base, path, params=None, *, now=None, test_mode=False):
        self.calls.append((name, path, dict(params or {})))
        value = self.json_payloads.get((name, path))
        if isinstance(value, Exception):
            raise value
        return value

    def get_text(self, name, url, *, encoding="utf-8", now=None, test_mode=False):
        self.calls.append((name, url, {}))
        return self.text_payload

    def health(self, now):
        return dict(self.health_payload)


def make_sources(tmp_path: Path, client: FakeClient | None = None):
    client = client or FakeClient()
    config = load_config(
        write_config(tmp_path),
        env={
            "CHIVES_HUB_TEST_MODE": "1",
            "CHIVES_HUB_TENCENT_BASE": "http://127.0.0.1:19999",
        },
    )
    return Sources(config, client=client, env={"CHIVES_HUB_TEST_MODE": "1"}), client, config


def tencent_line(code: str = "601099.SH", name: str = "太平洋", price: float = 3.51, prev: float = 3.54) -> str:
    fields = [""] * 88
    fields[1] = name
    fields[3] = f"{price:.2f}"
    fields[4] = f"{prev:.2f}"
    fields[30] = "20261104100000"
    fields[32] = f"{(price / prev - 1) * 100:.2f}"
    fields[47] = f"{prev * 1.1:.2f}"
    fields[48] = f"{prev * 0.9:.2f}"
    prefix = "sh" if code.endswith(".SH") else "sz"
    digits = code.split(".")[0]
    return f'v_{prefix}{digits}="' + "~".join(fields) + '";\n'


def test_cn_alerts_parse(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("cn_watch", "/alerts")] = {"ok": True, "alerts": [{"id": 1}]}
    assert sources.cn_alerts(0) == [{"id": 1}]
    assert client.calls[0][2] == {"after_id": 0, "limit": 200}


def test_cn_alerts_missing_list(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("cn_watch", "/alerts")] = {"ok": True}
    with pytest.raises(SourceError):
        sources.cn_alerts(0)


def test_cn_state_parse(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("cn_watch", "/state")] = {"quotes": {"601099.SH": {"price": 3.5}}}
    assert sources.cn_state()["quotes"]["601099.SH"]["price"] == 3.5


def test_cn_state_not_object(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("cn_watch", "/state")] = []
    with pytest.raises(SourceError):
        sources.cn_state()


def test_market_alerts_parse(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/alerts")] = {"ok": True, "alerts": [{"id": 3}]}
    assert sources.market_alerts(0) == [{"id": 3}]
    assert client.calls[0][2] == {"since_id": 0, "limit": 100}


def test_market_alerts_missing_list(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/alerts")] = {"ok": True}
    with pytest.raises(SourceError):
        sources.market_alerts(0)


def test_tencent_quotes_parse(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.text_payload = tencent_line()
    quotes = sources.tencent_quotes(["601099.SH"])
    assert quotes["601099.SH"].name == "太平洋"
    assert quotes["601099.SH"].price == 3.51
    assert quotes["601099.SH"].prev_close == 3.54


def test_tencent_quotes_dedupe(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.text_payload = tencent_line()
    sources.tencent_quotes(["601099.SH", "601099.SH"])
    assert len([call for call in client.calls if call[0] == "tencent"]) == 1


def test_tencent_quotes_too_many(tmp_path: Path) -> None:
    sources, _, _ = make_sources(tmp_path)
    with pytest.raises(SourceError):
        sources.tencent_quotes([f"{index:06d}.SZ" for index in range(81)])


def test_tencent_quotes_empty(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    assert sources.tencent_quotes([]) == {}
    assert client.calls == []


def test_analyses_missing(tmp_path: Path) -> None:
    sources, _, _ = make_sources(tmp_path)
    assert sources.analyses() == {}


def test_analyses_parse(tmp_path: Path) -> None:
    sources, _, config = make_sources(tmp_path)
    config.analyses_dir.mkdir()
    analysis = config.analyses_dir / "analysis-1.md"
    analysis.write_text("**结论：偏多。**", encoding="utf-8")
    (config.analyses_dir / "analyses.jsonl").write_text(
        json.dumps({"alert_id": 1, "status": "done", "file": str(analysis)}) + "\n"
        + "not json\n",
        encoding="utf-8",
    )
    result = sources.analyses()
    assert result[1].status == "done"
    assert result[1].markdown == "**结论：偏多。**"


def test_analyses_path_traversal_blocked(tmp_path: Path) -> None:
    sources, _, config = make_sources(tmp_path)
    config.analyses_dir.mkdir()
    (config.analyses_dir / "analyses.jsonl").write_text(
        json.dumps({"alert_id": 1, "status": "done", "file": "../../etc/passwd"}) + "\n",
        encoding="utf-8",
    )
    assert sources.analyses()[1].markdown == ""


def test_analyses_size_cap(tmp_path: Path) -> None:
    sources, _, config = make_sources(tmp_path)
    config.analyses_dir.mkdir()
    analysis = config.analyses_dir / "analysis-1.md"
    analysis.write_text("x" * 250_000, encoding="utf-8")
    (config.analyses_dir / "analyses.jsonl").write_text(
        json.dumps({"alert_id": 1, "status": "done", "file": "analysis-1.md"}) + "\n",
        encoding="utf-8",
    )
    assert len(sources.analyses()[1].markdown) == 200_000


def test_analyses_default_filename(tmp_path: Path) -> None:
    sources, _, config = make_sources(tmp_path)
    config.analyses_dir.mkdir()
    (config.analyses_dir / "analysis-2.md").write_text("body", encoding="utf-8")
    (config.analyses_dir / "analyses.jsonl").write_text(
        json.dumps({"alert_id": 2, "status": "done"}) + "\n", encoding="utf-8"
    )
    assert sources.analyses()[2].markdown == "body"


def test_health_shape(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.health_payload = {"cn_watch": {"ok": True, "age_s": 1.0}}
    health = sources.health(NOW)
    assert health["cn_watch"]["ok"] is True
    assert health["analyses"]["ok"] is False


class _Server:
    def __init__(self, handler_factory) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def close(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=3)
        self.httpd.server_close()


def server_for(status: int, body: bytes, headers=None) -> _Server:
    headers = headers or {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return

        def do_GET(self):  # noqa: N802
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Server(Handler)


def test_http_json_success() -> None:
    server = server_for(200, b'{"ok": true}')
    try:
        client = HttpClient(timeout=2.0)
        payload = client.get_json("cn_watch", f"http://127.0.0.1:{server.port}", "/state", test_mode=True)
        assert payload == {"ok": True}
    finally:
        server.close()


def test_http_redirect_refused() -> None:
    server = server_for(302, b"", {"Location": "/elsewhere"})
    try:
        client = HttpClient(timeout=2.0)
        with pytest.raises(SourceError) as exc:
            client.get_json("cn_watch", f"http://127.0.0.1:{server.port}", "/state", test_mode=True)
        assert exc.value.code == "redirect_refused"
    finally:
        server.close()


def test_http_response_too_large() -> None:
    server = server_for(200, b"x" * 200)
    try:
        client = HttpClient(timeout=2.0, max_bytes=50)
        with pytest.raises(SourceError) as exc:
            client.get_json("cn_watch", f"http://127.0.0.1:{server.port}", "/state", test_mode=True)
        assert exc.value.code == "response_too_large"
    finally:
        server.close()


def test_http_host_not_allowed() -> None:
    client = HttpClient(timeout=1.0)
    with pytest.raises(SourceError) as exc:
        client.get_json("cn_watch", "http://example.com", "/state")
    assert exc.value.code == "host_not_allowed"


def test_http_network_error() -> None:
    client = HttpClient(timeout=0.5)
    with pytest.raises(SourceError) as exc:
        client.get_json("cn_watch", "http://127.0.0.1:1", "/state", test_mode=True)
    assert exc.value.code == "upstream_network"


def test_http_invalid_json() -> None:
    server = server_for(200, b"not json")
    try:
        client = HttpClient(timeout=2.0)
        with pytest.raises(SourceError) as exc:
            client.get_json("cn_watch", f"http://127.0.0.1:{server.port}", "/state", test_mode=True)
        assert exc.value.code == "invalid_json"
    finally:
        server.close()


def test_http_health_tracks_failure() -> None:
    client = HttpClient(timeout=0.2)
    with pytest.raises(SourceError):
        client.get_json("cn_watch", "http://127.0.0.1:1", "/state", now=NOW, test_mode=True)
    health = client.health(NOW)
    assert health["cn_watch"]["ok"] is False
    assert health["cn_watch"]["age_s"] is None


# -- market-watch v1.4 review endpoints --------------------------------
def test_market_sectors_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/sectors")] = {"ok": True, "rows": []}
    assert sources.market_sectors("sw1")["ok"] is True
    assert client.calls[-1] == ("market_watch", "/sectors", {"level": "sw1"})


def test_market_pool_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/pool")] = {"ok": True, "count": 1}
    sources.market_pool("zt", day="2026-11-04", limit=50)
    assert client.calls[-1] == (
        "market_watch",
        "/pool",
        {"kind": "zt", "date": "2026-11-04", "limit": 50},
    )


def test_market_pool_ladder_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/pool/ladder")] = {"ok": True}
    sources.market_pool_ladder(day=None)
    assert client.calls[-1] == ("market_watch", "/pool/ladder", {"date": None})


def test_market_pool_history_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/pool/history")] = {"ok": True}
    sources.market_pool_history(10)
    assert client.calls[-1] == ("market_watch", "/pool/history", {"days": 10})


def test_market_pool_by_industry_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/pool/by-industry")] = {"ok": True}
    sources.market_pool_by_industry(day="2026-11-04")
    assert client.calls[-1] == (
        "market_watch",
        "/pool/by-industry",
        {"date": "2026-11-04"},
    )


def test_market_pool_yesterday_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/pool/yesterday")] = {"ok": True}
    sources.market_pool_yesterday()
    assert client.calls[-1] == ("market_watch", "/pool/yesterday", {})


def test_market_themes_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/themes")] = {"ok": True}
    sources.market_themes(limit=10, sort="change")
    assert client.calls[-1] == (
        "market_watch",
        "/themes",
        {"kind": "concept", "limit": 10, "sort": "change"},
    )


def test_market_flows_params(tmp_path: Path) -> None:
    sources, client, _ = make_sources(tmp_path)
    client.json_payloads[("market_watch", "/flows")] = {"ok": True}
    sources.market_flows("sector_in", limit=5)
    assert client.calls[-1] == (
        "market_watch",
        "/flows",
        {"kind": "sector_in", "limit": 5},
    )
