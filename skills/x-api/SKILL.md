---
name: x-api
description: "Search X (Twitter) posts from the last seven days, pull user profiles, hydrate specific posts, read a user's recent timeline, and size a query before spending on it, for sentiment, news and event research. Triggers on X, Twitter, tweets about, sentiment on, what are people saying about, recent posts about, or any request to read public X content."
metadata:
  maintainer: Chives
---

# X (Twitter) API

Read-only access to X content through five MCP tools. Use it for sentiment on tickers, executive announcements, launches, event tracking and qualitative research alongside filings and market data.

> **Not for single-post URL lookups.** If the user hands you a specific X post URL and just wants its text or context, use web_fetch on the URL — no API budget, no rate limit. Reach for this skill when the task is **search, aggregation, or thread traversal**.

## Auth

The tools take no token argument. The server reads `X_BEARER_TOKEN` from the process environment or the secrets file the operator provisioned, and injects it only in the upstream request header.

- If a call returns `missing_key`, the session has no key. Stop and tell the user: the operator needs to install `X_BEARER_TOKEN` (the repository's `scripts/install-keys.py` writes it) and restart the X server.
- Never ask the user to paste the token into chat, never print it, never write it to a file, and never put it in a query or URL.
- A regenerated token invalidates the old one; only the operator should regenerate it.

## Pricing and budget

X API access is **pay-per-use**, not a free tier. Read pricing is per returned resource, roughly **$0.005 per post** and **$0.01 per user**; the authoritative number is what the user sees in the X Developer Console, so quote the order of magnitude and point at the console rather than treating these as fixed.

Every successful response carries `data.budget`:

```json
{"used_today": 11, "remaining": 489}
```

The server reserves budget before each upstream request and settles it on the resources actually returned. The default daily cap is 500 posts (`X_DAILY_POST_BUDGET`), and exhausting it returns `budget_exhausted` with `reset_at`.

Cheap-first discipline:

1. Size the query with `x_counts_recent` (one unit of the local budget) before pulling posts.
2. Start `x_search_recent` at `max_results=10`; raise it only when the first page is on-topic.
3. Page with `next_token` only while the question is still open; stop when the marginal post stops adding information.
4. Check `data.budget` after each call and stop before `remaining` reaches zero.

## Tools at a glance

The primary use case is **search**; `x_search_recent` and `x_counts_recent` are what you reach for most.

| Tool | Use for | Page size | Notes |
|---|---|---|---|
| `x_search_recent` | Posts from the last 7 days | default 10, max 100 | Default choice. Query ≤512 chars. Supports `next_token`, `start_time`, `end_time`. |
| `x_counts_recent` | Post volume for a query, bucketed | one resource | `granularity` = `minute`, `hour` or `day`. Use it to size a search before paying for posts. |
| `x_get_post` | Hydrate one post by id | one resource | Mainly to get its `conversation_id` before a thread query. |
| `x_get_user` | A user profile and metrics | one resource | Handle without `@`, ≤15 chars; a leading `@` is accepted and stripped. |
| `x_user_posts` | A user's recent posts | default 10, max 100 (minimum 5) | Needs the numeric `user_id` from `x_get_user`, not the handle. |

**There is no full-archive search and no dedicated conversation endpoint.** `x_search_recent` covers the last 7 days only. For a thread, hydrate the root with `x_get_post`, then search `conversation_id:<id>` in `x_search_recent`; the root itself is not returned by that search. A thread older than 7 days is out of reach for this tool set — use web_search or tavily_search and label the source and its date.

## Examples

### Recent sentiment on a ticker

```text
counts = x_counts_recent(query="$NVDA -is:retweet lang:en", granularity="day")
res = x_search_recent(query="$NVDA -is:retweet lang:en", max_results=100)
posts = res["data"]["results"]
users = {u["id"]: u for u in res["data"]["users"]}
posts.sort(key=lambda p: p.get("public_metrics", {}).get("impression_count", 0), reverse=True)
for p in posts[:10]:
    author = users.get(p.get("author_id"), {})
    print(author.get("username", p.get("author_id")), p.get("public_metrics", {}).get("like_count"), p.get("text", "")[:140])
```

### Reaction to an event inside the seven-day window

```text
res = x_search_recent(
    query="$TSLA earnings -is:retweet lang:en",
    max_results=100,
    start_time="2026-10-28T00:00:00Z",
    end_time="2026-11-02T00:00:00Z",
)
```

`start_time` and `end_time` must carry a timezone and must fall inside the last 7 days; a timestamp older than that is rejected as `invalid_argument` without spending budget.

### Full thread on a specific post

```text
root = x_get_post(tweet_id="1700000000000000001")
root_post = root["data"]["post"]
thread = x_search_recent(
    query=f"conversation_id:{root_post['conversation_id']}",
    max_results=100,
)
all_posts = [root_post, *thread["data"]["results"]]
```

### Paginate through a large result

```text
posts, token = [], None
while len(posts) < 300:
    res = x_search_recent(query="from:FedSpeakers", max_results=100, next_token=token)
    if not res["ok"]:
        break
    posts.extend(res["data"]["results"])
    token = res["data"]["next_token"]
    if not token:
        break
```

Stop on the first error rather than retrying in the loop. Do not cache `next_token` across sessions: cursors expire.

## Post and user shape

Each post has `id`, `text`, `created_at`, `author_id`, `public_metrics`, `lang`, `conversation_id` and, when present upstream, `entities`. **There is no nested `author` object**: authors come back in a separate `data.users` list, and you join on `author_id` → `users[].id`. A missing user means the author was not expanded (suspended, deleted or withheld), so branch before reading a username.

`text` is capped at 4,000 characters; when it is cut, the row carries `truncated: true`. `public_metrics` keeps only integer fields and may omit any of them, so use `.get("like_count", 0)` rather than indexing.

Full per-tool response shapes, the envelope and the input constraints: [reference.md](./reference.md).

## Query syntax

`$TSLA` (cashtag), `#hashtag`, `from:elonmusk`, `to:@SEC_News`, `-is:retweet`, `is:verified`, `has:links`, `has:media`, `lang:en`, `"exact phrase"`, parentheses plus `OR` for alternation, and `conversation_id:<numeric id>` for a thread. Queries are limited to 512 characters. Full operator list: <https://docs.x.com/x-api/posts/search/introduction>.

## Errors

Every tool returns an envelope; errors are returned, never raised. Check `ok` and `error` before touching `data`, and read [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for the per-code playbook.

The codes you will see: `missing_key`, `invalid_argument`, `auth_failed`, `forbidden`, `not_found`, `rate_limited`, `budget_exhausted`, `http_error`, `network_error`, `malformed_response`, `internal_error`.

## Do / Don't

- **Do** check `data.budget` and size the query with `x_counts_recent` before a large pull.
- **Do** cross-reference X chatter with the price series (`fmp_get_historical_prices` for a US listing, `market_quote` or `market_bars` for an A-share) and with the official disclosure (`ob_sec_company_filings` for a US filing, `company_announcements` for an A-share announcement).
- **Do** label the retrieval time on every quoted post; the recent window moves.
- **Don't** hardcode or log the token. Ever.
- **Don't** cache `next_token` across sessions — cursors can expire.
- **Don't** assume every `author_id` resolves to a user; check `data.users` before reading a handle.
- **Don't** retry a 429 in a loop, and don't scrape x.com as a workaround for a missing or limited key.

## Related

- fmp_get_historical_prices — cross-reference X sentiment with US price action
- ob_sec_company_filings — pair chatter with the official US disclosure
- market_quote / market_bars — A-share price context (retain the units of the returned fields)
- company_announcements — A-share announcement list for the official version of a claim
- tavily_search / web_search — broader news search, and the fallback for anything older than the seven-day window
- tavily_extract — readable text of a public page linked from a post
