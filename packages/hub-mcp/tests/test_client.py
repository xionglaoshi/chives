from __future__ import annotations

import pytest

from hub_mcp.client import HubClient
from hub_mcp.errors import HubError
from tests.conftest import FakeHub


def test_get_passes_query(client: HubClient, fake_hub: FakeHub) -> None:
    payload = client.get_json("/signals", [("status", "all"), ("decide", "1"), ("limit", 5)])
    assert payload["ok"] is True
    assert ("GET", "/signals?status=all&decide=1&limit=5", None) == fake_hub.log[-1]


def test_post_sends_json_body(client: HubClient, fake_hub: FakeHub) -> None:
    payload = client.post_json("/plans", {"code": "600000.SH", "proposed_by": "agent"})
    assert payload["ok"] is True
    method, path, body = fake_hub.log[-1]
    assert (method, path) == ("POST", "/plans")
    assert body == {"code": "600000.SH", "proposed_by": "agent"}


def test_http_404_json_is_returned(client: HubClient) -> None:
    payload = client.get_json("/signals/404")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "signal_not_found"


def test_business_error_is_returned(client: HubClient) -> None:
    payload = client.get_json("/business_error")
    assert payload["ok"] is False
    assert payload["error"] == {"code": "boom", "message": "upstream failed"}


def test_unreachable_raises_hub_unreachable() -> None:
    with pytest.raises(HubError) as exc:
        HubClient("http://127.0.0.1:9", timeout=0.2).get_json("/signals")
    assert exc.value.code == "hub_unreachable"


def test_response_cap(fake_hub: FakeHub) -> None:
    with pytest.raises(HubError) as exc:
        HubClient(fake_hub.url, timeout=2.0).get_json("/large")
    assert exc.value.code == "response_too_large"


def test_invalid_json(fake_hub: FakeHub) -> None:
    with pytest.raises(HubError) as exc:
        HubClient(fake_hub.url).get_json("/badjson")
    assert exc.value.code == "invalid_response"


def test_non_object_json(fake_hub: FakeHub) -> None:
    with pytest.raises(HubError) as exc:
        HubClient(fake_hub.url).get_json("/array")
    assert exc.value.code == "invalid_response"


def test_timeout(fake_hub: FakeHub) -> None:
    with pytest.raises(HubError) as exc:
        HubClient(fake_hub.url, timeout=0.05).get_json("/slow")
    assert exc.value.code == "hub_unreachable"


def test_client_rejects_non_loopback() -> None:
    with pytest.raises(ValueError):
        HubClient("http://example.com:8867")
