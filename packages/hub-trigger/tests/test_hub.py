"""HTTP client contract with a local fake hub."""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from hub_trigger.config import ConfigError
from hub_trigger.hub import HubClient, HubError

from support import context, trigger


def test_non_loopback_client_is_rejected() -> None:
    with pytest.raises(ConfigError):
        HubClient("http://192.168.1.10:8867")


def test_triggers_since_returns_sorted_rows(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(2), trigger(1), trigger(3)])
    rows = HubClient(hub.url).triggers_since(1)
    assert [row["id"] for row in rows] == [2, 3]


def test_triggers_since_filters_server_rows(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(5)])
    assert HubClient(hub.url).triggers_since(5) == []


def test_trigger_request_parameters(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(1)])
    HubClient(hub.url).triggers_since(0, limit=7)
    assert any("since_id=0" in path and "limit=7" in path for method, path in hub.requests)


def test_latest_trigger_id_paginates(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(index) for index in range(1, 61)])
    assert HubClient(hub.url).latest_trigger_id() == 60


def test_latest_trigger_id_empty(hub_factory: Callable[..., Any]) -> None:
    assert HubClient(hub_factory([]).url).latest_trigger_id() == 0


def test_http_error_becomes_hub_error(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(1)])
    hub.fail_trigger_page = True
    with pytest.raises(HubError):
        HubClient(hub.url).triggers_since(0)


def test_missing_triggers_list_is_hub_error(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([])
    client = HubClient(hub.url)
    original = client._request_json

    def fake(path: str, **kwargs: Any) -> Any:
        return {"ok": True}

    client._request_json = fake  # type: ignore[method-assign]
    with pytest.raises(HubError):
        client.triggers_since(0)
    assert original is not None


@pytest.mark.parametrize(
    "row",
    [
        {"id": -1, "kind": "card_execute"},
        {"id": True, "kind": "card_execute"},
        {"id": 1.5, "kind": "card_execute"},
        {"id": 1, "kind": ""},
        {"id": 1},
        {"id": 1, "kind": 3},
    ],
)
def test_invalid_trigger_rows_are_rejected(
    hub_factory: Callable[..., Any], row: dict[str, Any]
) -> None:
    hub = hub_factory([row])
    with pytest.raises(HubError):
        HubClient(hub.url).triggers_since(-2)


def test_context_returns_pack(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory()
    hub.add(trigger(1), context(trigger(1)))
    assert HubClient(hub.url).context(1)["card"]["id"] == 1


def test_context_business_error(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(1)])
    with pytest.raises(HubError):
        HubClient(hub.url).context(1)


def test_context_http_error(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(1)])
    hub.error_ids.add(1)
    with pytest.raises(HubError):
        HubClient(hub.url).context(1)


def test_judge_posts_exact_body(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(1)])
    payload = HubClient(hub.url).judge(
        1, action="observe", reason="等", next_check="10:30", risk="跌破 10.2"
    )
    assert payload["ok"] is True
    assert hub.judgements[0]["body"] == {
        "action": "observe",
        "reason": "等",
        "next_check": "10:30",
        "risk": "跌破 10.2",
    }


def test_judge_rejection_is_returned(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(1)])
    hub.reject_ids.add(1)
    payload = HubClient(hub.url).judge(
        1, action="observe", reason="等", next_check="10:30", risk="边界"
    )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_value"


def test_client_strips_trailing_slash(hub_factory: Callable[..., Any]) -> None:
    hub = hub_factory([trigger(1)])
    assert HubClient(hub.url + "/").triggers_since(0)[0]["id"] == 1
