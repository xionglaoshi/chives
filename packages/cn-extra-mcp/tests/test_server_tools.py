from __future__ import annotations

from cn_extra_mcp import server


def test_exactly_eight_tools() -> None:
    names = [tool.name for tool in server.TOOLS]
    assert names == [
        "cn_get_minute_bars",
        "cn_get_quote_snapshot",
        "cn_intraday_summary",
        "cn_get_announcements",
        "cn_read_announcement",
        "cn_get_daily_bars",
        "cn_get_global_snapshot",
        "cn_get_overseas_quote",
    ]
    assert all(tool.inputSchema["type"] == "object" for tool in server.TOOLS)
    announcements = server.TOOLS[3].inputSchema
    assert announcements["properties"]["limit"]["minimum"] == 1
    assert announcements["properties"]["limit"]["maximum"] == 100
    assert announcements["required"] == ["code"]
    pdf = server.TOOLS[4].inputSchema
    assert pdf["required"] == ["url"]
    assert pdf["properties"]["start_page"]["default"] == 1
    assert pdf["properties"]["max_chars"]["minimum"] == 500
    assert pdf["properties"]["max_chars"]["maximum"] == 200000
    assert pdf["properties"]["layout"]["default"] is True


def test_missing_arguments_are_envelopes() -> None:
    for name, args in (
        ("cn_get_minute_bars", {}),
        ("cn_get_quote_snapshot", {}),
        ("cn_intraday_summary", {"code": "002553"}),
        ("cn_get_announcements", {}),
        ("cn_read_announcement", {}),
        ("cn_get_overseas_quote", {}),
    ):
        payload = server.dispatch(name, args)
        assert payload["ok"] is False
        assert payload["status"] == "error"
        assert payload["error"]["code"] == "invalid_argument"


def test_announcement_dispatch_passes_defaults(monkeypatch) -> None:
    seen: dict = {}

    def fake(**kwargs) -> dict:
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(server.service, "cn_get_announcements", fake)
    assert server.dispatch("cn_get_announcements", {"code": "002553"}) == {"ok": True}
    assert seen == {
        "code": "002553",
        "start_date": None,
        "end_date": None,
        "category": None,
        "limit": 20,
    }


def test_read_announcement_dispatch_passes_defaults(monkeypatch) -> None:
    seen: dict = {}

    def fake(**kwargs) -> dict:
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(server.service, "cn_read_announcement", fake)
    assert server.dispatch("cn_read_announcement", {"url": "http://x"}) == {"ok": True}
    assert seen == {
        "url": "http://x",
        "start_page": 1,
        "end_page": None,
        "max_chars": 20000,
        "layout": True,
    }


def test_unknown_tool() -> None:
    payload = server.dispatch("nope", {})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_tool"


def test_global_snapshot_schema_and_dispatch(monkeypatch) -> None:
    schema = next(t for t in server.TOOLS if t.name == "cn_get_global_snapshot").inputSchema
    assert schema["properties"]["groups"]["items"]["enum"] == [
        "us_index", "hk_index", "a50", "fx", "commodity", "rates", "leaders",
    ]
    assert "required" not in schema
    seen: list = []
    monkeypatch.setattr(server.global_market, "cn_get_global_snapshot", lambda groups: seen.append(groups) or {"ok": True})
    assert server.dispatch("cn_get_global_snapshot", {}) == {"ok": True}
    assert server.dispatch("cn_get_global_snapshot", {"groups": ["a50"]}) == {"ok": True}
    assert seen == [None, ["a50"]]


def test_overseas_quote_schema_and_dispatch(monkeypatch) -> None:
    schema = next(t for t in server.TOOLS if t.name == "cn_get_overseas_quote").inputSchema
    assert schema["required"] == ["symbols"]
    assert schema["properties"]["symbols"]["maxItems"] == 10
    seen: list = []
    monkeypatch.setattr(server.global_market, "cn_get_overseas_quote", lambda symbols: seen.append(symbols) or {"ok": True})
    assert server.dispatch("cn_get_overseas_quote", {"symbols": ["usNVDA"]}) == {"ok": True}
    assert seen == [["usNVDA"]]
