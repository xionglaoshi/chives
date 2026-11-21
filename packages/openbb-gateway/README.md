# openbb-gateway

An install-only package that provides the Python 3.12 virtualenv for the
[OpenBB MCP server](https://pypi.org/project/openbb-mcp-server/), plus a few
developer probes. It contains no gateway code of its own: the MCP filtering,
allowlist, caching, rate limiting and `ob_` renaming are done by
`packages/mcp-filter-proxy`, configured by `gateways/openbb/config.yaml`.

## Install

```bash
cd packages/openbb-gateway
uv venv --python 3.12 .venv
UV_CACHE_DIR="$PWD/.uv-cache" uv pip install --python .venv/bin/python \
  openbb==5.0.0 openbb-mcp-server==2.0.1 openbb-yfinance openbb-sec openbb-equity
```

`requirements.lock` is the exact `uv pip freeze` result (Python 3.12.12,
macOS arm64). Recreate an identical environment with:

```bash
uv pip install --python .venv/bin/python -r requirements.lock
```

`openbb==5.0.0` is a meta-package: it pulls provider extensions that are not
used here (for example `openbb-fred`, which needs `FRED_API_KEY`). **No
credential is configured anywhere**; key-requiring domains are marked
`needs_key` in `docs/openbb-tool-matrix.md` and are not exposed by the gateway.

## Run

Everything OpenBB writes at runtime must stay inside the repository. The
gateway config starts the upstream with an isolated environment
(`inherit_env: false`) and:

```yaml
env:
  HOME: /Users/xiong/.chives/packages/openbb-gateway/.home
```

so OpenBB creates `packages/openbb-gateway/.home/.openbb_platform`, never
`~/.openbb_platform`. `.home/` is git-ignored. Do not start `openbb-mcp`
without setting `HOME` this way.

Start the gateway through the proxy:

```bash
cd /Users/xiong/.chives
packages/mcp-filter-proxy/.venv/bin/python -m mcp_filter_proxy \
  --config gateways/openbb/config.yaml
```

Wiring check (connects upstream, lists the exposed tools, exits):

```bash
packages/mcp-filter-proxy/.venv/bin/python -m mcp_filter_proxy \
  --config gateways/openbb/config.yaml --check
# {"upstream_total": 393, "exposed": ["ob_equity_price_historical", ...], "missing": []}
```

The overlay `overlays/openbb.cordis.yml` starts exactly that command as the
`openbb` MCP server (`id: fin-openbb`). It contains no secrets.

## Exposure strategy

The OpenBB MCP server is **not** in discovery mode by default. Without a filter
it exposes every route of every installed extension: 1150 tools in this
environment, which would flood an agent's context. It also has an optional
`--tool-discovery` mode (14 meta-tools: `available_categories`,
`available_tools`, `search_tools`, `call_tool`, ...), but that is a two-step
interface and hides concrete schemas.

This gateway uses the middle ground:

1. `--allowed-categories equity,sec,news,yfinance,technical,nasdaq,federal_reserve,famafrench`
   cuts the upstream to 393 routes at registration time.
2. The proxy `allow:` list exposes only **59** concrete, read-only tools
   (`ob_` + the upstream name). `missing: []` in `--check` confirms that all 59
   exist.

The agent sees 59 explicit tools with schemas, not 393 and not 1150. There is
no admin/skill/prompt tool in the allowlist.

Provider selection is explicit in tool arguments. Free/keyless providers used
and verified here: `yfinance`, `nasdaq`, `sec`, `federal_reserve`,
`famafrench`, `finra`, `tmx`. Some routes accept only one provider, for example
`equity_fundamental_ratios` is `provider=nasdaq` only.

## Known limitations

- **Not every OpenBB tool works without a key.** FRED (`fred_*`) fails with
  `Missing credential 'fred_api_key'`; those domains are marked `needs_key` and
  are not exposed.
- **Yahoo Finance rate limiting.** Many `yfinance_*` and `equity_*` calls go to
  Yahoo. During development a burst of probes triggered
  `YFRateLimitError: Too Many Requests`; affected tools then return
  `isError: false` with `results: []` (and sometimes a `warnings` entry), i.e.
  a *silent empty result* rather than an error. The gateway caches results
  (60 s default, 1 h for fundamentals), but an agent must still check
  `results` and `warnings`; do not treat an empty list as "no such data".
  Prefer `provider=nasdaq` or `provider=sec` for prices/statements when Yahoo
  is throttled.
- **Empty responses without an error are common.** `equity_ownership_form_13f`
  and `yfinance_industry_overview` were observed returning a successful call
  with an empty text block (the latter works when both `sector` and `industry`
  are supplied). `equity_calendar_dividend` (nasdaq) returned `isError: true`
  with an empty message.
- **Provider-specific breakage.** `equity_search` with `provider=nasdaq`
  raises an internal pandas error; `provider=sec` works. `sec_sic_search`
  raises `'SIC Code'`. `equity_shorts_fails_to_deliver` (provider=sec) gets
  HTTP 404 for a future SEC ZIP file. These tools are not exposed.
- **Technical indicators take data, not a ticker.** `technical_rsi`,
  `technical_sma`, `technical_macd` require a `data` array of OHLCV rows; the
  agent must call `ob_equity_price_historical` first. `technical_indicators`
  is only a catalogue endpoint and rejects a body-less call.
- **Options chains are large.** `ob_nasdaq_options_chains` returned 3230 rows
  without `expiration`; pass `expiration` (188 rows for one expiry) to keep
  responses manageable. Delayed Nasdaq data.
- **Upstream MCP is newer than the proxy client.** `openbb-mcp-server 2.0.1`
  installs `mcp 2.3.0`/`fastmcp 4.1.5` in this venv, while
  `mcp-filter-proxy` uses `mcp 1.30.0`. The stdio protocol interoperates, but
  the two Python APIs differ (`is_error` vs `isError`); developer probes here
  handle both.
- **Startup is slow.** Importing every OpenBB extension takes about 30 s; the
  proxy has no startup timeout, and the client's `initialize` needs a generous
  timeout (the acceptance check uses 120 s).
- **Cache and rate limit are per proxy process** (max 500 entries, 24 calls per
  rolling minute), as documented by `packages/mcp-filter-proxy`.

## Developer probes

These are not used by the gateway:

- `call_batch.py` — run `_work/calls.json` through one session and append
  compact results to `_work/results.jsonl`.
- `verify_via_proxy.py` — call role tools through the proxy; prints row counts
  and the proxy `meta` block (cache/annotations).

They write only under `packages/openbb-gateway/_work/` and use
`HOME=packages/openbb-gateway/.home`.
