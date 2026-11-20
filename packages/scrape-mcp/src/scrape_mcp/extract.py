"""Turn a fetched document into markdown, plain text or raw HTML.

``trafilatura`` is the only extraction dependency (chosen over html2text
because it isolates the main article body).  When it returns nothing -- tiny
test pages, unusual markup, parser errors -- a small stdlib HTML parser
provides a plain-text fallback so a valid page is never reported as a failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

import trafilatura

MAX_CONTENT_CHARS = 100_000
MAX_TITLE_CHARS = 500

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SPACE_RE = re.compile(r"[ \t\f\v\u00a0]+")
_BLANKS_RE = re.compile(r"\n{3,}")
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)


class ExtractError(RuntimeError):
    """The document could not be converted to the requested format."""


@dataclass(frozen=True)
class Extraction:
    title: str
    content: str
    truncated: bool


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return _normalize("".join(self._parts))


def _normalize(value: str) -> str:
    lines = [_SPACE_RE.sub(" ", line).strip() for line in value.splitlines()]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def _html_title(html: str) -> str:
    match = _TITLE_RE.search(html)
    if not match:
        return ""
    return _normalize(unescape(match.group(1)))[:MAX_TITLE_CHARS]


def _fallback_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise ExtractError("could not parse the HTML document") from exc
    return parser.text()


def _trafilatura(html: str, output_format: str, url: str) -> str:
    try:
        result = trafilatura.extract(
            html,
            url=url or None,
            output_format=output_format,
            include_tables=True,
            include_links=output_format == "markdown",
            include_images=False,
            include_comments=False,
            favor_recall=False,
        )
    except Exception as exc:
        raise ExtractError("text extraction failed") from exc
    return result or ""


def extract_content(
    document: str,
    extraction: str,
    *,
    url: str = "",
    content_type: str = "text/html",
) -> Extraction:
    media_type = (content_type or "").split(";")[0].strip().lower()
    is_html = media_type in ("text/html", "application/xhtml+xml", "application/xml", "text/xml")
    title = _html_title(document) if is_html else ""

    if extraction == "html":
        content = document
    elif not is_html:
        content = _normalize(document)
    else:
        output_format = "markdown" if extraction == "markdown" else "txt"
        content = _trafilatura(document, output_format, url)
        if not content.strip():
            content = _fallback_text(document)

    if not content.strip() and extraction != "html":
        content = _fallback_text(document) if is_html else content

    truncated = len(content) > MAX_CONTENT_CHARS
    if truncated:
        content = content[:MAX_CONTENT_CHARS]
    return Extraction(title=title, content=content, truncated=truncated)
