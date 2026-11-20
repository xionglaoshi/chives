"""A deliberately small YAML subset parser (stdlib only).

The runner configuration only needs block mappings, block/indentless
sequences and scalar/flow values.  Full YAML is out of scope; JSON is a
subset of YAML and is accepted by the same entry point.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_INT_RE = re.compile(r"^[-+]?[0-9]+$")
_FLOAT_RE = re.compile(r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?$")


class YamlError(ValueError):
    """Raised when the input is not in the supported YAML subset."""


@dataclass(frozen=True)
class _Line:
    indent: int
    text: str
    number: int


def _strip_comment(text: str) -> str:
    in_single = False
    in_double = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_single:
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                in_single = False
        elif in_double:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_double = False
        elif char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char == "#" and (index == 0 or text[index - 1].isspace()):
            return text[:index].rstrip()
        index += 1
    return text.rstrip()


def _split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_single = False
    in_double = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_single:
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                in_single = False
        elif in_double:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_double = False
        elif char in "'\"":
            if char == "'":
                in_single = True
            else:
                in_double = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
        index += 1
    parts.append(text[start:].strip())
    return parts


def _find_key_colon(text: str) -> int:
    in_single = False
    in_double = False
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if in_single:
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                in_single = False
        elif in_double:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_double = False
        elif char in "'\"":
            if char == "'":
                in_single = True
            else:
                in_double = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0:
            if index + 1 == len(text) or text[index + 1].isspace():
                return index
        index += 1
    return -1


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) < 2 or text[0] != text[-1] or text[0] not in "'\"":
        raise YamlError(f"非法引号字符串: {text!r}")
    if text[0] == '"':
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise YamlError(f"非法双引号字符串: {text!r}") from exc
        return str(value)
    return text[1:-1].replace("''", "'")


def parse_scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(part) for part in _split_top_level(inner, ",")]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        if not inner:
            return {}
        result: dict[str, Any] = {}
        for part in _split_top_level(inner, ","):
            colon = _find_key_colon(part)
            if colon < 0:
                raise YamlError(f"非法流式映射项: {part!r}")
            key = parse_scalar(part[:colon])
            if not isinstance(key, str):
                key = str(key)
            result[key] = parse_scalar(part[colon + 1 :])
        return result
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return _unquote(text)
    lowered = text.lower()
    if lowered in {"null", "~", "none"}:
        return None
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if _INT_RE.match(text):
        try:
            return int(text)
        except ValueError:
            pass
    if _FLOAT_RE.match(text):
        try:
            return float(text)
        except ValueError:
            pass
    return text


class _Parser:
    def __init__(self, lines: list[_Line]) -> None:
        self.lines = lines

    def parse(self) -> Any:
        if not self.lines:
            return None
        value, index = self._parse_node(0, self.lines[0].indent)
        if index != len(self.lines):
            line = self.lines[index]
            raise YamlError(f"第 {line.number} 行缩进无法解析")
        return value

    def _parse_node(self, index: int, indent: int) -> tuple[Any, int]:
        if index >= len(self.lines):
            return None, index
        line = self.lines[index]
        if line.indent < indent:
            return None, index
        if line.text == "-" or line.text.startswith("- "):
            return self._parse_sequence(index, line.indent)
        return self._parse_mapping(index, line.indent)

    def _parse_mapping(self, index: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(self.lines):
            line = self.lines[index]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise YamlError(f"第 {line.number} 行缩进不一致")
            if line.text == "-" or line.text.startswith("- "):
                break
            colon = _find_key_colon(line.text)
            if colon < 0:
                raise YamlError(f"第 {line.number} 行缺少键值分隔冒号")
            raw_key = line.text[:colon].strip()
            if not raw_key:
                raise YamlError(f"第 {line.number} 行键为空")
            key_value = parse_scalar(raw_key)
            key = key_value if isinstance(key_value, str) else str(key_value)
            remainder = line.text[colon + 1 :].strip()
            index += 1
            if remainder:
                result[key] = parse_scalar(remainder)
                continue
            if index < len(self.lines):
                following = self.lines[index]
                if following.indent > indent:
                    value, index = self._parse_node(index, following.indent)
                    result[key] = value
                    continue
                if following.indent == indent and (
                    following.text == "-" or following.text.startswith("- ")
                ):
                    value, index = self._parse_sequence(index, indent)
                    result[key] = value
                    continue
            result[key] = None
        return result, index

    def _parse_sequence(self, index: int, indent: int) -> tuple[list[Any], int]:
        items: list[Any] = []
        while index < len(self.lines):
            line = self.lines[index]
            if line.indent != indent or not (line.text == "-" or line.text.startswith("- ")):
                break
            remainder = line.text[1:].strip()
            index += 1
            if not remainder:
                if index < len(self.lines) and self.lines[index].indent > indent:
                    value, index = self._parse_node(index, self.lines[index].indent)
                else:
                    value = None
                items.append(value)
                continue
            colon = _find_key_colon(remainder)
            if colon >= 0 and not remainder.startswith(("'", '"', "[", "{")):
                item: dict[str, Any] = {}
                key_value = parse_scalar(remainder[:colon].strip())
                key = key_value if isinstance(key_value, str) else str(key_value)
                tail = remainder[colon + 1 :].strip()
                if tail:
                    item[key] = parse_scalar(tail)
                elif index < len(self.lines) and self.lines[index].indent > indent:
                    nested, index = self._parse_node(index, self.lines[index].indent)
                    item[key] = nested
                else:
                    item[key] = None
                if index < len(self.lines) and self.lines[index].indent > indent:
                    extra, index = self._parse_mapping(index, self.lines[index].indent)
                    item.update(extra)
                items.append(item)
            else:
                items.append(parse_scalar(remainder))
        return items, index


def parse(text: str) -> Any:
    """Parse the supported YAML subset (JSON input is accepted too)."""

    if not isinstance(text, str):
        raise YamlError("输入必须是字符串")
    stripped = text.lstrip("\ufeff")
    json_candidate = "\n".join(
        line for line in stripped.splitlines() if not line.lstrip().startswith("#")
    )
    if json_candidate.lstrip().startswith(("{", "[")):
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            pass
    lines: list[_Line] = []
    raw_lines = stripped.splitlines()
    index = 0
    while index < len(raw_lines):
        raw = raw_lines[index]
        number = index + 1
        index += 1
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"第 {number} 行使用了制表符缩进")
        content = _strip_comment(raw)
        if not content.strip() or content.strip() == "---":
            continue
        indent = len(content) - len(content.lstrip(" "))
        lines.append(_Line(indent=indent, text=content.strip(), number=number))
    if not lines:
        return None
    return _Parser(lines).parse()
