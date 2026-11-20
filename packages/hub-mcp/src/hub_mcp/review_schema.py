"""Local mirror of the hub's ``POST /reviews`` schema.

Validating here means a malformed review never reaches the hub, and the agent
gets a stable error code instead of an upstream 4xx.  Limits and field names
follow ``docs/hub-api.md`` (Review section) exactly.
"""

from __future__ import annotations

from typing import Any

from hub_mcp.errors import ToolError
from hub_mcp.validation import (
    clean_body,
    clean_free_text,
    normalize_code,
    only_fields,
    optional_text,
    safe_date,
)

REVIEW_FIELDS = {
    "date",
    "kind",
    "env",
    "mainline",
    "themes",
    "ladder_note",
    "lhb_note",
    "events",
    "yesterday_feedback",
    "candidates",
    "pending",
    "data_cutoff",
    "sources",
    "checklist",
    "body_markdown",
}
REVIEW_KINDS = {"evening", "premarket"}
ENV_LABELS = {"strong", "neutral", "weak"}
MAX_CANDIDATES = 5


def _text(value: Any, field: str, limit: int, *, allow_empty: bool = False) -> str:
    return clean_free_text(value, field, limit, allow_empty=allow_empty)


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ToolError("invalid_value", f"{field} 必须是布尔值", field=field)
    return value


def _int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("invalid_value", f"{field} 必须是整数", field=field)
    if value < minimum or value > maximum:
        raise ToolError("bad_value", f"{field} 必须在 {minimum}..{maximum}", field=field)
    return value


def _list(raw: Any, field: str) -> list[Any]:
    if not isinstance(raw, list):
        raise ToolError("invalid_value", f"{field} 必须是数组", field=field)
    return raw


def _env(raw: Any) -> dict[str, Any]:
    if raw is None:
        raise ToolError("invalid_env", "env 必填", field="env")
    if not isinstance(raw, dict):
        raise ToolError("invalid_env", "env 必须是对象", field="env")
    only_fields(raw, {"label", "evidence", "differs_from_rule", "differs_note"}, field="env")
    label = raw.get("label")
    if label not in ENV_LABELS:
        raise ToolError("invalid_env", "env.label 只接受 strong/neutral/weak", field="env")
    evidence_raw = raw.get("evidence", [])
    if not isinstance(evidence_raw, list):
        raise ToolError("invalid_env", "env.evidence 必须是数组", field="env")
    if len(evidence_raw) > 8:
        raise ToolError("too_many_evidence", "env.evidence 最多 8 条", field="env")
    env: dict[str, Any] = {
        "label": label,
        "evidence": [_text(item, "env.evidence", 80) for item in evidence_raw],
        "differs_from_rule": (
            _bool(raw.get("differs_from_rule"), "env.differs_from_rule")
            if "differs_from_rule" in raw
            else False
        ),
    }
    if raw.get("differs_note") is not None:
        env["differs_note"] = _text(raw.get("differs_note"), "env.differs_note", 120)
    return env


def _mainline(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ToolError("invalid_mainline", "mainline 必须是对象或 null", field="mainline")
    only_fields(raw, {"name", "note"}, field="mainline")
    return {
        "name": _text(raw.get("name"), "mainline.name", 40),
        "note": _text(raw.get("note"), "mainline.note", 120, allow_empty=True),
    }


def _themes(raw: Any) -> list[dict[str, Any]]:
    rows = _list(raw, "themes")
    if len(rows) > 6:
        raise ToolError("too_many_themes", "themes 最多 6 条", field="themes")
    result = []
    for item in rows:
        if not isinstance(item, dict):
            raise ToolError("invalid_themes", "themes 必须是对象数组", field="themes")
        only_fields(item, {"name", "note"}, field="themes")
        result.append(
            {
                "name": _text(item.get("name"), "themes.name", 40),
                "note": _text(item.get("note"), "themes.note", 120, allow_empty=True),
            }
        )
    return result


def _events(raw: Any) -> list[dict[str, Any]]:
    rows = _list(raw, "events")
    if len(rows) > 12:
        raise ToolError("too_many_events", "events 最多 12 条", field="events")
    result = []
    for item in rows:
        if not isinstance(item, dict):
            raise ToolError("invalid_events", "events 必须是对象数组", field="events")
        only_fields(item, {"date", "target", "type", "source", "uncertain", "note"}, field="events")
        result.append(
            {
                "date": _text(item.get("date"), "events.date", 10),
                "target": _text(item.get("target"), "events.target", 40),
                "type": _text(item.get("type"), "events.type", 20),
                "source": _text(item.get("source"), "events.source", 40),
                "uncertain": (
                    _bool(item.get("uncertain"), "events.uncertain") if "uncertain" in item else False
                ),
                "note": _text(item.get("note", ""), "events.note", 80, allow_empty=True),
            }
        )
    return result


def _candidate_tags(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ToolError("invalid_candidates", "candidates.tags 必须是对象", field="candidates")
    only_fields(raw, {"streak", "theme", "env"}, field="candidates.tags")
    tags: dict[str, Any] = {}
    if raw.get("streak") is not None:
        tags["streak"] = _int(raw.get("streak"), "tags.streak", minimum=0, maximum=100)
    if raw.get("theme") is not None:
        tags["theme"] = _text(raw.get("theme"), "tags.theme", 40, allow_empty=True)
    if raw.get("env") is not None:
        if raw.get("env") not in ENV_LABELS:
            raise ToolError("invalid_candidates", "tags.env 只接受 strong/neutral/weak", field="candidates")
        tags["env"] = raw["env"]
    return tags


def _candidates(raw: Any) -> list[dict[str, Any]]:
    rows = _list(raw, "candidates")
    if len(rows) > MAX_CANDIDATES:
        raise ToolError(
            "too_many_candidates", f"candidates 最多 {MAX_CANDIDATES} 个", field="candidates"
        )
    result = []
    for item in rows:
        if not isinstance(item, dict):
            raise ToolError("invalid_candidates", "candidates 必须是对象数组", field="candidates")
        only_fields(item, {"code", "reason", "card_id", "tags"}, field="candidates")
        card_id = item.get("card_id")
        if card_id is not None:
            if isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 1:
                raise ToolError("invalid_value", "card_id 必须是正整数或 null", field="candidates")
        result.append(
            {
                "code": normalize_code(item.get("code")),
                "reason": _text(item.get("reason"), "candidates.reason", 120),
                "card_id": card_id,
                "tags": _candidate_tags(item.get("tags")),
            }
        )
    return result


def _string_list(raw: Any, field: str, *, limit: int, max_chars: int) -> list[str]:
    rows = _list(raw, field)
    if len(rows) > limit:
        raise ToolError(f"too_many_{field}", f"{field} 最多 {limit} 条", field=field)
    return [_text(item, field, max_chars) for item in rows]


def _checklist(raw: Any) -> list[dict[str, Any]]:
    rows = _list(raw, "checklist")
    if len(rows) > 12:
        raise ToolError("too_many_checklist", "checklist 最多 12 条", field="checklist")
    result = []
    for item in rows:
        if not isinstance(item, dict):
            raise ToolError("invalid_checklist", "checklist 必须是对象数组", field="checklist")
        only_fields(item, {"item", "ok", "note"}, field="checklist")
        entry = {
            "item": _text(item.get("item"), "checklist.item", 60),
            "ok": _bool(item.get("ok"), "checklist.ok"),
        }
        if item.get("note") is not None:
            entry["note"] = _text(item.get("note"), "checklist.note", 80, allow_empty=True)
        result.append(entry)
    return result


def validate_review(payload: Any) -> dict[str, Any]:
    """Return the normalized review object or raise ToolError before any HTTP call."""
    if not isinstance(payload, dict):
        raise ToolError("invalid_body", "review 必须是 JSON 对象", field="review")
    only_fields(payload, REVIEW_FIELDS, field="review")
    if "date" not in payload:
        raise ToolError("invalid_date", "date 必填", field="date")
    day = safe_date(payload.get("date"))
    kind = payload.get("kind")
    if kind not in REVIEW_KINDS:
        raise ToolError("invalid_kind", "kind 只接受 evening/premarket", field="kind")
    return {
        "date": day,
        "kind": kind,
        "env": _env(payload.get("env")),
        "mainline": _mainline(payload.get("mainline")),
        "themes": _themes(payload.get("themes") or []),
        "ladder_note": optional_text(payload.get("ladder_note"), "ladder_note", 200),
        "lhb_note": optional_text(payload.get("lhb_note"), "lhb_note", 300),
        "events": _events(payload.get("events") or []),
        "yesterday_feedback": optional_text(payload.get("yesterday_feedback"), "yesterday_feedback", 300),
        "candidates": _candidates(payload.get("candidates") or []),
        "pending": _string_list(payload.get("pending") or [], "pending", limit=10, max_chars=80),
        "data_cutoff": optional_text(payload.get("data_cutoff"), "data_cutoff", 10),
        "sources": _string_list(payload.get("sources") or [], "sources", limit=10, max_chars=80),
        "checklist": _checklist(payload.get("checklist") or []),
        "body_markdown": clean_body(payload.get("body_markdown", "")),
    }
