# mcp-filter-proxy

A small, dependency-light **stdio MCP proxy**. It connects to exactly one upstream
stdio MCP server, exposes only the tools named in an allowlist, prefixes their
names, and adds result caching, a sliding-window rate limit and a uniform `meta`
block. Everything else is passed through untouched.

Each Chives gateway declares the read-only tools available to its researchers.

## Install

```bash
cd packages/mcp-filter-proxy
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[test]"
```

The package declares only `mcp` and `pyyaml`; the test extra adds `pytest` and
`pytest-asyncio`.

## Usage

```bash
# Run as a stdio MCP server (stdout carries the MCP protocol)
.venv/bin/python -m mcp_filter_proxy --config examples/cn-data.yaml

# Inspect the wiring without entering the server loop
.venv/bin/python -m mcp_filter_proxy --config examples/cn-data.yaml --check
```

`--check` connects to the upstream, prints exactly one JSON line to stdout and
exits with code 0:

```json
{"upstream_total": 82, "exposed": ["cn_search_symbol", "cn_get_fund_flow"], "missing": []}
```

`exposed` uses the prefixed names; `missing` lists allowlist entries that do not
exist upstream (a warning is also written to stderr).

## Configuration

```yaml
name: cn_data                 # MCP server name shown to clients
upstream:
  command: /abs/path/to/server      # upstream stdio MCP executable
  args: []
  cwd: null                         # optional working directory
  inherit_env: false                # true: inherit the proxy's environment
  env:                              # ${VAR} is expanded from the proxy's environment
    SOME_KEY: ${SOME_KEY}
allow: [search_symbol, get_fund_flow]   # exact upstream names, must not be empty
rename_prefix: "cn_"                    # exposed name = prefix + upstream name
cache:
  max_entries: 500
  ttl_seconds:
    default: 60
    get_fund_flow: 300                  # keyed by the *upstream* tool name
rate_limit:
  max_calls_per_minute: 60
```

Details:

- `allow` must be a non-empty list; duplicates are collapsed. An empty list
  exits with code **2** before any upstream connection is attempted.
- Each `${VAR}` in `upstream.env` values is replaced from the proxy process
  environment. An unset variable exits with code **2** and an error that names
  the variable (never its value).
- `inherit_env: false` gives the upstream **only** `PATH`, `HOME` and the
  variables listed under `env`. The proxy execs the upstream through
  `env -i` so the MCP transport's default variables cannot leak in.
  `inherit_env: true` starts from the proxy's full environment and then applies
  `env` on top.
- `cache.max_entries` defaults to 500, `cache.ttl_seconds.default` to 60, and
  `rate_limit.max_calls_per_minute` to 60.

## Response checks (`checks`)

Optional. Without this section the proxy behaves exactly as before.

```yaml
checks:
  - tool: get_market_data              # upstream tool name, not the exposed/renamed one
    type: bars_within_requested_dates  # or non_empty_result (see below)
    start_arg: start_date              # argument holding the inclusive start date
    end_arg: end_date                  # argument holding the inclusive end date
    hint: "1m only returns today; use the minute-bar tool."  # optional
    date_field: trade_date             # field on each row holding the date/time
```

`bars_within_requested_dates` requires `start_arg`, `end_arg` and `date_field`.
`non_empty_result` requires none of them.

For a single-text-block JSON object whose top-level values are row lists (for
example `{"002553.SZ": [{"trade_date": "2026-10-30T09:31:00", ...}]}`), every
row's `date_field` is reduced to its first 10 characters — so both
`2026-10-30T00:00:00` and `2026-10-30 09:31:00` work — and must fall inside
`[start_arg, end_arg]` inclusive. If any row falls outside, the proxy returns
`isError: true` and this JSON, and does not cache it:

```json
{"ok": false, "status": "error", "error": {"code": "date_range_mismatch", "message": "...", "requested": ["2026-10-30", "2026-10-30"], "returned_dates": ["2026-10-30", "2026-11-02"], "returned_count": 2, "hint": "..."}}
```

`hint` is optional. When configured it must be a non-empty string of at most
300 characters; on a failed check that exact string is added to the error
object. Without `hint` the field is absent. `returned_count` is always present
on a mismatch and counts the returned rows that carried a usable `date_field`.

Rows without a usable `date_field` are ignored. An empty row list, a missing
`start_arg`/`end_arg`, or a payload that is not of the shape above is passed
through without validation.

### `non_empty_result`

Turns a silently empty successful response into an explicit error. `tool` is
either one upstream tool name or `"*"` (all allowlisted tools). A successful
response fails the check when any of these holds:

- the joined text content is empty or only whitespace;
- the text parses to a JSON object and its `results` key is an empty array;
- the text parses to a JSON array of length 0.

The replacement result is `isError: true` with:

```json
{"ok": false, "status": "error", "error": {"code": "empty_result", "message": "...", "tool": "get_quotes", "hint": "..."}}
```

`tool` is the upstream name and `hint` is present only when configured. Empty
responses are never cached, even when they are allowed, so a later call after
the upstream recovers can return real data. `allow_empty` is an optional,
non-empty list of upstream tool names that are allowed to be empty; it is only
valid when `tool` is `"*"`, and every name must also appear in `allow`.

```yaml
checks:
  - tool: "*"
    type: non_empty_result
    hint: "upstream returned empty; it may be rate limited, retry later."
    allow_empty: [get_dividends]      # a symbol may legitimately have none
```

Invalid response configuration exits with code **2** before any upstream
connection: an unknown check `type`; a `bars_within_requested_dates` check
missing one of `start_arg`, `end_arg`, `date_field`; `"*"` used with any type
other than `non_empty_result`; an invalid `hint` (not a string, empty, or
longer than 300 characters); an invalid `allow_empty` (not a non-empty list of
strings, used with a non-wildcard `tool` or another check type, or naming a
tool not in `allow`); or a `checks`/`annotations` entry whose tool is not in
`allow`.

## Unit annotations (`annotations`)

Optional. Without this section the proxy behaves exactly as before.

```yaml
annotations:
  get_market_data:
    units:
      volume: "lots (1 lot = 100 shares)"
```

For a successful single-text-block JSON object, the mapping under
`annotations.<upstream tool>` is merged into the proxy metadata (next to
`cache`, `latency_ms` and `proxy`). If the upstream object already has a `meta`
key the merge goes into `_proxy_meta`, exactly like the existing metadata rule,
so upstream `meta` is never overwritten. Annotations are also present on cache
hits.

## Behaviour

1. **Tool list.** Only allowlisted tools that exist upstream are listed.
   `inputSchema`, `description`, `outputSchema`, annotations and other tool
   metadata are copied verbatim; only `name` becomes `rename_prefix + name`.
2. **Refusals.** A call whose name is not one of the exposed names returns
   `isError: true` and is never forwarded upstream. This includes the bare
   upstream name when a prefix is configured.
3. **Results.** Upstream content blocks, `structuredContent` and `isError` are
   returned as-is. The one exception below: a result consisting of exactly one
   text block that parses to a JSON **object** gets a metadata field.
4. **Meta.** For that JSON object the proxy adds

   ```json
   {"meta": {"cache": "hit" | "miss", "latency_ms": 12, "proxy": "mcp-filter-proxy"}}
   ```

   If the upstream object already has a `meta` key, the proxy leaves it alone
   and writes its own data under `_proxy_meta`. Non-JSON text, non-object JSON,
   and multi-block results are returned unchanged. `latency_ms` is the measured
   wall-clock time of this call (including cache lookup), rounded to an integer.
5. **Cache.** Key = `(upstream tool name, canonical JSON of arguments with
   sorted keys)`. Only successful results are stored: `isError` must be false,
   and when the JSON object has an `ok` field it must be truthy. TTL comes from
   the upstream tool name, falling back to `default`; a TTL of 0 disables
   caching for that tool. When `max_entries` is exceeded the **oldest inserted**
   entry is evicted. Cache hits do not consume rate-limit budget and report
   `meta.cache == "hit"`.
6. **Rate limit.** A rolling 60-second window over all upstream calls (cache
   hits excluded). When full, the proxy returns `isError: true` with exactly

   ```json
   {"ok": false, "status": "error", "error": {"code": "rate_limited", "message": "..."}}
   ```

   and does not call upstream.
7. **Startup.** Empty `allow` and missing `${VAR}` exit with code 2. An
   allowlist entry that does not exist upstream is only a stderr warning; the
   remaining tools are exposed.
8. **Upstream crash.** After the upstream exits, the call in flight and every
   later call return `isError: true` with an `upstream_unavailable` error. The
   proxy process keeps serving `tools/list` and stays alive; it does not restart
   the upstream (single-upstream, no-retry by design).
9. **Logging.** All proxy logs go to stderr. stdout is reserved for the MCP
   protocol. Log lines contain tool names and cache outcomes, never arguments,
   environment variables or their values.

## Known limitations

- Exactly one upstream, no failover, no retry and no automatic restart.
- The tool list is a snapshot taken at startup; later upstream changes are not
  refreshed.
- The cache is per-process, in memory only, and is not shared or persisted.
- Rate limiting is per proxy instance.
- The proxy does not validate arguments locally (`validate_input=False`); it
  relies on the upstream schema and returns the upstream error.
- Only stdio upstreams; HTTP/SSE upstreams are out of scope.
- `env -i` requires a POSIX `env` binary (macOS/Linux).

## Tests

```bash
.venv/bin/python -m pytest -q
```

The suite starts a fake upstream MCP server (`tests/fake_upstream.py`) over
stdio. No network and no real market data are involved.
