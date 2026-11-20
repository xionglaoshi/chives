# scrape_page / scrape_pages Reference

Field-level reference for the two scraping tools. Read this when a call returns an unfamiliar `error.code`, when you need the exact volume or politeness limit, or when a batch result has to be reconciled.

## Tool contracts

### scrape_page

| Param | Type | Default | Rule |
|---|---|---|---|
| `url` | string | required | `http`/`https` only; ≤2048 characters; no username/password; no whitespace or backslash |
| `mode` | string | `fast` | `fast` or `browser`; `stealth` returns `invalid_argument` |
| `extraction` | string | `markdown` | `markdown`, `text` or `html` |
| `timeout` | number | `30` | 1–60 seconds, per fetch |

### scrape_pages

| Param | Type | Default | Rule |
|---|---|---|---|
| `urls` | string[] | required | 1–10 entries, each validated like `url` |
| `mode` | string | `fast` | same as above |
| `extraction` | string | `markdown` | same as above |
| `timeout` | number | `30` | same as above, applied per URL |

scrape_pages runs up to 4 fetches concurrently in `fast` mode and 2 in `browser` mode. The results always come back in input order, whatever order the fetches finish in.

## Envelope

Every success and every error uses the same outer shape:

```json
{
  "ok": true,
  "source": "scrape",
  "as_of": "2026-11-03T08:00:00+00:00",
  "status": "ready",
  "data": {},
  "warnings": []
}
```

- `ok` is `status != "error"`.
- `status` is `ready` (content present), `empty` (request succeeded, no body text) or `error`.
- On a single-page error, `data` is `{}` and `error: {"code", "message"}` is added; `warnings` is always present. A batch where every URL fails is `status: "error"` with a top-level `error` but still carries `data.results` (see Batch data).
- `as_of` is the envelope timestamp; `data.fetched_at` is the per-page timestamp. They can differ, and in a browser batch by seconds.

## Single-page data

| Field | Type | Meaning |
|---|---|---|
| `url` | string | Requested URL, with sensitive query values redacted |
| `final_url` | string | URL after redirects; use this one in citations |
| `http_status` | integer | Status after redirects |
| `title` | string | Extracted title, possibly empty |
| `content` | string | Extracted body; `markdown`, `text` or raw `html` per the call |
| `truncated` | boolean | True when `content` hit the 100,000-character cap |
| `content_chars` | integer | Length of the returned `content` |
| `fetched_at` | string | ISO8601 UTC fetch time |
| `untrusted_text` | boolean | Always true: the body is third-party data |

`content` is a plain string. `content[0]` is a character, not a page. There are no `.css()`, `.xpath()` or `.body` attributes and no response headers on the result: parse the string, or call again with `extraction="html"`.

## Batch data

| Field | Type | Meaning |
|---|---|---|
| `count` | integer | Number of results, one per input URL |
| `succeeded` | integer | Entries with `ok: true` |
| `failed_count` | integer | Entries with `ok: false` |
| `results` | array | One entry per input URL, in input order |
| `failed` | array | The failed entries, repeated for convenience |
| `untrusted_text` | boolean | Always true |

A success entry has the single-page fields plus `ok: true`. A failure entry is `{"ok": false, "url": ..., "error": {"code", "message"}}`.

If every URL fails, `status` is `error` and a top-level `error` summarizes the first failure. `data.results` is still populated, so a caller can log each failure rather than losing the batch.

## Error codes

| Code | Trigger | Recovery |
|---|---|---|
| `invalid_url` | Not http(s), credentials in the URL, length > 2048, whitespace, bad port | Fix the URL; no retry |
| `ssrf_blocked` | Loopback, private, link-local, CGNAT, multicast, cloud metadata, non-allowlisted host | The target is not public; do not route around it |
| `robots_disallowed` | robots.txt disallows this user agent | Respect it; pick another page |
| `blocked` | 403/429, a challenge/verification page, or a file download | Change source: tavily_extract, tavily_search, or the official API |
| `fetch_failed` | DNS/connect failure, redirect loop, other non-2xx | One retry only if transient |
| `timeout` | Per-fetch timeout, including a read timeout | Raise `timeout` after confirming the page is slow |
| `too_large` | Response body over 5 MB | Use an API or a smaller representation |
| `extract_failed` | Non-text content type, or extraction failed | Try `extraction="html"`, or another source |
| `browser_unavailable` | Chrome missing or failed to start | Use `fast`, or ask the operator |
| `invalid_argument` | Bad parameter, including `stealth` / `solve_cloudflare` | Fix the arguments |
| `rate_limited` | Local per-minute or per-domain limit | Wait, then reduce volume |

An unexpected internal failure surfaces as `fetch_failed` rather than a separate code. Errors are returned in the envelope, never raised as exceptions.

## Politeness and limits

| Limit | Value |
|---|---|
| Same-domain request interval | ≥1 second, enforced, not skipped |
| Process page fetches | 600 per minute, then `rate_limited` |
| scrape_pages batch size | 10 URLs |
| scrape_pages concurrency | 4 (`fast`), 2 (`browser`) |
| Response body cap | 5 MB |
| Returned content cap | 100,000 characters |
| robots.txt cache | 1 hour per origin |
| Redirects | Followed manually, at most 5 hops |
| `timeout` range | 1–60 seconds |

The domain interval and robots check apply in both modes. `Crawl-delay` is not interpreted; the tool uses 1 second per domain uniformly and does not read sitemaps.

## URL and security rules

- Only public `http`/`https` targets. The tool resolves the host and rejects the request if **any** resolved address is loopback, private, link-local, CGNAT, multicast, reserved, a cloud metadata address, or an IPv6 ULA/link-local/6to4/Teredo/NAT64 address.
- The connection is bound to the validated IP with the original host in the `Host` header and TLS SNI, so a second DNS answer cannot redirect the connection to an internal address.
- Redirects are validated hop by hop; a loop is rejected.
- `SCRAPE_ALLOW_HOSTS`, when the operator sets it, restricts the tool to those domains and their subdomains.
- Sensitive query values (`token=`, `key=`, `password=`, `secret=`, `session=`, `signature=`) are redacted as `***` in returned URLs; credential-bearing headers are redacted in messages.
- The tool sends no cookies and keeps no login state.

## Using the HTML output

`extraction="html"` returns the raw markup in `content`. Typical parse targets:

- tables: `table.data tr` → cells via `td`/`th` text
- article body: `article`, `main`, or a known container class
- links: `a[href]`, resolved against `final_url`
- attributes that markdown drops: `data-*`, `datetime`, `title`

Parse in a workspace script, with BeautifulSoup or lxml only if already installed; otherwise use the standard library's `html.parser`. Do not install packages for a single parse, and do not assume a browser DOM is available.

`extraction="markdown"` is produced by trafilatura with a plain-text fallback; it strips navigation, ads and boilerplate, so a table that matters may need the HTML call instead.

## Pagination patterns

The tools do not paginate by themselves: each call fetches the URLs it is given. For a list that spans pages:

1. Fetch page 1 with `extraction="html"` when the next link lives in markup.
2. Extract the next-page link and resolve it against `final_url`.
3. Keep only unseen URLs; cap the crawl before it starts.
4. Send at most 10 URLs per batch call.
5. Stop on `blocked`, `robots_disallowed`, `empty`, or the cap.
6. Log `url`, `final_url`, `fetched_at` and `content_chars` for each kept page.

A cursor in the page's own query string (`?page=2`) is usually more reliable than a "next" button that is rendered by JavaScript. If the cursor is behind JS, use `mode="browser"` for the index page only and keep the article fetches in `fast` mode.

## Fallback ladder

| Situation | Next step |
|---|---|
| `blocked` on a public page | tavily_extract on the same URL, then tavily_search for the same facts, then the official API |
| `robots_disallowed` | Do not fetch it; use an official API, a licensed feed, or a different page |
| `empty` from `fast` | Retry once with `mode="browser"` |
| `empty` from `browser` | The content is behind login or canvas; use an official source |
| `browser_unavailable` | Stay on `fast`; report the gap rather than installing a browser |
| `too_large` | Request the API's JSON or a smaller page |
| `extract_failed` on a PDF or Office file | Use the data tool or the publisher's API; this tool does not parse those formats |
| `rate_limited` | Wait, then lower the batch size; the limiter is shared by the process |

When the fallback produces the fact, record which source produced it, the URL and the retrieval time. A scraped number without a retrieval time is not reproducible.
