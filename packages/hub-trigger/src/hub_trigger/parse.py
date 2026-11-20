"""Parse the single-line fast judgement returned by the runner."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

ACTION_LABELS: tuple[tuple[str, str], ...] = (
    ("观察", "observe"),
    ("等待确认", "await_confirm"),
    ("按预案执行", "execute"),
    ("放弃", "abandon"),
    ("按计划退出", "exit"),
)
ACTION_MAP = dict(ACTION_LABELS)
ACTION_ENUM = frozenset(ACTION_MAP.values())
FULLWIDTH_SEPARATOR = "｜"
HALFWIDTH_SEPARATOR = "|"
REASON_LIMIT = 40
NEXT_CHECK_LIMIT = 30
RISK_LIMIT = 30
TOTAL_LIMIT = 150


@dataclass(frozen=True)
class Judgement:
    action: str
    reason: str
    next_check: str
    risk: str


def last_nonempty_line(text: str) -> str:
    if not isinstance(text, str):
        return ""
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _clean(text: str) -> str:
    cleaned = "".join(
        " " if char in "\r\n\t" else char
        for char in text
        if char in "\r\n\t" or unicodedata.category(char) not in {"Cc", "Cf"}
    )
    return " ".join(cleaned.split())


def _truncate(text: str, limit: int) -> str:
    return text[:limit]


def _split(line: str) -> list[str]:
    separator = FULLWIDTH_SEPARATOR if FULLWIDTH_SEPARATOR in line else HALFWIDTH_SEPARATOR
    return line.split(separator)


def parse_line(line: str) -> Judgement | None:
    if not isinstance(line, str):
        return None
    text = line.strip()
    if not text:
        return None
    parts = _split(text)
    if len(parts) < 4:
        return None
    if len(parts) > 4:
        parts = parts[:3] + [FULLWIDTH_SEPARATOR.join(parts[3:])]
    action_label = _clean(parts[0])
    action = ACTION_MAP.get(action_label)
    if action is None:
        return None
    reason = _truncate(_clean(parts[1]), REASON_LIMIT)
    next_check = _truncate(_clean(parts[2]), NEXT_CHECK_LIMIT)
    risk = _truncate(_clean(parts[3]), RISK_LIMIT)
    if not reason or not next_check or not risk:
        return None
    # Per-field caps already keep the joined judgement below TOTAL_LIMIT; enforce
    # the total as a last resort so a future label change cannot exceed it.
    while len(reason) + len(next_check) + len(risk) + 3 > TOTAL_LIMIT and risk:
        risk = risk[:-1]
    if not risk:
        return None
    return Judgement(action=action, reason=reason, next_check=next_check, risk=risk)


def parse_judgement(text: str | None) -> Judgement | None:
    if text is None:
        return None
    return parse_line(last_nonempty_line(text))
