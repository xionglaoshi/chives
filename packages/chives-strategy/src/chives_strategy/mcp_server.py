"""Stdio MCP forwarding layer for strategy-hub (standard library only).

Every tool call becomes one GET request to the loopback daemon.  Keeping the
forwarder dependency-free matches the rest of the strategy rule layer and lets
the server inject ``CHIVES_STRATEGIES`` per bot.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import __version__

logger = logging.getLogger(__name__)
SERVER_NAME = "strategy"
DEFAULT_URL = "http://127.0.0.1:8869"
TIMEOUT_SECONDS = 30.0

STRATEGY_ID = {
    "type": "string",
    "description": "策略 ID；本期为 zhushenglang（主升浪）。",
}
CODE = {"type": "string", "description": "股票代码，形如 600519.SH / 000001.SZ。"}
DATE = {"type": "string", "description": "交易日 YYYY-MM-DD；省略时用最新计算日。"}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "strategy_list",
        "description": "列出可用策略、中文说明与最新计算日。只读；规则在收盘后计算，前复权，不使用未来数据，不是投资建议。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "strategy_pools",
        "description": "读取某策略某日的首板观察池与主升浪池排序（含分项、优先级、状态）。前复权、收盘后计算、不使用未来数据，不是投资建议。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": STRATEGY_ID,
                "date": DATE,
                "pool": {"type": "string", "enum": ["first", "main"], "description": "只取一个池；省略返回两个池。"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "每个池最多返回多少行。"},
            },
            "required": ["strategy_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "strategy_round",
        "description": "读取某股当前/最近轮次的全部事件、分项与每日快照。前复权、收盘后计算、不使用未来数据，不是投资建议。",
        "inputSchema": {
            "type": "object",
            "properties": {"strategy_id": STRATEGY_ID, "code": CODE, "date": DATE},
            "required": ["strategy_id", "code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "strategy_events",
        "description": "读取策略事件流，可按日期区间与事件名过滤。前复权、收盘后计算、不使用未来数据，不是投资建议。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": STRATEGY_ID,
                "start": {"type": "string", "description": "起始日 YYYY-MM-DD（含）。"},
                "end": {"type": "string", "description": "结束日 YYYY-MM-DD（含）。"},
                "kinds": {"type": "string", "description": "事件名，逗号分隔，例如 优先级一确定,入主升浪池,主升浪移出。"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "required": ["strategy_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "strategy_levels",
        "description": "读取可交给盯盘的价位：突破线 Hb、标记价 P*、两条支撑、MA10，每项带口径说明。前复权、收盘后计算，不是买卖建议。",
        "inputSchema": {
            "type": "object",
            "properties": {"strategy_id": STRATEGY_ID, "code": CODE},
            "required": ["strategy_id", "code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "strategy_backtest",
        "description": "按冻结的买卖与费用规则启动历史回测（异步），返回 job_id；用 strategy_backtest_result 轮询。按冻结规则的历史模拟，不代表未来收益，不是投资建议。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": STRATEGY_ID,
                "scheme": {
                    "type": "string",
                    "enum": ["p1", "p2", "start", "second_board"],
                    "description": "入场方案：p1 优先级一、p2 优先级二、start 启动日、second_board 二板日。",
                },
                "start": {"type": "string", "description": "回测起始日 YYYY-MM-DD，默认 2020-01-01。"},
                "end": {"type": "string", "description": "回测结束日 YYYY-MM-DD，省略用最新计算日。"},
            },
            "required": ["strategy_id", "scheme"],
            "additionalProperties": False,
        },
    },
    {
        "name": "strategy_backtest_result",
        "description": "读取某回测任务的状态与摘要（含买不到/跳过比例、最大回撤、样本外表现）。按冻结规则的历史模拟，不代表未来收益，不是投资建议。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": STRATEGY_ID,
                "job_id": {"type": "string", "description": "strategy_backtest 返回的任务 ID。"},
            },
            "required": ["strategy_id", "job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "strategy_annotate",
        "description": "生成某轮次的 K 线标注 JSON 与图片（HTML/SVG）路径，用于人工复核首板、黄金坑与突破线。前复权、收盘后计算，不是投资建议。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": STRATEGY_ID,
                "code": CODE,
                "round_id": {"type": "integer", "minimum": 1, "description": "轮次 ID，先用 strategy_round 获取。"},
            },
            "required": ["strategy_id", "code", "round_id"],
            "additionalProperties": False,
        },
    },
]


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _json_payload(status: str, message: str) -> dict[str, Any]:
    return {"ok": False, "status": status, "message": message}


class StrategyClient:
    def __init__(self, base_url: str = DEFAULT_URL, allowed: list[str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.allowed = allowed

    def _check(self, strategy_id: str) -> dict[str, Any] | None:
        if self.allowed is not None and strategy_id not in self.allowed:
            allowed = "、".join(self.allowed) if self.allowed else "（空）"
            return _json_payload("unavailable", f"策略 {strategy_id} 不在可用列表（CHIVES_STRATEGIES）中；可用：{allowed}")
        return None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = {key: value for key, value in (params or {}).items() if value is not None and value != ""}
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        try:
            with _opener().open(urllib.request.Request(url, method="GET"), timeout=TIMEOUT_SECONDS) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
                if isinstance(body, dict):
                    return body
            except (ValueError, UnicodeDecodeError):
                pass
            return _json_payload("unavailable", f"策略服务返回 HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError):
            return _json_payload("unavailable", "策略服务没有启动，请先启动 chives-strategy（127.0.0.1:8869）")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return _json_payload("unavailable", "策略服务返回了无法识别的内容")
        return payload if isinstance(payload, dict) else _json_payload("unavailable", "策略服务返回了无法识别的内容")

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _opener().open(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
                if isinstance(body, dict):
                    return body
            except (ValueError, UnicodeDecodeError):
                pass
            return _json_payload("unavailable", f"策略服务返回 HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError):
            return _json_payload("unavailable", "策略服务没有启动，请先启动 chives-strategy（127.0.0.1:8869）")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return _json_payload("unavailable", "策略服务返回了无法识别的内容")
        return result if isinstance(result, dict) else _json_payload("unavailable", "策略服务返回了无法识别的内容")

    def backtest(
        self,
        strategy_id: str,
        scheme: str,
        start: str | None,
        end: str | None,
    ) -> dict[str, Any]:
        error = self._check(strategy_id)
        if error is not None:
            return error
        return self._post(
            f"/v1/{urllib.parse.quote(strategy_id)}/backtest",
            {"scheme": scheme, "start": start, "end": end},
        )

    def backtest_result(self, strategy_id: str, job_id: str) -> dict[str, Any]:
        error = self._check(strategy_id)
        if error is not None:
            return error
        return self._get(
            f"/v1/{urllib.parse.quote(strategy_id)}/backtest/{urllib.parse.quote(job_id)}"
        )

    def list_strategies(self) -> dict[str, Any]:
        payload = self._get("/v1/strategies")
        rows = payload.get("strategies")
        if self.allowed is not None and isinstance(rows, list):
            payload = dict(payload)
            payload["strategies"] = [
                row for row in rows if isinstance(row, dict) and row.get("id") in self.allowed
            ]
        return payload

    def pools(self, strategy_id: str, date: str | None, pool: str | None, limit: int | None) -> dict[str, Any]:
        error = self._check(strategy_id)
        if error is not None:
            return error
        payload = self._get(f"/v1/{urllib.parse.quote(strategy_id)}/pools", {"date": date})
        if not isinstance(payload.get("pools"), dict):
            return payload
        if pool in {"first", "main"}:
            rows = payload["pools"].get(pool) or []
            if limit:
                rows = rows[:limit]
            payload = dict(payload)
            payload["pools"] = {pool: rows}
        elif limit:
            payload = dict(payload)
            payload["pools"] = {
                key: (rows or [])[:limit] for key, rows in payload["pools"].items()
            }
        return payload

    def round(self, strategy_id: str, code: str, date: str | None) -> dict[str, Any]:
        error = self._check(strategy_id)
        if error is not None:
            return error
        return self._get(f"/v1/{urllib.parse.quote(strategy_id)}/round", {"code": code, "date": date})

    def events(
        self,
        strategy_id: str,
        start: str | None,
        end: str | None,
        kinds: str | None,
        limit: int | None,
    ) -> dict[str, Any]:
        error = self._check(strategy_id)
        if error is not None:
            return error
        return self._get(
            f"/v1/{urllib.parse.quote(strategy_id)}/events",
            {"start": start, "end": end, "kinds": kinds, "limit": limit},
        )

    def levels(self, strategy_id: str, code: str) -> dict[str, Any]:
        error = self._check(strategy_id)
        if error is not None:
            return error
        return self._get(f"/v1/{urllib.parse.quote(strategy_id)}/levels", {"code": code})

    def annotate(self, strategy_id: str, code: str, round_id: int) -> dict[str, Any]:
        error = self._check(strategy_id)
        if error is not None:
            return error
        return self._get(
            f"/v1/{urllib.parse.quote(strategy_id)}/annotate", {"code": code, "round_id": round_id}
        )

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "strategy_list":
            return self.list_strategies()
        if name not in {schema["name"] for schema in TOOL_SCHEMAS}:
            return _json_payload("unavailable", f"没有这个工具：{name}")
        strategy_id = str(args.get("strategy_id") or "").strip()
        if strategy_id == "":
            return _json_payload("unavailable", "参数 strategy_id 不能为空")
        if name == "strategy_backtest":
            scheme = str(args.get("scheme") or "").strip()
            if scheme == "":
                return _json_payload("unavailable", "参数 scheme 不能为空")
            return self.backtest(strategy_id, scheme, _text(args.get("start")), _text(args.get("end")))
        if name == "strategy_backtest_result":
            job_id = str(args.get("job_id") or "").strip()
            if job_id == "":
                return _json_payload("unavailable", "参数 job_id 不能为空")
            return self.backtest_result(strategy_id, job_id)
        if name == "strategy_pools":
            return self.pools(
                strategy_id,
                _text(args.get("date")),
                _text(args.get("pool")),
                _positive(args.get("limit")),
            )
        if name == "strategy_round":
            code = str(args.get("code") or "").strip().upper()
            if code == "":
                return _json_payload("unavailable", "参数 code 不能为空")
            return self.round(strategy_id, code, _text(args.get("date")))
        if name == "strategy_events":
            return self.events(
                strategy_id,
                _text(args.get("start")),
                _text(args.get("end")),
                _text(args.get("kinds")),
                _positive(args.get("limit")),
            )
        if name == "strategy_levels":
            code = str(args.get("code") or "").strip().upper()
            if code == "":
                return _json_payload("unavailable", "参数 code 不能为空")
            return self.levels(strategy_id, code)
        code = str(args.get("code") or "").strip().upper()
        round_id = _positive(args.get("round_id"))
        if code == "" or round_id is None:
            return _json_payload("unavailable", "参数 code 与 round_id 不能为空")
        return self.annotate(strategy_id, code, round_id)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _positive(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


class McpProtocol:
    def __init__(self, client: StrategyClient) -> None:
        self.client = client

    def tools(self) -> list[dict[str, Any]]:
        return TOOL_SCHEMAS

    def response(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method is None:
            return None
        if method.startswith("notifications/"):
            return None
        if request_id is None and not method.startswith("initialize"):
            # A notification (for example notifications/initialized); no reply.
            return None
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if isinstance(requested, str) and requested else "2024-11-05"
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tools()}}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(name, str):
                return self._error(request_id, -32602, "tools/call 需要工具名")
            payload = self.client.call(name, arguments if isinstance(arguments, dict) else {})
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, ensure_ascii=False, allow_nan=False)}
                    ],
                    "isError": False,
                },
            }
        return self._error(request_id, -32601, f"不支持的方法：{method}")

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(client: StrategyClient) -> int:
    protocol = McpProtocol(client)
    for line in sys.stdin:
        line = line.strip()
        if line == "":
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("ignored invalid JSON-RPC line")
            continue
        if not isinstance(message, dict):
            continue
        response = protocol.response(message)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="strategy-mcp", description="chives-strategy stdio MCP forwarder")
    parser.add_argument("--url", default=(os.environ.get("CHIVES_STRATEGY_URL") or DEFAULT_URL))
    parsed = parser.parse_args(argv)
    raw_allowed = os.environ.get("CHIVES_STRATEGIES")
    allowed = None if raw_allowed is None else [part.strip() for part in raw_allowed.split(",") if part.strip()]
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s: %(message)s")
    return serve(StrategyClient(parsed.url, allowed))


if __name__ == "__main__":
    raise SystemExit(main())
