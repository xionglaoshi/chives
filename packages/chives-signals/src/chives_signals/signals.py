"""Deterministic alert -> Signal processing (no model calls).

The rules live here so they are unit-testable without HTTP or SQLite:

* chives-radar stock alerts and market-watch R1-R6 alerts map to ``kind`` by rule
  type and direction;
* analysis markdown supplies the conclusion paragraph, direction and bullet
  points when a matching analysis exists;
* identical ``(object, rule)`` events merge for 30 minutes, while
  "misreport" (误报) cards fold for the rest of the trading day and default to
  ``done`` / ``info``.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

from .models import (
    CN_TZ,
    KIND_LABELS,
    SEVERITY_RANK,
    Analysis,
    Plan,
    Signal,
    fmt_iso,
    parse_iso,
    truncate,
)

MERGE_WINDOW = timedelta(minutes=30)
CONCLUSION_LIMIT = 60
BRIEF_LIMIT = 140

_CN_RULE_LABELS = {
    "pct_change": "涨跌幅异动",
    "vwap_deviation": "VWAP 偏离",
    "limit_proximity": "临近涨跌停",
    "price_cross": "价格穿越",
    "volume_surge": "成交额突增",
}

_MARKET_RULE_LABELS = {
    "R1": "指数放量下跌",
    "R2": "宽度恶化",
    "R3": "板块排名跃升",
    "R4": "板块涨停骤增",
    "R5": "相对强弱穿越",
    "R6": "个股板块背离",
}

_CONCLUSION_RE = re.compile(r"\*\*\s*结论\s*[:：]\s*(.+?)\*\*", re.DOTALL)
_CONCLUSION_OPEN_RE = re.compile(r"\*\*\s*结论\s*[:：]\s*(.+)", re.DOTALL)
_DIRECTION_LINE_RE = re.compile(
    r"^\s*(?:\*\*)?\s*方向\s*[:：]\s*(?:\*\*)?\s*(误报|偏多|偏空|中性)",
    re.MULTILINE,
)
_POINTS_HEADER_RE = re.compile(r"^\s*(?:\*\*)?\s*要点\s*[:：]\s*(?:\*\*)?\s*$", re.MULTILINE)
_DIVIDER_RE = re.compile(r"^\s*---\s*$", re.MULTILINE)
_DIRECTION_WORDS = (("误报", "neutral"), ("偏多", "bull"), ("偏空", "bear"), ("中性", "neutral"))
_DIRECTION_LINE_MAP = {"误报": "neutral", "偏多": "bull", "偏空": "bear", "中性": "neutral"}
_META_PREFIXES = (
    "告警 ID：",
    "告警时间：",
    "代码：",
    "名称：",
    "规则：",
    "状态：",
    "开始时间：",
    "结束时间：",
    "sessionId：",
)


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()


def _paragraphs(markdown: str) -> list[str]:
    chunks = re.split(r"\n\s*\n", markdown.replace("\r\n", "\n"))
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _content_paragraphs(markdown: str) -> list[str]:
    result: list[str] = []
    for paragraph in _paragraphs(markdown):
        if paragraph.startswith("#"):
            continue
        if paragraph.startswith("- ") and paragraph[2:].startswith(_META_PREFIXES):
            continue
        result.append(paragraph)
    return result


def extract_conclusion(markdown: str) -> str:
    if not markdown:
        return ""
    match = _CONCLUSION_RE.search(markdown)
    if match:
        return truncate(_plain(match.group(1)), CONCLUSION_LIMIT)
    opening = _CONCLUSION_OPEN_RE.search(markdown)
    if opening:
        first_line = opening.group(1).splitlines()[0]
        return truncate(_plain(first_line), CONCLUSION_LIMIT)
    paragraphs = _content_paragraphs(markdown)
    if not paragraphs:
        return ""
    return truncate(_plain(paragraphs[0]), CONCLUSION_LIMIT)


def extract_direction(markdown: str) -> str:
    if not markdown:
        return "neutral"
    explicit = _DIRECTION_LINE_RE.search(markdown)
    if explicit:
        return _DIRECTION_LINE_MAP[explicit.group(1)]
    conclusion = extract_conclusion(markdown)
    for word, direction in _DIRECTION_WORDS:
        if word in conclusion:
            return direction
    positions = [(markdown.find(word), direction) for word, direction in _DIRECTION_WORDS if word in markdown]
    if not positions:
        return "neutral"
    return min(positions, key=lambda item: item[0])[1]


def _bullet_point(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped.startswith(("- ", "• ", "* ")):
        return None
    text = _plain(stripped[2:])
    if not text or text.startswith(_META_PREFIXES):
        return None
    return truncate(text, 120)


def _points_block(markdown: str) -> Optional[list[str]]:
    """Points under a leading ``要点：`` line, stopping at the divider."""
    header = _POINTS_HEADER_RE.search(markdown)
    if header is None:
        return None
    points: list[str] = []
    for line in markdown[header.end() :].splitlines():
        if line.strip() == "---":
            break
        if not line.strip():
            continue
        point = _bullet_point(line)
        if point is None:
            break
        points.append(point)
        if len(points) >= 5:
            break
    return points


def extract_points(markdown: str) -> list[str]:
    block = _points_block(markdown)
    if block is not None:
        return block
    points: list[str] = []
    for line in markdown.splitlines():
        point = _bullet_point(line)
        if point is None:
            continue
        points.append(point)
        if len(points) >= 5:
            break
    return points


def _new_format_detail(markdown: str) -> Optional[str]:
    """Body after the divider when the fixed 方向/要点/divider header is present."""
    header = _DIRECTION_LINE_RE.search(markdown)
    if header is None:
        return None
    divider = _DIVIDER_RE.search(markdown, header.end())
    if divider is None:
        return None
    paragraphs: list[str] = []
    for paragraph in _paragraphs(markdown[divider.end() :]):
        if paragraph.startswith("- ") and paragraph[2:].startswith(_META_PREFIXES):
            continue
        text = re.sub(r"(?m)^\s*#{1,6}\s*", "", paragraph)
        paragraphs.append(_plain(text))
    return truncate(" ".join(paragraphs), 4000)


def extract_detail(markdown: str) -> str:
    if not markdown:
        return ""
    detailed = _new_format_detail(markdown)
    if detailed is not None:
        return detailed
    body = _CONCLUSION_RE.sub("", markdown)
    paragraphs = _content_paragraphs(body)
    return truncate(" ".join(_plain(item) for item in paragraphs), 4000)


def analysis_sections(analysis: Optional[Analysis]) -> dict[str, Any]:
    if analysis is None or not analysis.markdown:
        return {
            "markdown": "",
            "sections": {
                "conclusion": "",
                "direction": "neutral",
                "points": [],
                "detail": "",
            },
        }
    markdown = analysis.markdown
    return {
        "markdown": markdown,
        "sections": {
            "conclusion": extract_conclusion(markdown),
            "direction": extract_direction(markdown),
            "points": extract_points(markdown),
            "detail": extract_detail(markdown),
        },
    }


def analysis_skipped(analysis: Optional[Analysis]) -> bool:
    if analysis is None:
        return False
    if analysis.status in {"skipped", "dry_run"}:
        return True
    return analysis.reason in {"dry_run", "cooldown"}


def is_false_positive(analysis: Optional[Analysis]) -> bool:
    if analysis is None or not analysis.markdown:
        return False
    return "误报" in analysis.markdown


def dedupe_key(object_type: str, code: str, rule_id: Optional[str]) -> str:
    return f"{object_type}|{code}|{rule_id or ''}"


def merge_since(kind: str, false_positive: bool, ts: datetime) -> datetime:
    if kind == "info" and false_positive:
        local = ts.astimezone(CN_TZ)
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    return ts - MERGE_WINDOW


def _severity_from_cn(rule_type: str) -> str:
    if rule_type == "limit_proximity":
        return "L3"
    if rule_type in {"pct_change", "vwap_deviation", "volume_surge", "price_cross"}:
        return "L2"
    return "L1"


def _cn_kind(rule_type: str, direction: Optional[str], change_pct: Optional[float], false_positive: bool) -> str:
    if false_positive:
        return "info"
    if rule_type == "limit_proximity":
        return "risk" if direction == "down" else "opportunity"
    if rule_type == "volume_surge":
        if change_pct is None or change_pct == 0:
            return "info"
        return "risk" if change_pct < 0 else "opportunity"
    if rule_type == "price_cross":
        return "risk" if direction == "down" else "opportunity"
    if rule_type in {"pct_change", "vwap_deviation"}:
        return "risk" if direction == "down" else "opportunity"
    return "info"


def _bit(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _cn_title(alert: dict[str, Any], rule_type: str) -> str:
    name = str(alert.get("name") or alert.get("code") or "个股")
    label = _CN_RULE_LABELS.get(rule_type, "规则触发")
    change = _number(alert.get("change_pct"))
    price = _number(alert.get("price"))
    if rule_type == "pct_change" and change is not None:
        return f"{name} {label} {change:+.2f}%"
    if rule_type == "vwap_deviation" and change is not None:
        return f"{name} {label}（现价 {price:.2f}）" if price is not None else f"{name} {label}"
    if rule_type == "limit_proximity":
        side = "涨停" if alert.get("direction") == "up" else "跌停"
        return f"{name} 临近{side}"
    if rule_type == "price_cross" and price is not None:
        return f"{name} {label}（现价 {price:.2f}）"
    if price is not None:
        return f"{name} {label}（现价 {price:.2f}）"
    return f"{name} {label}"


def _cn_conclusion(alert: dict[str, Any], rule_type: str) -> str:
    name = str(alert.get("name") or alert.get("code") or "个股")
    price = _number(alert.get("price"))
    change = _number(alert.get("change_pct"))
    parts = [f"{name} 触发{_CN_RULE_LABELS.get(rule_type, '规则')}"]
    if price is not None:
        parts.append(f"现价 {price:.2f}")
    if change is not None:
        parts.append(f"涨跌 {change:+.2f}%")
    return truncate("，".join(parts), CONCLUSION_LIMIT)


def _context_range(
    *,
    level_lo: float,
    level_hi: float,
    stop: Optional[float],
    price: Optional[float],
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    giveup: bool = False,
) -> dict[str, Any]:
    return {
        "type": "range",
        "level_lo": level_lo,
        "level_hi": level_hi,
        "stop": stop,
        "price": price,
        "min": minimum if minimum is not None else level_lo,
        "max": maximum if maximum is not None else level_hi,
        "giveup": giveup,
    }


def _context_from_alert(alert: dict[str, Any]) -> Optional[dict[str, Any]]:
    payload = alert.get("payload")
    if isinstance(payload, dict):
        spark = payload.get("spark")
        if isinstance(spark, list):
            points = [
                float(item)
                for item in spark[:120]
                if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item))
            ]
            if points:
                return {"type": "spark", "points": points, "label": "盘中走势"}
        metrics: dict[str, Any] = {}
        objects = payload.get("objects")
        if isinstance(objects, list) and objects and isinstance(objects[0], dict):
            if isinstance(objects[0].get("metrics"), dict):
                metrics = objects[0]["metrics"]
        rank = _number(payload.get("rank")) or _number(metrics.get("rank"))
        before = _number(payload.get("rank_before")) or _number(metrics.get("rank_30m_ago"))
        if rank is not None and before is not None:
            share = _number(payload.get("amount_share_pct"))
            if share is None:
                share = _number(metrics.get("amount_share_pct"))
            return {
                "type": "rank",
                "from": int(before),
                "to": int(rank),
                "share_pct": share,
                "spark": [],
            }
    return None


def _primary(kind: str) -> dict[str, str]:
    if kind == "plan_proposal":
        return {"label": "确认计划", "action": "confirm_plan"}
    if kind == "card_proposal":
        return {"label": "确认", "action": "confirm_card"}
    if kind == "card_state":
        return {"label": "查看", "action": "open_card"}
    if kind == "review_ready":
        return {"label": "查看复盘", "action": "open_review"}
    if kind == "guidance":
        return {"label": "查看指引", "action": "open"}
    if kind in {"risk", "opportunity", "sector"}:
        return {"label": "查看详情", "action": "open"}
    return {"label": "知道了", "action": "ack"}


def _decide(kind: str, severity: str) -> bool:
    if kind in {
        "plan_proposal",
        "plan_entry",
        "plan_giveup",
        "card_proposal",
        "card_state",
        "discipline",
        "emergency",
    }:
        return True
    return kind in {"sector", "opportunity"} and severity in {"L2", "L3"}


def _build_signal(
    *,
    ts: datetime,
    kind: str,
    severity: str,
    object_type: str,
    object_code: str,
    object_name: str,
    title: str,
    direction: str,
    conclusion: str,
    brief: str,
    context: Optional[dict[str, Any]],
    source: dict[str, Any],
    rule_id: Optional[str],
    analysis_id: Optional[int],
    detail_available: bool,
    false_positive: bool,
    now: datetime,
) -> Signal:
    status = "done" if false_positive else "new"
    return Signal(
        id=None,
        ts=ts,
        kind=kind,
        decide=_decide(kind, severity),
        severity=severity,
        status=status,
        object_type=object_type,
        object_code=object_code,
        object_name=object_name,
        title=truncate(title, 80),
        direction=direction,
        conclusion=truncate(conclusion, CONCLUSION_LIMIT),
        brief=truncate(brief, BRIEF_LIMIT),
        context=context,
        source=source,
        merged_count=1,
        primary=_primary(kind),
        detail_available=detail_available,
        rule_id=rule_id,
        analysis_id=analysis_id,
        ignored=False,
        folded=false_positive,
        dedupe_key=dedupe_key(object_type, object_code, rule_id),
        created_at=now,
        updated_at=now,
    )


def signal_from_cn_alert(
    alert: dict[str, Any],
    analysis: Optional[Analysis],
    *,
    now: datetime,
) -> Optional[Signal]:
    """Return a Signal, or None when the alert is an unusable / skipped record."""
    try:
        alert_id = int(alert.get("id"))
    except (TypeError, ValueError):
        return None
    try:
        ts = parse_iso(alert.get("ts"))
    except ValueError:
        ts = now
    rule_id = str(alert.get("rule_id") or "")
    rule_type = str(alert.get("rule_type") or "")
    code = str(alert.get("code") or "")
    name = str(alert.get("name") or code)
    if not code or not rule_id:
        return None

    false_positive = is_false_positive(analysis)
    analysis_direction = extract_direction(analysis.markdown) if analysis and analysis.markdown else None
    if analysis_direction:
        direction = analysis_direction
    elif alert.get("direction") == "up":
        direction = "bull"
    elif alert.get("direction") == "down":
        direction = "bear"
    else:
        change = _number(alert.get("change_pct"))
        direction = "bull" if change is not None and change > 0 else "bear" if change is not None and change < 0 else "neutral"
    if false_positive:
        direction = "neutral"
    kind = _cn_kind(rule_type, alert.get("direction"), _number(alert.get("change_pct")), false_positive)
    severity = _severity_from_cn(rule_type)

    conclusion = _cn_conclusion(alert, rule_type)
    brief = ""
    if analysis and analysis.markdown:
        extracted = extract_conclusion(analysis.markdown)
        if extracted:
            conclusion = extracted
        points = extract_points(analysis.markdown)
        if points:
            brief = "；".join(points[:2])
        else:
            brief = extract_detail(analysis.markdown)

    source = {
        "label": "cn-watch",
        "alert_ids": [int(alert_id)],
        "analysis_id": alert_id if analysis is not None else None,
        "plan_id": None,
        "rule_id": rule_id,
    }
    return _build_signal(
        ts=ts,
        kind=kind,
        severity=severity,
        object_type="stock",
        object_code=code,
        object_name=name,
        title=_cn_title(alert, rule_type),
        direction=direction,
        conclusion=conclusion,
        brief=brief,
        context=_context_from_alert(alert),
        source=source,
        rule_id=rule_id,
        analysis_id=alert_id if analysis is not None else None,
        detail_available=bool(analysis and analysis.markdown),
        false_positive=false_positive,
        now=now,
    )


def _market_rule(alert: dict[str, Any]) -> str:
    payload = alert.get("payload")
    if isinstance(payload, dict) and payload.get("rule_id"):
        return str(payload["rule_id"])
    rule_id = str(alert.get("rule_id") or "")
    return rule_id.split(":")[0] if rule_id else ""


def signal_from_market_alert(
    alert: dict[str, Any],
    *,
    now: datetime,
) -> Optional[Signal]:
    try:
        alert_id = int(alert.get("id"))
    except (TypeError, ValueError):
        return None
    try:
        ts = parse_iso(alert.get("ts"))
    except ValueError:
        ts = now
    obj = alert.get("object") if isinstance(alert.get("object"), dict) else {}
    rule = _market_rule(alert)
    payload = alert.get("payload") if isinstance(alert.get("payload"), dict) else {}
    code = str(obj.get("code") or "")
    name = str(obj.get("name") or code)
    if not code:
        return None
    metrics: dict[str, Any] = {}
    objects = payload.get("objects")
    if isinstance(objects, list) and objects and isinstance(objects[0], dict):
        first = objects[0]
        if isinstance(first.get("metrics"), dict):
            metrics = first["metrics"]
        if not code:
            code = str(first.get("code") or "")
            name = str(first.get("name") or code)
    change = _number(payload.get("change_pct"))
    if change is None:
        change = _number(payload.get("index_change_pct"))
    if change is None:
        change = _number(metrics.get("change_pct"))
    if change is None:
        change = _number(metrics.get("sector_change_pct"))
    cross_direction = str(metrics.get("direction") or "")
    rule_id = str(alert.get("rule_id") or rule)

    if rule in {"R1", "R2"}:
        kind = "risk"
        object_type = "market"
        direction = "bear"
    elif rule in {"R3", "R4", "R5"}:
        kind = "sector"
        object_type = "sector"
        if cross_direction == "上穿":
            direction = "bull"
        elif cross_direction == "下穿":
            direction = "bear"
        else:
            direction = "neutral" if change is None else ("bull" if change >= 0 else "bear")
    elif rule == "R6":
        kind = "risk" if change is None or change < 0 else "opportunity"
        object_type = "stock"
        direction = "bear" if kind == "risk" else "bull"
    else:
        kind = "info"
        object_type = str(obj.get("type") or "stock")
        direction = "neutral"

    severity = str(alert.get("severity") or "L2")
    if severity not in SEVERITY_RANK:
        severity = "L2"
    title = str(alert.get("title") or f"{name} {_MARKET_RULE_LABELS.get(rule, '市场异动')}")
    detail = str(alert.get("detail") or "")
    conclusion = truncate(
        detail or f"{name} 触发{_MARKET_RULE_LABELS.get(rule, '市场规则')}", CONCLUSION_LIMIT
    )
    source = {
        "label": "market-watch",
        "alert_ids": [int(alert_id)],
        "analysis_id": _int_or_none(alert.get("analysis_id")),
        "plan_id": None,
        "rule_id": rule_id or rule or None,
    }
    return _build_signal(
        ts=ts,
        kind=kind,
        severity=severity,
        object_type=object_type,
        object_code=code,
        object_name=name,
        title=title,
        direction=direction,
        conclusion=conclusion,
        brief=detail,
        context=_context_from_alert(alert),
        source=source,
        rule_id=rule_id or rule or None,
        analysis_id=_int_or_none(alert.get("analysis_id")),
        detail_available=False,
        false_positive=False,
        now=now,
    )


def _condition_text(condition: dict[str, Any]) -> str:
    cond_type = condition.get("type")
    if cond_type == "price_cross":
        return f"价格{'上穿' if condition.get('direction') == 'up' else '下穿'} {condition.get('level')}"
    if cond_type == "price_in_range":
        return f"价格落在 {condition.get('lo')}–{condition.get('hi')}"
    if cond_type == "pct_change":
        return f"涨跌幅{'≥' if condition.get('direction') == 'up' else '≤-'}{condition.get('threshold_pct')}%"
    return "计划条件"


def plan_signal(plan: Plan, kind: str, *, now: datetime, price: Optional[float]) -> Signal:
    condition = dict(plan.condition)
    level = _number(condition.get("level"))
    lo = _number(condition.get("lo"))
    hi = _number(condition.get("hi"))
    level_lo = level if level is not None else (lo if lo is not None else 0.0)
    level_hi = level if level is not None else (hi if hi is not None else level_lo)
    giveup = kind == "plan_giveup"
    if kind == "plan_entry":
        title = f"{plan.name} 到达进场位"
    elif kind == "plan_giveup":
        title = f"{plan.name} 触及放弃位"
    elif kind == "plan_proposal":
        title = f"{plan.name} 计划待确认"
    else:
        title = f"{plan.name} 计划提醒"
    conclusion = f"{plan.name} {_condition_text(condition)}"
    if price is not None:
        conclusion = f"{conclusion}，现价 {price:.2f}"
    brief = plan.rationale or _condition_text(condition)
    source = {
        "label": "hub",
        "alert_ids": [],
        "analysis_id": plan.source.get("analysis_id") if isinstance(plan.source, dict) else None,
        "plan_id": plan.id,
        "rule_id": None,
    }
    return _build_signal(
        ts=now,
        kind=kind,
        severity="L2",
        object_type="stock",
        object_code=plan.code,
        object_name=plan.name,
        title=title,
        direction="neutral",
        conclusion=conclusion,
        brief=brief,
        context=_context_range(
            level_lo=level_lo,
            level_hi=level_hi,
            stop=plan.stop,
            price=price,
            minimum=level_lo,
            maximum=level_hi,
            giveup=giveup,
        ),
        source=source,
        rule_id=None,
        analysis_id=source["analysis_id"],
        detail_available=False,
        false_positive=False,
        now=now,
    )


def expiry_signal(plan: Plan, *, now: datetime) -> Signal:
    source = {
        "label": "hub",
        "alert_ids": [],
        "analysis_id": plan.source.get("analysis_id") if isinstance(plan.source, dict) else None,
        "plan_id": plan.id,
        "rule_id": None,
    }
    return _build_signal(
        ts=now,
        kind="info",
        severity="L1",
        object_type="stock",
        object_code=plan.code,
        object_name=plan.name,
        title=f"{plan.name} 计划已过期",
        direction="neutral",
        conclusion=f"{plan.name} 的计划在 {fmt_iso(plan.expires_at)} 前未触发",
        brief=plan.rationale,
        context=None,
        source=source,
        rule_id=None,
        analysis_id=source["analysis_id"],
        detail_available=False,
        false_positive=False,
        now=now,
    )


def sort_signals(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, int, float]:
        ts = item.get("ts")
        stamp = ts.timestamp() if isinstance(ts, datetime) else 0.0
        return (
            0 if item.get("decide") else 1,
            -SEVERITY_RANK.get(item.get("severity"), 0),
            -stamp,
        )

    return sorted(items, key=key)


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def signal_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Render a stored signal row exactly as the contract's Signal object."""
    ts = row.get("ts")
    snooze = row.get("snooze_until")
    kind = row.get("kind")
    direction = row.get("direction") or "neutral"
    return {
        "id": row.get("id"),
        "ts": fmt_iso(ts) if isinstance(ts, datetime) else ts,
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "decide": bool(row.get("decide")),
        "severity": row.get("severity"),
        "status": row.get("status"),
        "snooze_until": fmt_iso(snooze) if isinstance(snooze, datetime) else snooze,
        "object": {
            "type": row.get("object_type"),
            "code": row.get("object_code"),
            "name": row.get("object_name"),
        },
        "title": row.get("title"),
        "direction": direction,
        "direction_label": {"bull": "偏多", "bear": "偏空", "neutral": "中性"}.get(direction, "中性"),
        "conclusion": row.get("conclusion"),
        "brief": row.get("brief"),
        "context": row.get("context"),
        "source": row.get("source"),
        "merged_count": row.get("merged_count", 1),
        "primary": row.get("primary"),
        "detail_available": bool(row.get("detail_available")),
    }


def resolve_snooze_until(value: Any, *, now: datetime, calendar: Any) -> datetime:
    from .calendar import next_close, next_open

    if not isinstance(value, str) or not value.strip():
        raise ValueError("until is required for snooze")
    text = value.strip()
    if text == "30m":
        return now + timedelta(minutes=30)
    if text == "close":
        return next_close(calendar, now)
    if text == "next_open":
        return next_open(calendar, now)
    try:
        target = parse_iso(text)
    except ValueError as exc:
        raise ValueError("until must be 30m|close|next_open or an ISO timestamp") from exc
    if target <= now:
        raise ValueError("until must be in the future")
    if target - now > timedelta(days=30):
        raise ValueError("snooze must not exceed 30 days")
    return target


# -- v1.1 playbook signals ----------------------------------------------
def _card_source(card: Any, rule_id: str) -> dict[str, Any]:
    card_id = card.get("id") if isinstance(card, dict) else getattr(card, "id", None)
    return {
        "label": "hub",
        "alert_ids": [],
        "analysis_id": None,
        "plan_id": None,
        "card_id": card_id,
        "rule_id": rule_id,
    }


def _card_value(card: Any, key: str, default: Any = None) -> Any:
    return card.get(key, default) if isinstance(card, dict) else getattr(card, key, default)


def card_proposal_signal(card: Any, *, now: datetime) -> Signal:
    card_id = _card_value(card, "id")
    code = str(_card_value(card, "code", ""))
    name = str(_card_value(card, "name") or code)
    thesis = str(_card_value(card, "thesis", "") or "")
    source = _card_source(card, "card_proposal")
    return _build_signal(
        ts=now,
        kind="card_proposal",
        severity="L2",
        object_type="stock",
        object_code=code,
        object_name=name,
        title=f"{name} 作战卡待确认",
        direction="neutral",
        conclusion=truncate(f"{name} 的作战卡等待确认", CONCLUSION_LIMIT),
        brief=thesis,
        context={"type": "card", "card_id": card_id, "from_state": None, "to_state": "proposed"},
        source=source,
        rule_id=f"card:{card_id}:proposal",
        analysis_id=None,
        detail_available=False,
        false_positive=False,
        now=now,
    )


def card_state_signal(
    card: Any,
    *,
    from_state: Optional[str],
    to_state: str,
    reason: str,
    now: datetime,
    price: Optional[float] = None,
) -> Signal:
    card_id = _card_value(card, "id")
    code = str(_card_value(card, "code", ""))
    name = str(_card_value(card, "name") or code)
    direction = "bull" if to_state in {"await_confirm", "execute"} else (
        "bear" if to_state in {"abandon", "exit"} else "neutral"
    )
    severity = "L3" if to_state in {"abandon", "exit"} else "L2"
    conclusion = reason
    if price is not None:
        conclusion = f"{reason}，现价 {price:.2f}"
    return _build_signal(
        ts=now,
        kind="card_state",
        severity=severity,
        object_type="stock",
        object_code=code,
        object_name=name,
        title=f"{name} {to_state}",
        direction=direction,
        conclusion=truncate(conclusion, CONCLUSION_LIMIT),
        brief=str(_card_value(card, "thesis", "") or ""),
        context={
            "type": "card",
            "card_id": card_id,
            "from_state": from_state,
            "to_state": to_state,
        },
        source=_card_source(card, f"card:{card_id}:{to_state}"),
        rule_id=f"card:{card_id}:{to_state}",
        analysis_id=None,
        detail_available=False,
        false_positive=False,
        now=now,
    )


def review_ready_signal(review: Any, *, now: datetime) -> Signal:
    day = review.get("date") if isinstance(review, dict) else getattr(review, "date", "")
    kind = review.get("kind") if isinstance(review, dict) else getattr(review, "kind", "evening")
    revision = (
        review.get("revision") if isinstance(review, dict) else getattr(review, "revision", 1)
    )
    source = {
        "label": "hub",
        "alert_ids": [],
        "analysis_id": None,
        "plan_id": None,
        "card_id": None,
        "rule_id": f"review:{day}:{kind}",
    }
    label = "晚复盘" if kind == "evening" else "盘前复盘"
    return _build_signal(
        ts=now,
        kind="review_ready",
        severity="L1",
        object_type="market",
        object_code="review",
        object_name=f"{day} {label}",
        title=f"{day} {label}已生成",
        direction="neutral",
        conclusion=truncate(f"{day} {label}已保存（第 {revision} 版）", CONCLUSION_LIMIT),
        brief="复盘页可查看结构化结果",
        context={"type": "review", "date": day, "kind": kind, "revision": revision},
        source=source,
        rule_id=f"review:{day}:{kind}",
        analysis_id=None,
        detail_available=False,
        false_positive=False,
        now=now,
    )


def discipline_signal(reason: Mapping[str, Any], *, now: datetime) -> Signal:
    text = str(reason.get("text") or "纪律暂停")
    rule = str(reason.get("rule") or "discipline")
    source = {
        "label": "hub",
        "alert_ids": [],
        "analysis_id": None,
        "plan_id": None,
        "card_id": None,
        "rule_id": f"discipline:{rule}",
    }
    return _build_signal(
        ts=now,
        kind="discipline",
        severity="L3",
        object_type="market",
        object_code="discipline",
        object_name="纪律暂停",
        title=f"纪律暂停：{text}",
        direction="neutral",
        conclusion=truncate(text, CONCLUSION_LIMIT),
        brief="暂停只是提示，不阻断任何操作；请按既定纪律处理",
        context={
            "type": "discipline",
            "rule": rule,
            "value": reason.get("value"),
            "threshold": reason.get("threshold"),
        },
        source=source,
        rule_id=f"discipline:{rule}",
        analysis_id=None,
        detail_available=False,
        false_positive=False,
        now=now,
    )


def guidance_signal(context: Mapping[str, Any], *, day: str, slot: str, now: datetime) -> Signal:
    market = context.get("market_state") if isinstance(context.get("market_state"), Mapping) else {}
    label = str(market.get("label") or "未知")
    theme = str(context.get("theme_state") or "未知")
    cards = context.get("cards") if isinstance(context.get("cards"), list) else []
    conclusion = f"{slot} 指引：{label}·题材{theme}，{len(cards)} 张作战卡"
    brief = (
        f"当前动作 {context.get('current_action') or '无预案'}；"
        f"下一检查 {context.get('next_check') or '15:00'}；"
        f"风险边界 {context.get('risk_bound') or '未设置'}"
    )
    rule_id = f"guidance:{day}:{slot}"
    source = {
        "label": "hub",
        "alert_ids": [],
        "analysis_id": None,
        "plan_id": None,
        "card_id": None,
        "rule_id": rule_id,
    }
    return _build_signal(
        ts=now,
        kind="guidance",
        severity="L1",
        object_type="market",
        object_code="guidance",
        object_name=f"{day} {slot} 指引",
        title=f"盘中指引 {slot}",
        direction="neutral",
        conclusion=truncate(conclusion, CONCLUSION_LIMIT),
        brief=truncate(brief, BRIEF_LIMIT),
        context=dict(context),
        source=source,
        rule_id=rule_id,
        analysis_id=None,
        detail_available=False,
        false_positive=False,
        now=now,
    )


def emergency_signal(hit: Mapping[str, Any], *, now: datetime) -> Signal:
    from .emergency import EMERGENCY_STEPS, hit_label

    reason = str(hit.get("reason") or "emergency")
    label = hit_label(reason)
    detail = str(hit.get("detail") or "")
    steps = list(EMERGENCY_STEPS)
    conclusion = f"{label}：{detail}" if detail else label
    source = {
        "label": "hub",
        "alert_ids": [],
        "analysis_id": None,
        "plan_id": None,
        "card_id": None,
        "rule_id": f"emergency:{reason}",
    }
    return _build_signal(
        ts=now,
        kind="emergency",
        severity="L3",
        object_type="market",
        object_code="emergency",
        object_name="应急",
        title=f"应急：{label}",
        direction="bear",
        conclusion=truncate(conclusion, CONCLUSION_LIMIT),
        brief=truncate("→".join(steps), BRIEF_LIMIT),
        context={
            "type": "emergency",
            "reason": reason,
            "label": label,
            "detail": detail,
            "steps": steps,
        },
        source=source,
        rule_id=f"emergency:{reason}",
        analysis_id=None,
        detail_available=False,
        false_positive=False,
        now=now,
    )
