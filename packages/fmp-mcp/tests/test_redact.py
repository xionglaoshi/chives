from __future__ import annotations

from fmp_mcp.redact import redact

KEY = "SECRETKEY_ABC123"


def test_apikey_query_fragment_is_redacted() -> None:
    text = f"GET https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey={KEY}&limit=5"
    out = redact(text, KEY)
    assert KEY not in out
    assert "apikey=***" in out
    assert "limit=5" in out


def test_json_apikey_is_redacted() -> None:
    text = '{"apikey": "' + KEY + '", "symbol": "AAPL"}'
    out = redact(text, KEY)
    assert KEY not in out
    assert '"apikey": "***"' in out


def test_raw_secret_is_redacted_even_without_a_key_name() -> None:
    out = redact(f"upstream said {KEY} is invalid", KEY)
    assert KEY not in out and "***" in out


def test_empty_text_and_no_secret_are_safe() -> None:
    assert redact("", KEY) == ""
    assert redact("plain", None) == "plain"
