"""Asia/Shanghai timestamps used for trigger age, cooldowns and daily budgets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def parse_moment(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def format_moment(moment: datetime) -> str:
    return moment.astimezone(SHANGHAI).isoformat(timespec="seconds")


def parse_now(value: str) -> datetime:
    return parse_moment(value)
