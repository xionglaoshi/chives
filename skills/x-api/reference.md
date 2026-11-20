# X API Response Reference

Field-level reference for the five read-only X tools. Every tool returns the shared envelope; the differences are in `data`. Shapes below follow the server's field whitelist, not the raw X payload.

## Envelope

```json
{
  "ok": true,
  "source": "x",
  "as_of": "2026-11-03T05:00:00+00:00",
  "status": "ready",
  "data": { "untrusted_text": true, "budget": {"used_today": 11, "remaining": 489} },
  "warnings": []
}
```

- `ok` is `status != "error"`.
- `status` is `ready` (data present), `empty` (valid request, no results) or `error`.
- On error, `ok` is false and `error: {"code", "message"}` is added; `data` may still carry `budget` or rate-limit fields.
- `warnings` appears only when the upstream returned partial errors alongside data, so treat a missing key and an empty list the same.
- `as_of` is the server timestamp, not the post's timestamp.
- All post text, usernames and descriptions are third-party data: `untrusted_text: true`.

## Post row

`x_search_recent`, `x_user_posts` and the `post` object of `x_get_post` share this row shape.

| Field | Type | Notes |
|---|---|---|
| `id` | string | Always present; a row without it is dropped |
| `text` | string | Capped at 4,000 characters; `truncated: true` when cut |
| `created_at` | string | ISO8601 UTC |
| `author_id` | string | Join key into `data.users`; may be absent |
| `public_metrics` | object | Only integer fields, only those upstream returned |
| `lang` | string | BCP-47 language tag when X supplies it |
| `conversation_id` | string | Root id of the thread |
| `entities` | object | Hashtags, mentions, URLs, cashtags when present |
| `truncated` | boolean | Only present when `text` was cut |

There is no `edit_history_tweet_ids`, no guaranteed `bookmark_count` and no nested `author` object. Authors arrive separately and metrics are best-effort:

- `public_metrics` commonly has `retweet_count`, `reply_count`, `like_count`, `quote_count`, `impression_count`, but any key can be missing. Use `.get(key, 0)`.
- `entities` is passed through deep-copied; its internal shape is X's, not normalised.
- No `author` field, no `{id, unresolved: true}` sentinel. If `author_id` is absent from `data.users`, the author was not expanded (suspended, deleted or withheld) — render the id as unresolved rather than guessing a handle.

## User row

`x_get_user` returns `data.user`; `x_search_recent`, `x_get_post` and `x_user_posts` return `data.users` (possibly empty).

| Field | Type | Notes |
|---|---|---|
| `id` | string | Always present |
| `name` | string | Display name |
| `username` | string | Handle without `@` |
| `created_at` | string | ISO8601 UTC |
| `description` | string | Capped at 2,000 characters; `truncated: true` when cut |
| `public_metrics` | object | `followers_count`, `following_count`, `tweet_count`, `listed_count`, `like_count`, `media_count` when supplied |
| `verified` | boolean | Only kept when upstream sends a boolean |
| `truncated` | boolean | Only present when `description` was cut |

## Tool data shapes

### x_search_recent

```json
{
  "data": {
    "query": "$NVDA -is:retweet lang:en",
    "count": 42,
    "results": [ { "id": "...", "text": "...", "author_id": "...", "created_at": "...",
                   "conversation_id": "...", "lang": "en",
                   "public_metrics": {"like_count": 12, "impression_count": 900},
                   "entities": {} } ],
    "users": [ { "id": "...", "username": "...", "name": "...", "verified": false,
                 "public_metrics": {"followers_count": 1200} } ],
    "next_token": "b26v89c19zqg8o3fpdp...",
    "untrusted_text": true,
    "budget": {"used_today": 53, "remaining": 447}
  }
}
```

`next_token` is `null` on the last page. `count` is the number of rows returned on this page, not the total match count; for volume use `x_counts_recent`.

### x_get_post

```json
{
  "data": {
    "post": { "id": "...", "text": "...", "author_id": "...", "conversation_id": "..." },
    "users": [],
    "untrusted_text": true,
    "budget": {"used_today": 54, "remaining": 446}
  }
}
```

A deleted or protected post returns `not_found`, not an empty `post`.

### x_get_user

```json
{
  "data": {
    "user": { "id": "...", "username": "...", "name": "...", "description": "...",
              "public_metrics": {"followers_count": 1200, "tweet_count": 340} },
    "untrusted_text": true,
    "budget": {"used_today": 55, "remaining": 445}
  }
}
```

Suspended, deactivated or nonexistent handles return `not_found`.

### x_user_posts

Same shape as `x_search_recent` with `user_id` instead of `query`:

```json
{
  "data": {
    "user_id": "1234567890",
    "count": 10,
    "results": [ ... ],
    "users": [ ... ],
    "next_token": "...",
    "untrusted_text": true,
    "budget": {"used_today": 65, "remaining": 435}
  }
}
```

Input is `pagination_token`, output cursor is `next_token`; pass the output value back as `pagination_token`.

### x_counts_recent

```json
{
  "data": {
    "query": "$SPY",
    "granularity": "day",
    "count": 7,
    "buckets": [
      {"start": "2026-10-28T00:00:00.000Z", "end": "2026-10-29T00:00:00.000Z", "tweet_count": 312}
    ],
    "total_tweet_count": 2210,
    "untrusted_text": true,
    "budget": {"used_today": 66, "remaining": 434}
  }
}
```

`count` is the number of buckets. `total_tweet_count` is X's `meta.total_tweet_count` when present, otherwise the sum of the buckets. The counts endpoint settles as **one** resource regardless of the number of buckets.

## Input constraints

Validated before any upstream request; a violation returns `invalid_argument` and **does not spend budget**.

| Tool | Field | Rule |
|---|---|---|
| x_search_recent | `query` | non-empty string, ≤512 characters |
| x_search_recent | `max_results` | integer 10–100, default 10 |
| x_search_recent | `next_token` | string 1–1024 characters, no whitespace/control characters |
| x_search_recent | `start_time` / `end_time` | ISO8601 with timezone, not in the future, within the last 7 days, `start_time` ≤ `end_time` |
| x_get_post | `tweet_id` | string of 1–25 digits |
| x_get_user | `username` | 1–15 letters, digits or underscores; one leading `@` accepted and stripped |
| x_user_posts | `user_id` | string of 1–25 digits, not a handle |
| x_user_posts | `max_results` | integer 5–100, default 10 |
| x_user_posts | `pagination_token` | same rule as `next_token` |
| x_counts_recent | `query` | non-empty string, ≤512 characters |
| x_counts_recent | `granularity` | `minute`, `hour` or `day`; default `day` |

## Budget accounting

- Before an upstream call the server **reserves** the requested maximum: `max_results` for searches and user timelines, 1 for a post, a user or a counts query.
- After the response it **settles** on the resources actually returned: row count for searches and timelines, 1 for the single-resource tools.
- Consequence: a search with `max_results=100` against `remaining=40` fails with `budget_exhausted` even if only 12 posts exist. Set `max_results` at or below `remaining`.
- `budget_exhausted` includes `data.budget`, `data.reset_at` and `data.reset_at_epoch`.
- The daily cap is 500 posts by default (`X_DAILY_POST_BUDGET`), counted per local calendar day.
- Budget state is shared through a file, so two sessions with the same state file cannot double-spend; the local rate-limit bucket is per process and is not shared.

## Rate limits

- Local token bucket: a 30-call burst with one refill every 30 seconds (steady state ≈30 calls per 15 minutes). Exceeding it returns `rate_limited` with `retry_after_seconds`.
- Upstream 429: `rate_limited` with `reset_at_epoch` and `retry_after_seconds` parsed from `x-rate-limit-reset` (falling back to `retry-after`).
- The tool never retries automatically. A retry is the agent's decision, once, after the stated wait.

## Currency and time

- Every timestamp is UTC. Parse `created_at` with `datetime.fromisoformat(value.replace("Z", "+00:00"))`.
- `created_at` is the post time; `as_of` and `fetched_at` are retrieval times. Keep both when a claim depends on "as of".
- The search window is relative to the server's clock, not the user's; a query built for "yesterday" must be re-derived at call time.

## Related

- `x_search_recent` for the last seven days; web_search or tavily_search for anything older, labelled with the retrieval date.
- `x_get_post` for a single id; the built-in web fetch for a single public URL the user already has.
- `x_counts_recent` before a large pull; `data.budget` after every call.
