from __future__ import annotations

import json

from portfolio_mcp.server import TOOLS, TOOL_NAMES, create_server, dispatch
from portfolio_mcp.service import PortfolioService

EXPECTED_TOOLS = [
    "portfolio_add_position",
    "portfolio_clear",
    "portfolio_get",
    "portfolio_record_trade",
    "portfolio_trade_history",
    "portfolio_import_commit",
    "portfolio_import_preview",
    "portfolio_parse_csv",
    "portfolio_remove_position",
    "portfolio_risk",
    "portfolio_set_cash",
    "portfolio_update_position",
    "portfolio_valuation",
]


def test_expected_tools() -> None:
    assert sorted(TOOL_NAMES) == sorted(EXPECTED_TOOLS)
    assert len(TOOLS) == 13


def test_commit_description_allows_direct_commit_after_preview() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "portfolio_import_commit")
    description = tool.description or ""
    assert "preview 后可直接 commit" in description
    assert "警告" in description
    assert "覆盖" in description


def test_edit_tools_do_not_require_a_second_confirmation() -> None:
    for name in (
        "portfolio_update_position",
        "portfolio_remove_position",
        "portfolio_set_cash",
    ):
        tool = next(tool for tool in TOOLS if tool.name == name)
        description = tool.description or ""
        assert "Only call when the user states" not in description
        assert "do not ask for a second confirmation" in description


def test_risk_description_limits_use_to_portfolio_diagnosis() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "portfolio_risk")
    description = tool.description or ""
    assert "只在用户要求诊断持仓时调用" in description
    assert "private" in description


def test_dispatch_unknown_tool() -> None:
    payload = dispatch(PortfolioService.__new__(PortfolioService), "portfolio_wipe", {})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_tool"


def test_dispatch_routes_all_tools(service: PortfolioService) -> None:
    assert dispatch(service, "portfolio_get", {})["status"] == "empty"
    parsed = dispatch(
        service,
        "portfolio_parse_csv",
        {"text": "代码,名称,数量,成本价\n600000,浦发银行,1000,9.5\n"},
    )
    assert parsed["data"]["count"] == 1
    preview = dispatch(service, "portfolio_import_preview", {"rows": parsed["data"]["rows"]})
    token = preview["data"]["confirm_token"]
    assert dispatch(service, "portfolio_import_commit", {"confirm_token": token})["ok"] is True
    assert dispatch(service, "portfolio_set_cash", {"cash": 100})["ok"] is True
    added = dispatch(
        service,
        "portfolio_add_position",
        {"code": "000001", "quantity": 100, "cost": 9.5, "name": "平安银行"},
    )
    assert added["ok"] is True
    assert added["data"]["after"]["qty"] == 100
    assert dispatch(
        service, "portfolio_update_position", {"code": "600000", "fields": {"qty": 900}}
    )["ok"] is True
    assert dispatch(service, "portfolio_remove_position", {"code": "600000"})["ok"] is True
    assert dispatch(service, "portfolio_clear", {"confirm": True})["ok"] is True
    assert dispatch(service, "portfolio_valuation", {})["status"] == "empty"
    assert dispatch(service, "portfolio_risk", {})["status"] == "empty"


async def test_mcp_session_lists_and_calls_tools(service: PortfolioService) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(service)
    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()
        assert sorted(tool.name for tool in listed.tools) == sorted(EXPECTED_TOOLS)

        empty = await session.call_tool("portfolio_get", {})
        empty_payload = json.loads(empty.content[0].text)
        assert empty_payload["status"] == "empty"
        assert empty_payload["private"] is True

        risk = await session.call_tool("portfolio_risk", {})
        risk_payload = json.loads(risk.content[0].text)
        assert risk_payload["status"] == "empty"
        assert risk_payload["private"] is True

        preview = await session.call_tool(
            "portfolio_import_preview",
            {"rows": [{"code": "600000", "name": "浦发银行", "qty": 1000, "cost_price": 9.5}]},
        )
        preview_payload = json.loads(preview.content[0].text)
        token = preview_payload["data"]["confirm_token"]

        commit = await session.call_tool("portfolio_import_commit", {"confirm_token": token})
        commit_payload = json.loads(commit.content[0].text)
        assert commit_payload["data"]["written"] is True

        reused = await session.call_tool("portfolio_import_commit", {"confirm_token": token})
        reused_payload = json.loads(reused.content[0].text)
        assert reused_payload["error"]["code"] == "invalid_token"


async def test_mcp_session_rejects_sensitive_text(service: PortfolioService) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    account = "3" * 15
    server = create_server(service)
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "portfolio_parse_csv",
            {"text": f"代码,名称,数量,成本价,资金账号\n600000,浦发,1000,9.5,{account}\n"},
        )
        payload = json.loads(result.content[0].text)
        assert payload["error"]["code"] == "sensitive_text"
        assert account not in json.dumps(payload, ensure_ascii=False)
