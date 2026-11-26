"""Shared value objects and China-time helpers.

Timestamps are timezone aware and normalized to UTC+8.  Nothing in this module
reads the wall clock; callers inject time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

CN_TZ = timezone(timedelta(hours=8))

KIND_LABELS = {
    "plan_proposal": "待确认计划",
    "plan_entry": "进场位到达",
    "plan_giveup": "不再跟",
    "plan_other": "计划提醒",
    "sector": "板块异动",
    "risk": "风险",
    "opportunity": "机会",
    "info": "信息",
    "card_proposal": "待确认作战卡",
    "card_state": "作战卡状态变化",
    "guidance": "盘中指引",
    "emergency": "应急",
    "review_ready": "复盘已生成",
    "discipline": "纪律暂停",
}

DIRECTION_LABELS = {"bull": "偏多", "bear": "偏空", "neutral": "中性"}

STATUSES = ("new", "seen", "snoozed", "done", "ignored")

SEVERITY_RANK = {"L1": 1, "L2": 2, "L3": 3}


def to_cn(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(CN_TZ)


def parse_iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected an ISO8601 timestamp")
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        raise ValueError("ISO8601 timestamp must include a timezone offset")
    return to_cn(parsed)


def fmt_iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else to_cn(value).isoformat()


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat()


def truncate(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


@dataclass
class Signal:
    id: Optional[int]
    ts: datetime
    kind: str
    decide: bool
    severity: str
    status: str
    object_type: str
    object_code: str
    object_name: str
    title: str
    direction: str
    conclusion: str
    brief: str
    context: Optional[dict[str, Any]]
    source: dict[str, Any]
    merged_count: int
    primary: dict[str, Any]
    detail_available: bool
    rule_id: Optional[str] = None
    analysis_id: Optional[int] = None
    snooze_until: Optional[datetime] = None
    ignored: bool = False
    folded: bool = False
    dedupe_key: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": fmt_iso(self.ts),
            "kind": self.kind,
            "kind_label": KIND_LABELS.get(self.kind, self.kind),
            "decide": self.decide,
            "severity": self.severity,
            "status": self.status,
            "snooze_until": fmt_iso(self.snooze_until),
            "object": {
                "type": self.object_type,
                "code": self.object_code,
                "name": self.object_name,
            },
            "title": self.title,
            "direction": self.direction,
            "direction_label": DIRECTION_LABELS.get(self.direction, "中性"),
            "conclusion": self.conclusion,
            "brief": self.brief,
            "context": self.context,
            "source": self.source,
            "merged_count": self.merged_count,
            "primary": self.primary,
            "detail_available": self.detail_available,
        }


@dataclass
class Plan:
    id: Optional[int]
    code: str
    name: str
    kind: str
    status: str
    condition: dict[str, Any]
    stop: Optional[float]
    rationale: str
    source: dict[str, Any]
    proposed_by: str
    created_at: datetime
    expires_at: datetime
    triggered_at: Optional[datetime] = None
    last_price: Optional[float] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "condition": dict(self.condition),
            "stop": self.stop,
            "rationale": self.rationale,
            "source": dict(self.source),
            "proposed_by": self.proposed_by,
            "created_at": fmt_iso(self.created_at),
            "expires_at": fmt_iso(self.expires_at),
            "triggered_at": fmt_iso(self.triggered_at),
            "last_price": self.last_price,
        }


@dataclass
class Analysis:
    alert_id: int
    status: str
    reason: Optional[str] = None
    file: Optional[str] = None
    markdown: str = ""
    conclusion: str = ""
    direction: str = "neutral"
    points: list[str] = field(default_factory=list)
    detail: str = ""
