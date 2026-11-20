"""Tool dispatch and argument validation for the cn-watch MCP server."""

from __future__ import annotations

from typing import Any

from .client import (
    EngineAPIError,
    EngineHTTPError,
    EngineResponseError,
    EngineUnreachable,
    WatchClient,
)
from .envelope import as_of_from, failure, success, warnings_for

ERROR_HINTS = {
    "invalid_symbol": "代码格式不正确，应为 6 位数字，可带 .SH/.SZ 后缀",
    "unsupported_market": "引擎暂不支持北交所",
    "unsupported_instrument": "引擎暂不支持指数代码",
    "quote_unavailable": "取不到该代码的行情，未加入自选股",
    "watchlist_full": "自选股数量已达上限",
    "protected_symbol": "该标的来自配置文件，不能通过接口删除；请修改 config/watch.yaml",
    "persistence_error": "引擎无法写入运行时自选股文件",
    "invalid_rule": "规则字段校验失败，请对照配置格式检查",
    "invalid_id": "规则 id 只能包含字母、数字、下划线、连字符，长度 1~40",
    "out_of_bounds": "阈值超出允许范围",
    "rules_full": "规则数量已达上限",
    "rule_not_found": "规则不存在，无法修改或撤销",
}


class InvalidArgument(ValueError):
    pass


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidArgument(f"{name} must be an integer")
    return value


def _after_id(value: Any) -> int:
    parsed = _integer(value, "after_id")
    if parsed < 0:
        raise InvalidArgument("after_id must be a non-negative integer")
    return parsed


def _limit(value: Any) -> int:
    parsed = _integer(value, "limit")
    if parsed < 1 or parsed > 500:
        raise InvalidArgument("limit must be an integer from 1 to 500")
    return parsed


def _code(value: Any) -> str | int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidArgument("code must be a string or integer stock code")
    if isinstance(value, str) and not value.strip():
        raise InvalidArgument("code must not be empty")
    return value


def _rule(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidArgument("rule must be a JSON object")
    return value


def _rule_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidArgument("id must be a non-empty string")
    return value.strip()


def _history_limit(value: Any) -> int:
    parsed = _integer(value, "limit")
    if parsed < 1 or parsed > 500:
        raise InvalidArgument("limit must be an integer from 1 to 500")
    return parsed


def _rule_change_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = {
        key: payload.get(key)
        for key in (
            "status",
            "rule_id",
            "source",
            "before",
            "after",
            "count",
            "limit",
        )
    }
    data["id"] = payload.get("rule_id")
    return data


def _history_data(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("history")
    if not isinstance(rows, list):
        raise EngineResponseError("cn-watch engine did not return a history array")
    return {"history": rows, "count": len(rows)}


def _alerts_data(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("alerts")
    if not isinstance(rows, list):
        raise EngineResponseError("cn-watch engine did not return an alerts array")
    return {"alerts": rows, "count": len(rows), "untrusted_text": True}


def _watchlist_data(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("watchlist")
    if not isinstance(rows, list):
        raise EngineResponseError("cn-watch engine did not return a watchlist array")
    return {
        "watchlist": rows,
        "count": len(rows),
        "limit": payload.get("limit"),
        "untrusted_text": True,
    }


def _symbol_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = {
        key: payload.get(key)
        for key in ("status", "code", "name", "source", "count", "limit")
    }
    data["untrusted_text"] = True
    return data


def _api_failure(exc: EngineAPIError) -> dict[str, Any]:
    message = exc.message
    hint = ERROR_HINTS.get(exc.code)
    if hint and hint not in message:
        message = f"{message}（{hint}）"
    return failure(exc.code, message, status_code=exc.status_code)


def dispatch(name: str, arguments: dict[str, Any] | None, client: WatchClient) -> dict[str, Any]:
    if arguments is not None and not isinstance(arguments, dict):
        return failure("invalid_argument", "arguments must be a JSON object")
    args = arguments or {}
    try:
        if name == "watch_get_alerts":
            after_id = _after_id(args["after_id"]) if "after_id" in args else 0
            limit = _limit(args["limit"]) if "limit" in args else 50
            payload = client.get_json("/alerts", {"after_id": after_id, "limit": limit})
            return success(_alerts_data(payload), warnings=warnings_for(payload))
        if name == "watch_get_health":
            payload = client.get_json("/health")
            return success(payload, as_of=as_of_from(payload), warnings=warnings_for(payload))
        if name == "watch_get_state":
            payload = client.get_json("/state")
            return success(payload, as_of=as_of_from(payload), warnings=warnings_for(payload))
        if name == "watch_get_rules":
            payload = client.get_json("/rules")
            return success(payload, as_of=as_of_from(payload), warnings=warnings_for(payload))
        if name == "watch_get_watchlist":
            payload = client.get_json("/watchlist")
            return success(_watchlist_data(payload))
        if name == "watch_add_symbol":
            if "code" not in args:
                raise InvalidArgument("code is required")
            payload = client.post_json("/watchlist/add", {"code": _code(args["code"])})
            return success(_symbol_data(payload))
        if name == "watch_remove_symbol":
            if "code" not in args:
                raise InvalidArgument("code is required")
            payload = client.post_json("/watchlist/remove", {"code": _code(args["code"])})
            return success(_symbol_data(payload))
        if name == "watch_upsert_rule":
            if "rule" in args:
                value = args["rule"]
            elif "id" in args and "type" in args:
                value = args
            else:
                raise InvalidArgument("rule is required")
            payload = client.post_json(
                "/rules/upsert", _rule(value), actor="agent"
            )
            return success(_rule_change_data(payload))
        if name == "watch_remove_rule":
            if "id" not in args:
                raise InvalidArgument("id is required")
            payload = client.post_json(
                "/rules/remove", {"id": _rule_id(args["id"])}, actor="agent"
            )
            return success(_rule_change_data(payload))
        if name == "watch_revert_rule":
            if "id" not in args:
                raise InvalidArgument("id is required")
            payload = client.post_json(
                "/rules/revert", {"id": _rule_id(args["id"])}, actor="agent"
            )
            return success(_rule_change_data(payload))
        if name == "watch_get_rule_history":
            limit = _history_limit(args["limit"]) if "limit" in args else 50
            payload = client.get_json(
                "/rules/history", {"limit": limit}, actor="agent"
            )
            return success(_history_data(payload))
    except InvalidArgument as exc:
        return failure("invalid_argument", str(exc))
    except EngineUnreachable as exc:
        return failure("engine_unreachable", str(exc))
    except EngineAPIError as exc:
        return _api_failure(exc)
    except EngineHTTPError as exc:
        return failure("engine_error", str(exc), status_code=exc.status_code)
    except EngineResponseError as exc:
        return failure("engine_error", str(exc))
    return failure("unknown_tool", f"unknown tool: {name}")
