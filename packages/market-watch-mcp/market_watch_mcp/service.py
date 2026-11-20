"""Tool dispatch and argument validation for the market-watch MCP server."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .client import (
    EngineHTTPError,
    EngineResponseError,
    EngineUnreachable,
    MarketClient,
    ResponseTooLarge,
)
from .envelope import (
    as_of_from,
    failure,
    is_empty,
    passthrough_error,
    success,
    warnings_for,
)

SECTOR_CODE = re.compile(r"^BK[0-9]{4}$")
DATE_FORMAT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
POOL_VIEWS = {
    "ladder": "/pool/ladder",
    "history": "/pool/history",
    "yesterday": "/pool/yesterday",
    "by_industry": "/pool/by-industry",
}


class InvalidArgument(ValueError):
    pass


def _integer(value: Any, name: str, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidArgument(f"{name} must be an integer")
    if value < low or (high is not None and value > high):
        bound = f"from {low} to {high}" if high is not None else f">= {low}"
        raise InvalidArgument(f"{name} must be an integer {bound}")
    return value


def _choice(value: Any, name: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InvalidArgument(f"{name} must be one of {', '.join(allowed)}")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidArgument(f"{name} must be a boolean")
    return value


def _code(value: Any) -> str:
    if not isinstance(value, str) or not SECTOR_CODE.fullmatch(value):
        raise InvalidArgument("code must match BK followed by 4 digits, e.g. BK0433")
    return value


def _date(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not DATE_FORMAT.fullmatch(value):
        raise InvalidArgument("date must be YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise InvalidArgument("date is not a valid calendar date") from exc
    return value


def _check_keys(args: dict[str, Any], allowed: tuple[str, ...]) -> None:
    extra = sorted(set(args) - set(allowed))
    if extra:
        raise InvalidArgument(f"unexpected argument: {', '.join(extra)}")


def _required(args: dict[str, Any], name: str) -> Any:
    if name not in args:
        raise InvalidArgument(f"{name} is required")
    return args[name]


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is False:
        error = payload.get("error")
        if error is None:
            error = {"code": "engine_error", "message": "engine returned ok=false"}
        return passthrough_error(error)
    status = "empty" if is_empty(payload) else "ready"
    return success(
        payload, as_of=as_of_from(payload), warnings=warnings_for(payload), status=status
    )


def _truncate(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    rows = payload.get("rows")
    if isinstance(rows, list) and len(rows) > limit:
        payload = dict(payload)
        payload["rows"] = rows[:limit]
    return payload


def _sector(args: dict[str, Any], client: MarketClient) -> dict[str, Any]:
    _check_keys(args, ("code", "members", "member_limit"))
    code = _code(_required(args, "code"))
    members = _bool(args["members"], "members") if "members" in args else False
    member_limit = _integer(args["member_limit"], "member_limit", 5, 100) if "member_limit" in args else 20
    detail = client.get_json(f"/sectors/{code}")
    result = _result(detail)
    if not result["ok"] or not members:
        return result
    try:
        member_payload = client.get_json(f"/sectors/{code}/members")
        if member_payload.get("ok") is False:
            raise EngineResponseError("members endpoint returned ok=false")
    except (EngineUnreachable, EngineHTTPError, EngineResponseError, ResponseTooLarge):
        result["warnings"].append("members_unavailable")
        return result
    result["data"]["members"] = _truncate(member_payload, member_limit)
    for warning in warnings_for(member_payload):
        if warning not in result["warnings"]:
            result["warnings"].append(warning)
    return result


def _dispatch(name: str, args: dict[str, Any], client: MarketClient) -> dict[str, Any] | None:
    if name == "mkt_get_overview":
        _check_keys(args, ())
        return _result(client.get_json("/overview"))
    if name == "mkt_get_summary":
        _check_keys(args, ())
        return _result(client.get_json("/summary"))
    if name == "mkt_get_sectors":
        _check_keys(args, ("limit",))
        limit = _integer(args["limit"], "limit", 5, 40) if "limit" in args else 30
        payload = client.get_json("/sectors", {"level": "sw1"})
        return _result(_truncate(payload, limit))
    if name == "mkt_get_sector":
        return _sector(args, client)
    if name == "mkt_get_themes":
        _check_keys(args, ("sort", "limit"))
        sort = _choice(args["sort"], "sort", ("change", "amount")) if "sort" in args else "change"
        limit = _integer(args["limit"], "limit", 5, 30) if "limit" in args else 20
        return _result(client.get_json("/themes", {"kind": "concept", "sort": sort, "limit": limit}))
    if name == "mkt_get_movers":
        _check_keys(args, ("kind", "limit"))
        kind = _choice(_required(args, "kind"), "kind", ("gainers", "losers", "active"))
        limit = _integer(args["limit"], "limit", 5, 20) if "limit" in args else 10
        return _result(client.get_json("/movers", {"kind": kind, "limit": limit}))
    if name == "mkt_get_flows":
        _check_keys(args, ("kind", "limit"))
        kind = _choice(
            _required(args, "kind"), "kind", ("sector_in", "sector_out", "stock_in", "stock_out")
        )
        limit = _integer(args["limit"], "limit", 5, 20) if "limit" in args else 10
        return _result(client.get_json("/flows", {"kind": kind, "limit": limit}))
    if name == "mkt_get_pool":
        _check_keys(args, ("kind", "date", "limit"))
        kind = _choice(_required(args, "kind"), "kind", ("zt", "zb", "dt"))
        date = _date(args.get("date"))
        limit = _integer(args["limit"], "limit", 1, 200) if "limit" in args else 50
        params: dict[str, Any] = {"kind": kind, "limit": limit}
        if date:
            params["date"] = date
        return _result(client.get_json("/pool", params))
    if name == "mkt_get_pool_stats":
        _check_keys(args, ("view", "date", "days"))
        view = _choice(_required(args, "view"), "view", tuple(POOL_VIEWS))
        date = _date(args.get("date"))
        days = _integer(args["days"], "days", 10, 30) if "days" in args else 20
        params = {}
        if view == "history":
            params["days"] = days
        elif view in ("ladder", "by_industry") and date:
            params["date"] = date
        return _result(client.get_json(POOL_VIEWS[view], params or None))
    if name == "mkt_get_alerts":
        _check_keys(args, ("since_id", "limit"))
        since_id = _integer(args["since_id"], "since_id", 0) if "since_id" in args else 0
        limit = _integer(args["limit"], "limit", 1, 200) if "limit" in args else 50
        return _result(client.get_json("/alerts", {"since_id": since_id, "limit": limit}))
    return None


def dispatch(name: str, arguments: dict[str, Any] | None, client: MarketClient) -> dict[str, Any]:
    if arguments is not None and not isinstance(arguments, dict):
        return failure("invalid_argument", "arguments must be a JSON object")
    try:
        result = _dispatch(name, arguments or {}, client)
    except InvalidArgument as exc:
        return failure("invalid_argument", str(exc))
    except EngineUnreachable as exc:
        return failure("engine_unreachable", str(exc))
    except EngineHTTPError as exc:
        return failure("engine_error", str(exc), status_code=exc.status_code)
    except ResponseTooLarge as exc:
        return failure("response_too_large", str(exc))
    except EngineResponseError as exc:
        return failure("engine_error", str(exc))
    if result is None:
        return failure("unknown_tool", f"unknown tool: {name}")
    return result
