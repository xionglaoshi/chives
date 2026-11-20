"""Shared helpers for the mcp-filter-proxy test suite."""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, TextIO

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PKG_ROOT = Path(__file__).resolve().parents[1]
FAKE_UPSTREAM = Path(__file__).resolve().with_name("fake_upstream.py")


def make_config(
    tmp_path: Path,
    *,
    allow: list[str],
    prefix: str = "p_",
    cache: dict[str, Any] | None = None,
    rate: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    inherit_env: bool = False,
    name: str = "test-proxy",
    checks: list[dict[str, Any]] | None = None,
    annotations: dict[str, Any] | None = None,
) -> Path:
    data: dict[str, Any] = {
        "name": name,
        "upstream": {
            "command": sys.executable,
            "args": [str(FAKE_UPSTREAM)],
            "cwd": str(PKG_ROOT),
            "inherit_env": inherit_env,
            "env": env or {},
        },
        "allow": allow,
        "rename_prefix": prefix,
    }
    if cache is not None:
        data["cache"] = cache
    if rate is not None:
        data["rate_limit"] = rate
    if checks is not None:
        data["checks"] = checks
    if annotations is not None:
        data["annotations"] = annotations
    path = tmp_path / "proxy.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@asynccontextmanager
async def proxy_session(
    config_path: Path,
    *,
    errlog: TextIO | None = None,
    env_extra: dict[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_filter_proxy", "--config", str(config_path)],
        cwd=str(PKG_ROOT),
        env=env,
    )
    async with stdio_client(params, errlog=errlog or sys.stderr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def result_text(result: Any) -> str:
    return "".join(
        block.text for block in result.content if getattr(block, "text", None) is not None
    )


def result_json(result: Any) -> dict[str, Any]:
    return json.loads(result_text(result))
