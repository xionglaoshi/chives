from __future__ import annotations

import json
import socket
import time

import pytest
import requests

from fmp_mcp.client import FmpClient
from fmp_mcp.config import Settings
from fmp_mcp.tools import dispatch
from fake_upstream import FakeFmp

KEY = "TESTKEY_123456"


def _code(payload: dict) -> str:
    return (payload.get("error") or {}).get("code", "")


@pytest.mark.parametrize(
    ("symbol", "code"),
    [
        ("BADKEY", "unauthorized"),
        ("ERR200", "unauthorized"),
        ("PREMIUM", "plan_restricted"),
        ("LIMIT", "rate_limited"),
        ("FAIL500", "upstream_error"),
        ("REDIRECT", "upstream_error"),
    ],
)
def test_upstream_errors_are_mapped_to_envelopes(client: FmpClient, symbol: str, code: str) -> None:
    payload = dispatch("fmp_get_quote", {"symbol": symbol}, client)
    assert payload["ok"] is False and payload["status"] == "error"
    assert _code(payload) == code
    assert payload["error"]["message"]
    assert payload["data"]["count"] == 0


def test_404_is_upstream_error(client: FmpClient) -> None:
    payload = client.get_rows("/stable/not-a-real-endpoint", {})
    assert payload.error is not None and payload.error.code == "upstream_error"


def test_timeout_is_upstream_unreachable_and_fast(settings: Settings) -> None:
    client = FmpClient(settings, timeout=0.2)
    started = time.monotonic()
    payload = dispatch("fmp_get_quote", {"symbol": "SLOW"}, client)
    elapsed = time.monotonic() - started
    assert _code(payload) == "upstream_unreachable"
    assert elapsed < 5


def test_connection_failure_is_upstream_unreachable() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    client = FmpClient(Settings(base_url=f"http://127.0.0.1:{port}", api_key=KEY, key_source="test"), timeout=0.5)
    payload = dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    assert _code(payload) == "upstream_unreachable"


def test_requests_exception_text_with_key_never_leaks(
    client: FmpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args, **kwargs):
        raise requests.ConnectionError(
            f"Max retries exceeded with url: /stable/quote?symbol=AAPL&apikey={KEY}"
        )

    monkeypatch.setattr(client.session, "get", explode)
    payload = dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    text = json.dumps(payload)
    assert _code(payload) == "upstream_unreachable"
    assert KEY not in text and "apikey=" not in text


def test_upstream_body_echoing_key_is_redacted(client: FmpClient) -> None:
    payload = dispatch("fmp_get_quote", {"symbol": "ECHO500"}, client)
    text = json.dumps(payload)
    assert _code(payload) == "upstream_error"
    assert KEY not in text
    assert "***" in payload["error"]["message"]


def test_upstream_401_body_echoing_key_is_not_echoed(client: FmpClient) -> None:
    payload = dispatch("fmp_get_quote", {"symbol": "BADKEY"}, client)
    text = json.dumps(payload)
    assert _code(payload) == "unauthorized"
    assert KEY not in text


def test_non_json_2xx_is_upstream_error(client: FmpClient) -> None:
    class Response:
        status_code = 200
        text = "not json"

        def json(self):
            raise ValueError("nope")

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    client.session = Session()
    result = client.get_rows("/stable/quote", {"symbol": "AAPL"})
    assert result.error is not None and result.error.code == "upstream_error"
