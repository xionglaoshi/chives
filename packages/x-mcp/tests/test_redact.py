from __future__ import annotations

import json

from x_mcp.redact import MASK, Redactor

TOKEN = "AAAA" + "FAKE" + "TOKEN" + "1234567890"


def test_text_replacement() -> None:
    redactor = Redactor(TOKEN)
    assert redactor.text(f"before {TOKEN} after") == f"before {MASK} after"


def test_token_prefix_is_redacted() -> None:
    redactor = Redactor(TOKEN)
    prefix = TOKEN[:16]
    rendered = redactor.text(f"prefix is {prefix} and the rest is hidden")
    assert TOKEN[:16] not in rendered
    assert MASK in rendered


def test_bearer_payload_is_redacted_even_when_it_is_not_the_known_token() -> None:
    redactor = Redactor(TOKEN)
    rendered = redactor.text("Authorization: Bearer some-other-token")
    assert "some-other-token" not in rendered
    assert f"Bearer {MASK}" in rendered


def test_short_secret_is_still_replaced() -> None:
    redactor = Redactor("short")
    assert redactor.text("a short value") == f"a {MASK} value"


def test_empty_secret_is_a_noop() -> None:
    redactor = Redactor(None)
    assert redactor.text("unchanged") == "unchanged"
    assert redactor.obj({"a": "unchanged"}) == {"a": "unchanged"}


def test_nested_objects_are_redacted() -> None:
    redactor = Redactor(TOKEN)
    value = {
        "error": {"message": f"token {TOKEN} rejected"},
        "rows": [{"content": TOKEN}, {"nested": (TOKEN, 1)}],
    }
    rendered = json.dumps(redactor.obj(value))
    assert TOKEN not in rendered
    assert rendered.count(MASK) == 3


def test_dictionary_keys_are_redacted_too() -> None:
    redactor = Redactor(TOKEN)
    assert redactor.obj({TOKEN: TOKEN}) == {MASK: MASK}
