# OpenBB gateway

Configuration-only gateway: `packages/mcp-filter-proxy` exposes 59 read-only
OpenBB tools under the `ob_` prefix, using `config.yaml` in this directory. The
upstream is the OpenBB MCP server restricted to eight keyless categories; see
`packages/openbb-gateway/README.md` for installation and the upstream details.

Run it through the proxy:

```bash
packages/mcp-filter-proxy/.venv/bin/python -m mcp_filter_proxy \
  --config gateways/openbb/config.yaml
```

Wiring check:

```bash
packages/mcp-filter-proxy/.venv/bin/python -m mcp_filter_proxy \
  --config gateways/openbb/config.yaml --check
```

## Empty-result guard

Yahoo-backed tools can return `isError: false` with `results: []` or with no
text at all when Yahoo rate-limits a request. Treating that as "no data" is
wrong, so the config enables the proxy's `non_empty_result` check for every
exposed tool:

```yaml
checks:
  - tool: "*"
    type: non_empty_result
    hint: "上游返回空，可能是 Yahoo 限流或该 provider 没有这个标的的数据；可稍后重试，或在支持的情况下改用 provider=nasdaq / provider=sec"
```

An empty text block, whitespace-only text, `{"results": []}` or `[]` now
returns `isError: true` with `error.code == "empty_result"`, `error.tool` and
the Chinese `hint` above. Empty results are never cached.

`equity_calendar_splits` is in `allow_empty`: a date range with no splits
legitimately returns an empty list (verified with a weekend range and
`provider=nasdaq` on 2026-11-02).

## Tool matrix

Per-tool status, reproducible `recommended_call` arguments, data-source backing
and stability grading are recorded in `docs/openbb-tool-matrix.md`.
