# X API Troubleshooting

Read this when:

- A tool returned `{"error": {"code": "missing_key", ...}}` and you need to tell the user how to fix it.
- A tool returned `auth_failed`, `forbidden`, `rate_limited`, `budget_exhausted`, `http_error`, `not_found`, `network_error`, `malformed_response` or `invalid_argument` and you are not sure what to do next.
- The user asks "how do I set up X" or "where does the token come from".
- A query that used to work now costs more than expected, or the daily budget ran out mid-research.

## First-time setup — a bearer token provisioned by the operator

The X tools are read-only and use app-only authentication (a Bearer Token). The token is **server-side**: the agent never sees it, never passes it as an argument, and never writes it anywhere.

### Step 1 — Create the X app (one-time, user or operator)

1. Go to <https://console.x.com/> with an X account.
2. Accept the developer terms if prompted.
3. Create a **Project** and an **App** inside it.
4. Note the plan and its pricing in the Developer Console; X API is **pay-per-use**, and the console is the only authoritative price list.

### Step 2 — Generate the Bearer Token

1. Open the App → **Keys and tokens**.
2. Under **Bearer Token**, generate (or regenerate) the token.
3. Copy it once; X does not show it again.

> Regenerating invalidates the previous token. Every session using the old one will start returning `auth_failed` until the new value is installed.

### Step 3 — Install it without exposing it

The operator installs the token through the repository's key installer, which reads a local keys file and writes only the recognized names (it prints lengths, not values):

```bash
python3 scripts/install-keys.py /path/to/keys.txt
```

The X server reads `X_BEARER_TOKEN` from the process environment, then from the dotenv file `DSH_FINANCE_SECRETS` points at, then from `<repo>/config/secrets.env`. After installing or rotating the key, **restart the X server**; a running process keeps its old environment.

Do not ask the user to paste the token into the conversation. Do not read `config/secrets.env` yourself, and never print the value or its prefix.

### Step 4 — Verify through a tool call

The cheapest verification is a counts query, which costs one resource:

```text
x_counts_recent(query="$SPY", granularity="day")
```

`ok: true` means the key works. `missing_key` means the server started without it; `auth_failed` means the key is present but rejected.

## Error playbook

Each tool returns `{"ok": false, "error": {"code", "message"}}` on failure and never raises. Match the `code` to the row below.

### missing_key

```json
{"ok": false, "status": "error", "error": {"code": "missing_key", "message": "X_BEARER_TOKEN is not set; ..."}}
```

**Meaning:** the server started with no token in its environment or secrets file.

**What to do:** stop trying. Tell the user the operator needs to install `X_BEARER_TOKEN` with `scripts/install-keys.py` and restart the server. Do not scrape x.com, do not proxy through another site, and do not retry in a loop.

### auth_failed (401)

**Meaning:** a token exists but X rejected it. Usual causes: it was regenerated in the console while the server kept the old value; it was copied with whitespace or a `Bearer ` prefix; it is the wrong token type (an OAuth 1.0a user token rather than an app-only bearer token).

**What to do:** surface the status, ask the operator to install the current token and restart, and retry at most once on the same token. Do not regenerate the user's token on their behalf.

### forbidden (403)

**Meaning:** the token is valid but the plan does not include the endpoint, or the app lacks access to it.

**What to do:** this tool set only calls recent search, post lookup, user lookup, user posts and recent counts. There is **no full-archive endpoint** to fall back from, so a 403 here is a plan or app-permission problem: tell the user to confirm the plan and endpoint access in the Developer Console. Fall back to web_search or tavily_search for older material and label it.

### rate_limited (429, or a local limit)

```json
{"ok": false, "error": {"code": "rate_limited", "message": "..."},
 "data": {"retry_after_seconds": 47, "reset_at_epoch": 1777777760}}
```

**Meaning:** the local token bucket (a 30-call burst, one refill per 30 seconds by default) or X's own limit was hit. A local limit returns only `retry_after_seconds`; an upstream 429 also returns `reset_at_epoch`. The tool does **not** retry automatically.

**What to do:**

- `retry_after_seconds` ≤ ~60: wait that long, then retry once.
- `retry_after_seconds` > 60 or absent: stop and tell the user when the limit resets (`reset_at_epoch`).
- Narrow the query (`start_time`/`end_time`, fewer pages, lower `max_results`) to cut request volume.
- Never run a retry loop around search.

### budget_exhausted

```json
{"ok": false, "error": {"code": "budget_exhausted", "message": "daily X read budget exhausted ..."},
 "data": {"budget": {"used_today": 500, "remaining": 0}, "reset_at": "...", "reset_at_epoch": 1777777760}}
```

**Meaning:** the local daily cap (`X_DAILY_POST_BUDGET`, default 500 posts) is used up. This is a spending guard, not an X error.

**What to do:** stop. Report `used_today` and `reset_at`. Either wait for the local day to roll over, or ask the operator whether to raise the cap. Do not work around it with a second process, a different state file or unauthenticated scraping.

### http_error (400 / 404 / 5xx)

**Meaning:** X returned a non-2xx that is not 401/403/429.

**What to do:**

- **400:** inspect `error.message`; usually an unsupported operator, an over-length query (512 characters) or a timestamp outside the seven-day window. Fix the query and retry once.
- **404:** already mapped to `not_found` before it reaches this code; handle it there.
- **5xx:** retry once after 5–10 seconds. If it persists, tell the user the X API is unhealthy and stop.

### not_found

**Meaning:** the post or user is deleted, protected, suspended or never existed.

**What to do:** move on. If the user asked about that specific account or post, say it is unavailable and note the retrieval attempt.

### network_error

**Meaning:** DNS, TCP or TLS failure before X responded. The tool only reports the exception class, not the raw string.

**What to do:** retry once, then stop and say the session cannot reach `api.x.com`.

### malformed_response

**Meaning:** X returned 2xx with a body that is not JSON or not the expected shape (rare).

**What to do:** retry once; if it recurs, treat it as a transient X-side issue and stop.

### invalid_argument

**Meaning:** the tool rejected the arguments before making a request, so **nothing was billed**.

| Message | Cause | Fix |
|---|---|---|
| `query must be a non-empty string of at most 512 characters` | Empty query or over 512 chars | Shorten it; split an `OR` chain into calls |
| `max_results must be an integer between 10 and 100` | Search outside 10–100 | Use at least 10; slice the list if you need fewer |
| `max_results must be an integer between 5 and 100` | User posts outside 5–100 | Use 5 minimum for a user timeline |
| `start_time must be within the last 7 days` | Timestamp older than the recent window | Move the window forward, or use web_search for older material |
| `start_time must include a timezone` | Naive timestamp | Use `2026-11-02T00:00:00Z` or an explicit offset |
| `start_time must not be after end_time` | Reversed window | Swap them |
| `tweet_id must be a string of 1 to 25 digits` | A URL or non-digit id | Take the trailing digits from `https://x.com/user/status/<id>` |
| `user_id must be a string of 1 to 25 digits` | Passed a handle to `x_user_posts` | Resolve the handle with `x_get_user` first |
| `username must be a string of 1 to 15 letters, digits or underscores` | `@` in the middle, spaces, or too long | Strip the `@`; keep 1–15 characters |
| `pagination token must be a string of 1 to 1024 characters` | A token was truncated or copied with whitespace | Copy `data.next_token` exactly, or restart from page 1 |
| `granularity must be minute, hour or day` | Typo | Use one of the three |
| `start_time must not be in the future` | Timestamp ahead of UTC now | Fix the clock or the input |

### internal_error

**Meaning:** an unexpected server-side failure, not an upstream X response.

**What to do:** retry once. If it persists, tell the operator the X server is unhealthy and stop.

## What not to do

- Don't ask for, print, log or store the token. Not in code, not in comments, not in a chat reply.
- Don't regenerate the user's token on their behalf — it is their console.
- Don't scrape x.com with the scrape tools or web_fetch as a workaround when the key is the blocker; ask the operator to install the key first, and otherwise use a search service that indexes public posts.
- Don't loop on 429 or 5xx, and don't spread a budget across processes to evade the daily cap.
- Don't present a post count as a population estimate. The recent search endpoint returns a sample governed by X's own coverage and rate limits; say "posts returned for this query", not "all posts".
