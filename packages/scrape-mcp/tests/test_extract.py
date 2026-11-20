from __future__ import annotations

import trafilatura

from scrape_mcp.extract import MAX_CONTENT_CHARS, extract_content

ARTICLE = """<html><head><title>A &amp; B</title></head><body>
<nav>menu</nav>
<article><h1>Heading</h1><p>Paragraph one.</p><p>Paragraph two.</p></article>
</body></html>"""


def test_markdown_extraction_and_title() -> None:
    result = extract_content(ARTICLE, "markdown")
    assert result.title == "A & B"
    assert "Paragraph one." in result.content
    assert "Heading" in result.content
    assert result.truncated is False


def test_text_extraction() -> None:
    result = extract_content(ARTICLE, "text")
    assert "Paragraph two." in result.content
    assert "<p>" not in result.content


def test_html_extraction_is_raw() -> None:
    result = extract_content(ARTICLE, "html")
    assert "<article>" in result.content
    assert result.title == "A & B"


def test_plain_text_input() -> None:
    result = extract_content("just text", "markdown", content_type="text/plain")
    assert result.content == "just text"
    assert result.title == ""


def test_truncation_at_100k_characters() -> None:
    document = "<html><body><p>" + ("z" * (MAX_CONTENT_CHARS + 500)) + "</p></body></html>"
    result = extract_content(document, "text")
    assert result.truncated is True
    assert len(result.content) == MAX_CONTENT_CHARS


def test_fallback_when_trafilatura_returns_nothing(monkeypatch) -> None:
    monkeypatch.setattr(trafilatura, "extract", lambda *args, **kwargs: None)
    result = extract_content(ARTICLE, "markdown")
    assert "Paragraph one." in result.content
    assert "Heading" in result.content


def test_scripts_are_not_part_of_the_fallback_text(monkeypatch) -> None:
    monkeypatch.setattr(trafilatura, "extract", lambda *args, **kwargs: None)
    document = "<html><body><script>evil()</script><p>visible</p></body></html>"
    result = extract_content(document, "text")
    assert "visible" in result.content
    assert "evil()" not in result.content
