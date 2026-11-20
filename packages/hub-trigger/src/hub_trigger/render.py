"""Render the frozen hub context pack into the fast-judge prompt."""

from __future__ import annotations

import json
from typing import Any

from .config import CONTEXT_PLACEHOLDER

MAX_CONTEXT_BYTES = 12 * 1024
# Leave room for the newlines the template puts around the data block.
DEFAULT_CONTEXT_BYTES = MAX_CONTEXT_BYTES - 2


class RenderError(Exception):
    """Raised when the context pack cannot be serialized."""


def serialize_context(context: Any, max_bytes: int = DEFAULT_CONTEXT_BYTES) -> str:
    try:
        raw = json.dumps(
            context,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RenderError(f"上下文包无法序列化为 JSON: {exc}") from exc
    # A third-party string must not be able to close the <context_data> block.
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RenderError(f"上下文包无法编码为 UTF-8: {exc}") from exc
    if len(encoded) <= max_bytes:
        return raw
    return encoded[:max_bytes].decode("utf-8", "ignore")


def build_prompt(template_text: str, context: Any) -> str:
    if CONTEXT_PLACEHOLDER not in template_text:
        raise RenderError(f"提示词模板缺少 {CONTEXT_PLACEHOLDER}")
    return template_text.replace(CONTEXT_PLACEHOLDER, serialize_context(context))
