"""A deliberately small YAML subset parser (standard library only).

market-watch may not depend on PyYAML, so configuration files use this subset:

* block mappings with two-space indentation
* block sequences (``- item``, ``- key: value``)
* flow sequences ``[a, b]`` and flow mappings ``{a: 1, b: 2}``
* unquoted / single-quoted / double-quoted scalars
* ``#`` comments, blank lines
* ``true``/``false``/``null``/``~``, integers, floats

Anchors, multi-line scalars, tags and nested block values inside flow
collections are rejected with :class:`YamlError` instead of being guessed.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["YamlError", "loads", "load"]


class YamlError(ValueError):
    """The document uses something outside the supported subset."""


_TRUE = {"true", "True", "TRUE"}
_FALSE = {"false", "False", "FALSE"}
_NULL = {"null", "Null", "NULL", "~"}


def _strip_comment(line: str) -> str:
    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == "#":
            return line[:index]
    return line


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        raise YamlError("empty scalar")
    if text[0] == '"':
        if len(text) < 2 or text[-1] != '"':
            raise YamlError(f"unterminated string: {text!r}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise YamlError(f"bad double-quoted string: {text!r}") from exc
    if text[0] == "'":
        if len(text) < 2 or text[-1] != "'":
            raise YamlError(f"unterminated string: {text!r}")
        return text[1:-1].replace("''", "'")
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if text in _NULL:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


class _Flow:
    """Recursive-descent parser for one flow collection or scalar."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def parse(self) -> Any:
        value = self._value()
        self._skip_space()
        if self.pos != len(self.text):
            raise YamlError(f"trailing characters: {self.text[self.pos:]!r}")
        return value

    def _skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def _value(self) -> Any:
        self._skip_space()
        if self.pos >= len(self.text):
            raise YamlError("unexpected end of flow value")
        char = self.text[self.pos]
        if char == "[":
            return self._sequence()
        if char == "{":
            return self._mapping()
        if char in {'"', "'"}:
            return self._quoted()
        return _scalar(self._bare(stop=",]}"))

    def _quoted(self) -> str:
        quote = self.text[self.pos]
        start = self.pos
        self.pos += 1
        escaped = False
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                self.pos += 1
                return _scalar(self.text[start : self.pos])
            self.pos += 1
        raise YamlError(f"unterminated string: {self.text[start:]!r}")

    def _bare(self, stop: str) -> str:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in stop:
            self.pos += 1
        return self.text[start : self.pos]

    def _sequence(self) -> list[Any]:
        self.pos += 1
        items: list[Any] = []
        self._skip_space()
        if self.pos < len(self.text) and self.text[self.pos] == "]":
            self.pos += 1
            return items
        while True:
            items.append(self._value())
            self._skip_space()
            if self.pos >= len(self.text):
                raise YamlError("unterminated flow sequence")
            char = self.text[self.pos]
            self.pos += 1
            if char == "]":
                return items
            if char != ",":
                raise YamlError(f"expected ',' or ']' at {self.pos}")

    def _mapping(self) -> dict[str, Any]:
        self.pos += 1
        result: dict[str, Any] = {}
        self._skip_space()
        if self.pos < len(self.text) and self.text[self.pos] == "}":
            self.pos += 1
            return result
        while True:
            self._skip_space()
            if self.pos < len(self.text) and self.text[self.pos] in {'"', "'"}:
                key = self._quoted()
            else:
                key = self._bare(stop=":").strip()
            if not key:
                raise YamlError("empty key in flow mapping")
            self._skip_space()
            if self.pos >= len(self.text) or self.text[self.pos] != ":":
                raise YamlError(f"expected ':' after key {key!r}")
            self.pos += 1
            result[str(key)] = self._value()
            self._skip_space()
            if self.pos >= len(self.text):
                raise YamlError("unterminated flow mapping")
            char = self.text[self.pos]
            self.pos += 1
            if char == "}":
                return result
            if char != ",":
                raise YamlError(f"expected ',' or '}}' at {self.pos}")


def _flow_value(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text[0] in "[{":
        return _Flow(text).parse()
    return _scalar(text)


class _Block:
    def __init__(self, lines: list[tuple[int, str]]) -> None:
        self.lines = lines
        self.pos = 0

    def parse(self) -> Any:
        if not self.lines:
            return {}
        value = self._node(self.lines[0][0])
        if self.pos != len(self.lines):
            indent, text = self.lines[self.pos]
            raise YamlError(f"unexpected indentation at line {indent}: {text!r}")
        return value

    def _node(self, indent: int) -> Any:
        if self.lines[self.pos][1].startswith("- "):
            return self._sequence(indent)
        return self._mapping(indent)

    def _mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.pos < len(self.lines):
            line_indent, text = self.lines[self.pos]
            if line_indent < indent:
                break
            if line_indent > indent:
                raise YamlError(f"unexpected indentation: {text!r}")
            if text.startswith("- "):
                break
            key, sep, rest = self._split_key(text)
            if not sep:
                raise YamlError(f"expected 'key: value': {text!r}")
            self.pos += 1
            if rest.strip():
                result[key] = _flow_value(rest.strip())
                continue
            if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                result[key] = self._node(self.lines[self.pos][0])
            else:
                result[key] = None
        return result

    def _sequence(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while self.pos < len(self.lines):
            line_indent, text = self.lines[self.pos]
            if line_indent != indent or not text.startswith("- "):
                break
            rest = text[2:].strip()
            self.pos += 1
            if not rest:
                if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                    result.append(self._node(self.lines[self.pos][0]))
                else:
                    result.append(None)
                continue
            key, sep, tail = self._split_key(rest)
            if sep and not rest.startswith(('"', "'", "[", "{")):
                item: dict[str, Any] = {}
                if tail.strip():
                    item[key] = _flow_value(tail.strip())
                elif self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                    item[key] = self._node(self.lines[self.pos][0])
                else:
                    item[key] = None
                if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                    extra = self._mapping(self.lines[self.pos][0])
                    for extra_key, extra_value in extra.items():
                        if extra_key in item:
                            raise YamlError(f"duplicate key in sequence item: {extra_key}")
                        item[extra_key] = extra_value
                result.append(item)
                continue
            result.append(_flow_value(rest))
        return result

    @staticmethod
    def _split_key(text: str) -> tuple[str, bool, str]:
        quote = ""
        for index, char in enumerate(text):
            if quote:
                if char == quote:
                    quote = ""
                continue
            if char in {'"', "'"}:
                quote = char
                continue
            if char == ":":
                if index + 1 < len(text) and text[index + 1] not in " \t":
                    continue
                key = text[:index].strip()
                if key.startswith(('"', "'")):
                    key = _scalar(key)
                return str(key), True, text[index + 1 :]
        return "", False, ""


def loads(text: str) -> Any:
    lines: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        if "\t" in stripped[: len(stripped) - len(stripped.lstrip())]:
            raise YamlError(f"tab indentation on line {number}")
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    if not lines:
        return {}
    return _Block(lines).parse()


def load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return loads(handle.read())
