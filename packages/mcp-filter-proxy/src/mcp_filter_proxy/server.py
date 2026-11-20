"""Allowlist filtering, metadata, caching and rate limiting around the upstream."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from mcp_filter_proxy import PROXY_NAME, __version__
from mcp_filter_proxy.cache import ResultCache, SlidingWindowLimiter, cache_key
from mcp_filter_proxy.config import (
    CHECK_BARS_WITHIN_REQUESTED_DATES,
    CHECK_NON_EMPTY_RESULT,
    CheckConfig,
    ProxyConfig,
)
from mcp_filter_proxy.upstream import UpstreamGateway, UpstreamUnavailable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExposedTool:
    upstream_name: str
    tool: types.Tool


@dataclass
class ProxyRuntime:
    config: ProxyConfig
    gateway: UpstreamGateway
    registry: dict[str, ExposedTool]
    cache: ResultCache
    limiter: SlidingWindowLimiter


def build_registry(
    upstream_tools: tuple[types.Tool, ...], allow: tuple[str, ...], prefix: str
) -> tuple[dict[str, ExposedTool], list[str]]:
    available = {tool.name: tool for tool in upstream_tools}
    registry: dict[str, ExposedTool] = {}
    missing: list[str] = []
    for upstream_name in allow:
        tool = available.get(upstream_name)
        if tool is None:
            missing.append(upstream_name)
            continue
        exposed_name = f"{prefix}{upstream_name}"
        registry[exposed_name] = ExposedTool(
            upstream_name=upstream_name,
            tool=tool.model_copy(update={"name": exposed_name}),
        )
    return registry, missing


def _error_result(code: str, message: str, **extra: Any) -> types.CallToolResult:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    payload = {"ok": False, "status": "error", "error": error}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        isError=True,
    )


def _rate_limited_result(max_calls: int) -> types.CallToolResult:
    return _error_result(
        "rate_limited",
        f"rate limit exceeded: at most {max_calls} upstream calls per 60 seconds",
    )


def _is_cacheable(result: types.CallToolResult) -> bool:
    if result.isError:
        return False
    blocks = result.content
    if len(blocks) == 1 and isinstance(blocks[0], types.TextContent):
        try:
            payload = json.loads(blocks[0].text)
        except (TypeError, ValueError):
            return True
        if isinstance(payload, dict) and "ok" in payload:
            return bool(payload["ok"])
    return True


def _json_object(result: types.CallToolResult) -> dict[str, Any] | None:
    """Return the payload when the result is exactly one JSON-object text block."""
    blocks = result.content
    if len(blocks) != 1 or not isinstance(blocks[0], types.TextContent):
        return None
    try:
        payload = json.loads(blocks[0].text)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def attach_meta(
    result: types.CallToolResult,
    cache_state: str,
    latency_ms: float,
    annotations: Mapping[str, Any] | None = None,
) -> types.CallToolResult:
    """Add proxy metadata (and configured annotations) to a JSON object result."""
    payload = _json_object(result)
    if payload is None:
        return result

    meta: dict[str, Any] = dict(annotations or {})
    meta.update(
        {
            "cache": cache_state,
            "latency_ms": max(0, int(round(latency_ms))),
            "proxy": PROXY_NAME,
        }
    )
    key = "_proxy_meta" if "meta" in payload else "meta"
    payload[key] = meta
    block = result.content[0].model_copy(
        update={"text": json.dumps(payload, ensure_ascii=False)}
    )
    return result.model_copy(update={"content": [block]})


def _date_part(value: Any) -> date | None:
    """Parse the leading date of an ISO-like value, tolerating a trailing time."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _check_bars_within_requested_dates(
    result: types.CallToolResult,
    check: CheckConfig,
    arguments: dict[str, Any],
) -> types.CallToolResult | None:
    start_raw = arguments.get(check.start_arg)
    end_raw = arguments.get(check.end_arg)
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start = _date_part(start_raw)
    end = _date_part(end_raw)
    if start is None or end is None or start > end:
        return None

    payload = _json_object(result)
    if payload is None:
        return None

    returned: list[date] = []
    for value in payload.values():
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict):
                continue
            day = _date_part(row.get(check.date_field))
            if day is not None:
                returned.append(day)
    if not returned:
        return None

    if all(start <= day <= end for day in returned):
        return None

    earliest = min(returned).isoformat()
    latest = max(returned).isoformat()
    message = (
        f"upstream returned {check.date_field} values outside the requested range "
        f"{start.isoformat()}..{end.isoformat()}: {earliest}..{latest}"
    )
    extra: dict[str, Any] = {
        "requested": [start_raw, end_raw],
        "returned_dates": [earliest, latest],
        "returned_count": len(returned),
    }
    if check.hint is not None:
        extra["hint"] = check.hint
    return _error_result("date_range_mismatch", message, **extra)


def _text_and_other_blocks(result: types.CallToolResult) -> tuple[str, bool]:
    """Join the text blocks and report whether any non-text block is present."""
    parts: list[str] = []
    has_other = False
    for block in result.content:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        else:
            has_other = True
    return "".join(parts), has_other


def _is_empty_result(result: types.CallToolResult) -> bool:
    """True for a successful result that carries no usable text or an empty JSON list."""
    if result.isError:
        return False
    text, has_other = _text_and_other_blocks(result)
    if not text.strip():
        return not has_other
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return False
    if isinstance(payload, list):
        return len(payload) == 0
    if isinstance(payload, dict):
        rows = payload.get("results")
        return isinstance(rows, list) and len(rows) == 0
    return False


def _check_non_empty_result(
    result: types.CallToolResult,
    check: CheckConfig,
    upstream_tool: str,
) -> types.CallToolResult | None:
    if upstream_tool in check.allow_empty or not _is_empty_result(result):
        return None
    extra: dict[str, Any] = {"tool": upstream_tool}
    if check.hint is not None:
        extra["hint"] = check.hint
    message = f"upstream returned an empty result for '{upstream_tool}'"
    return _error_result("empty_result", message, **extra)


def check_result(
    result: types.CallToolResult,
    checks: tuple[CheckConfig, ...],
    arguments: dict[str, Any],
    upstream_tool: str,
) -> types.CallToolResult | None:
    """Return a replacement error result when a configured response check fails."""
    if result.isError or not checks:
        return None
    for check in checks:
        if check.type == CHECK_BARS_WITHIN_REQUESTED_DATES:
            failure = _check_bars_within_requested_dates(result, check, arguments)
        elif check.type == CHECK_NON_EMPTY_RESULT:
            failure = _check_non_empty_result(result, check, upstream_tool)
        else:  # pragma: no cover - guarded by config validation
            failure = None
        if failure is not None:
            return failure
    return None


async def handle_call(
    runtime: ProxyRuntime, name: str, arguments: dict[str, Any] | None
) -> types.CallToolResult:
    started = time.perf_counter()
    entry = runtime.registry.get(name)
    if entry is None:
        logger.warning("rejected non-allowlisted tool: %s", name)
        return _error_result(
            "tool_not_allowed", f"tool '{name}' is not exposed by this proxy"
        )

    args = arguments or {}
    ttl = runtime.cache.ttl_for(entry.upstream_name)
    key = cache_key(entry.upstream_name, args)

    if ttl > 0:
        cached = runtime.cache.get(key)
        if cached is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            logger.info("cache hit: %s", entry.upstream_name)
            return attach_meta(
                cached,
                "hit",
                elapsed_ms,
                runtime.config.annotations_for(entry.upstream_name),
            )

    if not runtime.limiter.allow():
        logger.warning("rate limited: %s", entry.upstream_name)
        return _rate_limited_result(runtime.limiter.max_calls)

    try:
        result = await runtime.gateway.call_tool(entry.upstream_name, args)
    except UpstreamUnavailable as exc:
        logger.error("upstream unavailable: %s", entry.upstream_name)
        return _error_result("upstream_unavailable", str(exc))
    except TimeoutError:
        logger.error("upstream timeout: %s", entry.upstream_name)
        return _error_result(
            "upstream_timeout", f"upstream tool '{entry.upstream_name}' timed out"
        )
    except Exception as exc:
        logger.error("upstream call failed: %s (%s)", entry.upstream_name, type(exc).__name__)
        return _error_result(
            "upstream_error", f"upstream call failed ({type(exc).__name__})"
        )

    failure = check_result(
        result,
        runtime.config.checks_for(entry.upstream_name),
        args,
        entry.upstream_name,
    )
    if failure is not None:
        logger.warning("response check failed: %s", entry.upstream_name)
        return failure

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    empty = _is_empty_result(result)
    cacheable = not empty and _is_cacheable(result)
    if cacheable:
        runtime.cache.put(key, result, ttl)
        logger.info("cache miss: %s", entry.upstream_name)
    elif empty:
        logger.info("not cached (empty result): %s", entry.upstream_name)
    else:
        logger.info("not cached (unsuccessful result): %s", entry.upstream_name)
    annotations = (
        runtime.config.annotations_for(entry.upstream_name) if cacheable else {}
    )
    return attach_meta(result, "miss", elapsed_ms, annotations)


def create_server(config: ProxyConfig, runtime: ProxyRuntime) -> Server:
    server: Server = Server(config.name, version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [entry.tool for entry in runtime.registry.values()]

    # Register the call handler directly instead of using @server.call_tool().
    # The decorator re-validates structuredContent against the upstream
    # outputSchema, which would replace a valid upstream result with a local
    # validation error. A proxy must pass the result through untouched, so the
    # raw handler returns our CallToolResult as-is.
    async def call_tool_handler(request: types.CallToolRequest) -> types.ServerResult:
        try:
            result = await handle_call(
                runtime, request.params.name, request.params.arguments
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            logger.error("unexpected proxy error: %s", type(exc).__name__)
            result = _error_result("proxy_error", "unexpected proxy error")
        return types.ServerResult(result)

    server.request_handlers[types.CallToolRequest] = call_tool_handler
    return server


async def serve(config: ProxyConfig) -> int:
    async with UpstreamGateway(config.upstream) as gateway:
        registry, missing = build_registry(gateway.tools, config.allow, config.rename_prefix)
        for name in missing:
            logger.warning("allowlisted tool does not exist upstream: %s", name)

        runtime = ProxyRuntime(
            config=config,
            gateway=gateway,
            registry=registry,
            cache=ResultCache(config.cache),
            limiter=SlidingWindowLimiter(config.rate_limit),
        )
        server = create_server(config, runtime)
        init_options = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, init_options, raise_exceptions=False
            )
    return 0
