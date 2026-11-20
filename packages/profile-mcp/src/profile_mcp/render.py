"""Render the profile into the managed AGENTS.md block."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from profile_mcp.atomic import atomic_write_text
from profile_mcp.fields import FIELD_LABELS, FIELD_ORDER, MAX_BLOCK_BYTES

START_MARKER = "<!-- dsh-finance:profile:start -->"
END_MARKER = "<!-- dsh-finance:profile:end -->"

INTRO = (
    "以下是用户自己在对话中说明的偏好；给分析和建议时要考虑，"
    "行情与持仓等易变事实使用前以当前数据为准；若与用户当前对话冲突，以当前对话为准。"
)

TRUNCATED_NOTICE = "- （画像过长，部分字段已省略；完整内容见 finance-profile.json）"


def _quote(value: str) -> str:
    return '"' + value + '"'


def _format_value(field: str, value: Any) -> str:
    if field == "agent_preference":
        return _quote(str(value))
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "、".join(_quote(str(item)) for item in value)
    return str(value)


def render_block(profile: dict[str, Any]) -> str:
    """Return the full managed block (markers included), capped at MAX_BLOCK_BYTES."""
    body: list[str] = []
    for field in FIELD_ORDER:
        if field not in profile:
            continue
        body.append(f"- {FIELD_LABELS[field]} ({field}): {_format_value(field, profile[field])}")

    def build(lines: list[str], *, notice: bool) -> str:
        parts = [START_MARKER, "## 用户画像（Chives）", "", INTRO, ""]
        parts.extend(lines)
        if notice and lines:
            parts.append(TRUNCATED_NOTICE)
        parts.append(END_MARKER)
        return "\n".join(parts)

    kept = list(body)
    block = build(kept, notice=False)
    if len(block.encode("utf-8")) <= MAX_BLOCK_BYTES:
        return block
    while kept:
        kept.pop()
        block = build(kept, notice=True)
        if len(block.encode("utf-8")) <= MAX_BLOCK_BYTES:
            return block
    block = build([], notice=False)
    if len(block.encode("utf-8")) <= MAX_BLOCK_BYTES:
        return block
    # Last resort: keep both markers and the introduction, nothing else.
    return "\n".join([START_MARKER, INTRO, END_MARKER])


def _markers(text: str) -> tuple[int, int]:
    return text.count(START_MARKER), text.count(END_MARKER)


def sync_agents_md(path: Path, profile: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Insert, replace or remove the managed block; never rewrite unrelated text."""
    warnings: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = None
    except (OSError, UnicodeDecodeError) as exc:
        warnings.append(
            {
                "code": "agents_md_unreadable",
                "message": f"could not read {path.name}: {type(exc).__name__}; the profile was saved but AGENTS.md was not changed",
            }
        )
        return {"path": str(path), "status": "skipped", "bytes": 0}, warnings

    if text is None:
        if not profile:
            return {"path": str(path), "status": "unchanged", "bytes": 0}, warnings
        text = ""

    starts, ends = _markers(text)
    start_at = text.find(START_MARKER)
    end_at = text.find(END_MARKER)
    if (starts, ends) == (1, 1) and end_at < start_at:
        warnings.append(
            {
                "code": "agents_md_markers_broken",
                "message": "profile markers appear in the wrong order; AGENTS.md was left untouched",
            }
        )
        return {"path": str(path), "status": "skipped", "bytes": 0}, warnings
    if (starts, ends) not in ((0, 0), (1, 1)):
        warnings.append(
            {
                "code": "agents_md_markers_broken",
                "message": "profile markers are missing one half or duplicated; AGENTS.md was left untouched",
            }
        )
        return {"path": str(path), "status": "skipped", "bytes": 0}, warnings

    block = render_block(profile) if profile else ""
    status = "unchanged"
    if starts == 1:
        span_end = end_at + len(END_MARKER)
        if profile:
            if text[start_at:span_end] == block:
                return {"path": str(path), "status": "unchanged", "bytes": len(block.encode("utf-8"))}, warnings
            new_text = text[:start_at] + block + text[span_end:]
            status = "updated"
        else:
            prefix = text[:start_at]
            suffix = text[span_end:]
            new_text = prefix + suffix
            if suffix == "\n" and prefix.endswith("\n"):
                new_text = prefix
            status = "removed"
            if not new_text.strip():
                new_text = ""
    else:
        if not profile:
            return {"path": str(path), "status": "unchanged", "bytes": 0}, warnings
        separator = "" if not text or text.endswith("\n") else "\n"
        new_text = text + separator + block + "\n"
        status = "updated" if path.exists() else "created"

    try:
        atomic_write_text(path, new_text)
    except OSError as exc:
        warnings.append(
            {
                "code": "agents_md_write_failed",
                "message": f"could not write {path.name}: {type(exc).__name__}; the profile was saved",
            }
        )
        return {"path": str(path), "status": "failed", "bytes": 0}, warnings
    return {"path": str(path), "status": status, "bytes": len(block.encode("utf-8"))}, warnings
