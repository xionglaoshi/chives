from __future__ import annotations

import json

from tavily_mcp.redact import MASK, Redactor


def test_text_replacement() -> None:
    redactor = Redactor("tvly-secret")
    assert redactor.text("before tvly-secret after") == f"before {MASK} after"


def test_empty_secret_is_a_noop() -> None:
    redactor = Redactor(None)
    assert redactor.text("unchanged") == "unchanged"
    assert redactor.obj({"a": "unchanged"}) == {"a": "unchanged"}


def test_nested_objects_are_redacted() -> None:
    redactor = Redactor("tvly-secret")
    value = {
        "error": {"message": "key tvly-secret rejected"},
        "rows": [{"content": "tvly-secret"}, {"nested": ("tvly-secret", 1)}],
    }
    rendered = json.dumps(redactor.obj(value))
    assert "tvly-secret" not in rendered
    assert rendered.count(MASK) == 3


def test_dictionary_keys_are_redacted_too() -> None:
    redactor = Redactor("tvly-secret")
    assert redactor.obj({"tvly-secret": "tvly-secret"}) == {MASK: MASK}
