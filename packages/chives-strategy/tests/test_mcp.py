from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from chives_strategy.daemon import HubDaemon

from .support import build_service


def _start_hub(databases: dict[str, Path]) -> tuple[HubDaemon, str]:
    service = build_service(databases)
    daemon = HubDaemon(service, port=0).start()
    return daemon, f"http://127.0.0.1:{daemon.port}"


def _session(url: str, allowed: str) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["CHIVES_STRATEGIES"] = allowed
    return subprocess.Popen(
        [sys.executable, "-m", "chives_strategy.mcp_server", "--url", url],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )


def _exchange(process: subprocess.Popen[str], message: dict) -> dict:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    assert line, "MCP server closed stdout"
    return json.loads(line)


def test_mcp_tools_list_and_forwarding(databases: dict[str, Path]) -> None:
    daemon, url = _start_hub(databases)
    process = _session(url, "zhushenglang")
    try:
        init = _exchange(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}},
            },
        )
        assert init["result"]["serverInfo"]["name"] == "strategy"

        listing = _exchange(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [tool["name"] for tool in listing["result"]["tools"]]
        assert names == [
            "strategy_list",
            "strategy_pools",
            "strategy_round",
            "strategy_events",
            "strategy_levels",
            "strategy_backtest",
            "strategy_backtest_result",
            "strategy_annotate",
        ]
        descriptions = " ".join(tool["description"] for tool in listing["result"]["tools"])
        assert "前复权" in descriptions
        assert "不是投资建议" in descriptions
        assert "不代表未来收益" in descriptions
        assert "冻结" in descriptions

        call = _exchange(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "strategy_pools",
                    "arguments": {"strategy_id": "zhushenglang", "date": "2026-11-17", "pool": "main", "limit": 1},
                },
            },
        )
        payload = json.loads(call["result"]["content"][0]["text"])
        assert payload["strategy"] == "zhushenglang"
        assert payload["pools"]["main"][0]["code"] == "600519.SH"
        assert "first" not in payload["pools"]
    finally:
        process.terminate()
        process.wait(timeout=5)
        daemon.stop()


def test_mcp_rejects_strategy_outside_chives_strategies(databases: dict[str, Path]) -> None:
    daemon, url = _start_hub(databases)
    process = _session(url, "other")
    try:
        _exchange(
            process,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        )
        call = _exchange(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "strategy_levels", "arguments": {"strategy_id": "zhushenglang", "code": "600519.SH"}},
            },
        )
        payload = json.loads(call["result"]["content"][0]["text"])
        assert payload["ok"] is False
        assert "CHIVES_STRATEGIES" in payload["message"]
    finally:
        process.terminate()
        process.wait(timeout=5)
        daemon.stop()
