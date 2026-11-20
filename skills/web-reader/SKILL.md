---
name: web-reader
description: 读网页与文档链接：抓取文章、公告、网页内容并转成可读文本。 Read web pages, articles, announcements, and document links by fetching a URL and converting the response into Markdown text with the `web_fetch` tool. Covers source priority, truncation handling, publish/fetch dates, and privacy. For research support only; not investment advice.
---

# Web Reading

## Purpose

Fetch a specific URL and turn it into readable text, removing ads, navigation,
styling, and other distractions. Suitable for:
- API documentation (`tushare`, exchange data pages, and similar)
- Technical articles and blogs
- Company announcements, annual/interim reports, and exchange disclosure pages
- GitHub README / Wiki pages

For A-share and HK research, prefer the primary source: cninfo (巨潮资讯), the
SSE/SZSE/BSE announcement page, HKEXnews, the company IR page, or the regulator's
own site. Treat blogs, forums, aggregators, and social posts as low-reliability
secondary sources; if you use one, say so and try to trace the claim back to the
primary document.

## Usage

Call the `web_fetch` tool with the URL:

```
web_fetch(url="https://www.sse.com.cn/...")
```

`web_fetch` returns the URL, the HTTP status code, and the page body rendered to
Markdown or plain text. When the page or the output cap cuts the content, the
result is marked as truncated and the text ends with
`(Content truncated. Fetch a more specific URL or section for the full text.)`.
There is no `no_cache` parameter and no JSON `length` field; do not invent them.

`web_fetch` has no JavaScript rendering guarantee: a single-page app may return
only skeleton HTML. If that happens, try the site's print/plain version, the
underlying API or data endpoint, the PDF/announcement link, or `web_search` for
another copy. If none works, say the page could not be read.

## Source priority

1. Regulator, exchange, or company filing (cninfo/SSE/SZSE/BSE/HKEXnews/SEC).
2. Company IR page, official press release, or official data release.
3. Reputable media quoting the primary document.
4. Broker/research commentary, blogs, forums, social posts — secondary at best.

For every page used in a conclusion, record:
- the page's **publish date** (or "no date shown");
- the **fetch date** (`as_of`);
- the URL;
- whether the page is primary or secondary.

## Truncation and long documents

Announcements and annual reports are often far longer than one fetch. When the
result says it was truncated:

- Do not analyze the fragment as if it were the whole document.
- Fetch a more specific section URL, an anchor, or a paginated view when the site
  offers one.
- If the document is a PDF and the text cannot be extracted, use the announcement
  landing page or another accessible version; do not claim to have read pages you
  did not see.
- In the note, write "read is incomplete: truncated at <section>" and state which
  sections are missing.

## Privacy & freshness

- **Third-party dependency:** the fetch goes through the configured web provider,
  which may be an external service. Do **not** pass URLs containing credentials,
  tokens, cookies, or private/internal addresses — they would leave this host.
- **Caching/staleness:** a fetched page may be a cached snapshot. Check the page's
  own date and the fetch time before using a number. If freshness matters, fetch
  again later or use a source that publishes an explicit timestamp.
- **Bash fallback:** if a site blocks the normal fetch (for example HTTP 403/451),
  a manual `bash` + HTTP client fetch is possible, but it bypasses the tool's URL
  safety guard and the normal provider layer. Use it sparingly, never for
  internal/authenticated URLs, and record that you used a fallback.

## Common usage

Read an exchange disclosure page:
```
web_fetch(url="https://www.sse.com.cn/disclosure/listedinfo/announcement/")
```

Read a company's annual report landing page, then follow the PDF/section link:
```
web_fetch(url="https://www.cninfo.com.cn/...")
```

Read API documentation:
```
web_fetch(url="https://tushare.pro/document/2?doc_id=27")
```

