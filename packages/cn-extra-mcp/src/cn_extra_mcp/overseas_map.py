"""Strict loader for config/overseas-map.yaml (a deliberately small YAML subset).

PyYAML is not a dependency of this package, so the file format is restricted to:

    leaders:
      - symbol: usNVDA
        name: 英伟达
        a_share_sectors: [算力, 光模块]
        note: "关联逻辑"

Flow-style entries (``- {symbol: usNVDA, name: ..., a_share_sectors: [..]}``) are accepted too.
Everything else is rejected with a line number.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from cn_extra_mcp.symbols import is_overseas_symbol

MAP_ENV = "CN_EXTRA_OVERSEAS_MAP"
MAX_LEADERS = 30
MAX_NOTE_CHARS = 40
MAX_SECTORS = 8
ALLOWED_KEYS = ("symbol", "name", "a_share_sectors", "note")
REQUIRED_KEYS = ("symbol", "name", "a_share_sectors")

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:(?:\s+(.*))?$")


class MapError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def default_map_path() -> Path:
    override = os.environ.get(MAP_ENV)
    if override:
        return Path(override)
    # src/cn_extra_mcp/overseas_map.py -> repository root is four levels up from the file's folder
    return Path(__file__).resolve().parents[4] / "config" / "overseas-map.yaml"


def _split_top(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch in "[{":
            depth += 1
            current.append(ch)
        elif ch in "]}":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if quote or depth != 0:
        raise ValueError("unbalanced quote or bracket")
    parts.append("".join(current))
    return parts


def _scalar(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("empty value")
    if text[0] in "\"'":
        if len(text) < 2 or text[-1] != text[0]:
            raise ValueError("unterminated quoted string")
        return text[1:-1]
    if text[0] in "[{&*!|>":
        raise ValueError(f"unsupported value syntax: {text[0]!r}")
    return text


def _value(text: str) -> Any:
    text = text.strip()
    if text.startswith("["):
        if not text.endswith("]"):
            raise ValueError("unterminated list")
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(item) for item in _split_top(inner)]
    return _scalar(text)


def _flow_map(text: str) -> dict[str, Any]:
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError("unterminated flow map")
    inner = text[1:-1].strip()
    result: dict[str, Any] = {}
    for item in _split_top(inner):
        match = _KEY_RE.match(item.strip())
        if match is None or match.group(2) is None:
            raise ValueError(f"bad flow entry: {item.strip()!r}")
        key = match.group(1)
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = _value(match.group(2))
    return result


def parse_map_text(text: str) -> list[dict[str, Any]]:
    errors: list[str] = []
    entries: list[tuple[int, dict[str, Any]]] = []
    seen_leaders = False
    current: dict[str, Any] | None = None
    current_indent = 0

    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            errors.append(f"line {number}: tab indentation is not allowed")
            continue
        indent = len(raw) - len(raw.lstrip())
        body = raw.strip()

        if indent == 0 and not body.startswith("- "):
            match = _KEY_RE.match(body)
            if match is None or match.group(1) != "leaders":
                errors.append(f"line {number}: unknown top-level key (only 'leaders' is allowed)")
                continue
            if seen_leaders:
                errors.append(f"line {number}: duplicate key 'leaders'")
                continue
            seen_leaders = True
            rest = (match.group(2) or "").strip()
            if rest and rest != "[]":
                errors.append(f"line {number}: 'leaders' must be a block list")
            current = None
            continue

        if not seen_leaders:
            errors.append(f"line {number}: content before 'leaders:'")
            continue

        if body.startswith("- "):
            item = body[2:].strip()
            current = {}
            current_indent = indent
            entries.append((number, current))
            try:
                if item.startswith("{"):
                    current.update(_flow_map(item))
                    current = None
                else:
                    match = _KEY_RE.match(item)
                    if match is None or match.group(2) is None:
                        raise ValueError(f"expected 'key: value', got {item!r}")
                    current[match.group(1)] = _value(match.group(2))
            except ValueError as exc:
                errors.append(f"line {number}: {exc}")
                current = None
            continue

        if current is None or indent <= current_indent:
            errors.append(f"line {number}: unexpected line outside a list entry")
            continue
        match = _KEY_RE.match(body)
        try:
            if match is None or match.group(2) is None:
                raise ValueError(f"expected 'key: value', got {body!r}")
            key = match.group(1)
            if key in current:
                raise ValueError(f"duplicate key {key!r}")
            current[key] = _value(match.group(2))
        except ValueError as exc:
            errors.append(f"line {number}: {exc}")

    if not seen_leaders:
        errors.append("line 1: missing 'leaders:' key")

    validated: list[dict[str, Any]] = []
    symbols: set[str] = set()
    for position, (number, entry) in enumerate(entries, start=1):
        problems: list[str] = []
        if position > MAX_LEADERS:
            problems.append(f"more than {MAX_LEADERS} leaders")
        for key in entry:
            if key not in ALLOWED_KEYS:
                problems.append(f"unknown key {key!r}")
        for key in REQUIRED_KEYS:
            if key not in entry:
                problems.append(f"missing key {key!r}")
        symbol = entry.get("symbol")
        if symbol is not None:
            if not is_overseas_symbol(symbol):
                problems.append(f"invalid symbol {symbol!r}")
            elif symbol in symbols:
                problems.append(f"duplicate symbol {symbol!r}")
            else:
                symbols.add(symbol)
        name = entry.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            problems.append("name must be a non-empty string")
        sectors = entry.get("a_share_sectors")
        if sectors is not None:
            if (
                not isinstance(sectors, list)
                or not sectors
                or len(sectors) > MAX_SECTORS
                or not all(isinstance(s, str) and s.strip() for s in sectors)
            ):
                problems.append(f"a_share_sectors must be a list of 1-{MAX_SECTORS} non-empty strings")
        note = entry.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE_CHARS):
            problems.append(f"note must be a string of at most {MAX_NOTE_CHARS} characters")
        if problems:
            errors.extend(f"line {number}: {problem}" for problem in problems)
        else:
            validated.append(
                {
                    "symbol": entry["symbol"],
                    "name": entry["name"],
                    "a_share_sectors": list(entry["a_share_sectors"]),
                    "note": entry.get("note", ""),
                }
            )
    if errors:
        raise MapError(errors)
    return validated


def load_map(path: Path | None = None) -> list[dict[str, Any]] | None:
    """Return validated leaders, or None when the file does not exist. Raises MapError if invalid."""
    target = path or default_map_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise MapError([f"cannot read map file ({type(exc).__name__})"]) from exc
    return parse_map_text(text)
