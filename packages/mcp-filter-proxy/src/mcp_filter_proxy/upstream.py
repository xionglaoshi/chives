"""Lifecycle of the single upstream stdio MCP server and transparent calls to it."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from contextlib import AsyncExitStack
from typing import Any

import mcp.types as types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from mcp_filter_proxy.config import UpstreamConfig

logger = logging.getLogger(__name__)

START_TIMEOUT_SECONDS = 120.0
CALL_TIMEOUT_SECONDS = 120.0
_ENV_BIN = shutil.which("env") or "/usr/bin/env"


class UpstreamUnavailable(RuntimeError):
    """The upstream process is not connected (or could not be started)."""


def _looks_disconnected(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return any(_looks_disconnected(child) for child in exc.exceptions)
    if isinstance(exc, McpError):
        return getattr(exc.error, "code", None) == types.CONNECTION_CLOSED
    return type(exc).__name__ in {"ClosedResourceError", "BrokenResourceError", "EndOfStream"}


def _redact(text: str, config: UpstreamConfig) -> str:
    for value in config.env.values():
        if value:
            text = text.replace(value, "***")
    return text


def build_server_parameters(config: UpstreamConfig) -> StdioServerParameters:
    env = {key: value for key, value in os.environ.items()}
    if config.inherit_env:
        env.update(config.env)
        return StdioServerParameters(
            command=config.command,
            args=list(config.args),
            cwd=config.cwd,
            env=env,
        )

    # `inherit_env: false` promises only PATH, HOME and the configured variables.
    # The MCP stdio client always adds a handful of safe defaults, so `env -i`
    # clears the environment right before exec and hands the upstream exactly
    # the documented set.
    child_env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
    }
    child_env.update(config.env)
    assignments = [f"{key}={value}" for key, value in child_env.items()]
    return StdioServerParameters(
        command=_ENV_BIN,
        args=["-i", *assignments, config.command, *config.args],
        cwd=config.cwd,
        env={"PATH": child_env["PATH"], "HOME": child_env["HOME"]},
    )


class UpstreamGateway:
    """Owns the upstream client session for the lifetime of the proxy."""

    def __init__(self, config: UpstreamConfig) -> None:
        self._config = config
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: tuple[types.Tool, ...] = ()
        self._dead_reason: str | None = None

    @property
    def tools(self) -> tuple[types.Tool, ...]:
        return self._tools

    @property
    def dead(self) -> bool:
        return self._dead_reason is not None

    async def __aenter__(self) -> "UpstreamGateway":
        await self._open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _open(self) -> None:
        self._stack = AsyncExitStack()
        try:
            read_stream, write_stream = await self._stack.enter_async_context(
                stdio_client(build_server_parameters(self._config), errlog=sys.stderr)
            )
            self._session = await self._stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await asyncio.wait_for(self._session.initialize(), START_TIMEOUT_SECONDS)
            listed = await asyncio.wait_for(self._session.list_tools(), START_TIMEOUT_SECONDS)
            self._tools = tuple(listed.tools)
        except Exception as exc:
            await self.close()
            detail = _redact(f"{type(exc).__name__}: {exc}", self._config)
            raise UpstreamUnavailable(
                f"could not initialize upstream {self._config.command!r}: {detail}"
            ) from exc

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:  # pragma: no cover - shutdown best effort
                logger.debug("error while closing upstream session", exc_info=True)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if self._dead_reason is not None:
            raise UpstreamUnavailable(self._dead_reason)
        session = self._session
        if session is None:
            raise UpstreamUnavailable("upstream is not connected")

        try:
            return await asyncio.wait_for(
                session.call_tool(name, arguments), CALL_TIMEOUT_SECONDS
            )
        except Exception as exc:
            if _looks_disconnected(exc):
                self._dead_reason = "upstream process exited or closed the connection"
                logger.error("upstream disconnected while calling %s", name)
                raise UpstreamUnavailable(self._dead_reason) from exc
            raise
