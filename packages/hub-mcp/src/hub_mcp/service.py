"""Tool implementations: signals, plans, reviews, settings and playbook cards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

from hub_mcp.card_schema import PROPOSED_MESSAGE as CARD_PROPOSED_MESSAGE
from hub_mcp.card_schema import validate_card
from hub_mcp.client import HubClient
from hub_mcp.envelope import error_payload, ok_payload
from hub_mcp.errors import HubError, ToolError
from hub_mcp.review_schema import validate_review
from hub_mcp.setting_schema import (
    SUGGESTED_MESSAGE,
    spec_for,
    validate_basis,
    validate_value,
)
from hub_mcp.validation import (
    clean_rationale,
    normalize_code,
    safe_date,
    validate_analysis_id,
    validate_condition,
    validate_expires_in_days,
    validate_kind,
    validate_stop,
)

CN_TZ = timezone(timedelta(hours=8))
SIGNAL_STATUSES = {"active", "snoozed", "done", "all"}
PLAN_STATUSES = {"proposed", "active", "triggered", "expired", "cancelled", "all"}
CARD_STATUSES = {"proposed", "active", "closed", "all"}
CARD_PROPOSED_BY = "agent"
PROPOSED_MESSAGE = "已提交，等待用户在「盯盘/我的」页确认后才会生效"
MAX_DETAIL_CHARS = 4000
MAX_STATS_DAYS = 365
_SIGNAL_KEYS = ("id", "ts", "kind", "object", "title", "direction", "conclusion", "brief", "status")


def _now_cn() -> datetime:
    return datetime.now(CN_TZ)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _slim_signal(raw: Any) -> dict[str, Any]:
    item = raw if isinstance(raw, dict) else {}
    obj = item.get("object")
    signal = {key: item.get(key) for key in _SIGNAL_KEYS}
    signal["object"] = (
        {key: obj.get(key) for key in ("type", "code", "name")} if isinstance(obj, dict) else {}
    )
    return signal


def _analysis_sections(raw: Any) -> dict[str, Any]:
    """Accept the real hub's ``{markdown, sections}`` or an already-flat dict."""
    block = raw if isinstance(raw, dict) else {}
    sections = block.get("sections")
    if not isinstance(sections, dict):
        sections = block if any(key in block for key in ("conclusion", "direction", "points", "detail")) else {}
    points = sections.get("points")
    clean_points = [str(item) for item in points if isinstance(item, (str, int, float))] if isinstance(points, list) else []
    conclusion = sections.get("conclusion")
    direction = sections.get("direction")
    if direction not in {"bull", "bear", "neutral"}:
        direction = "neutral"
    detail = sections.get("detail")
    return {
        "conclusion": conclusion if isinstance(conclusion, str) else "",
        "direction": direction,
        "points": clean_points[:8],
        "detail": _truncate(detail if isinstance(detail, str) else "", MAX_DETAIL_CHARS),
    }


def _business_error(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("ok") is not False:
        return None
    error = payload.get("error")
    error = error if isinstance(error, dict) else {}
    return error_payload(
        str(error.get("code") or "hub_error"),
        str(error.get("message") or "chives-hub 返回错误"),
    )


def _handle_tool_errors(method: Callable[[Any, dict[str, Any]], dict[str, Any]]) -> Callable[[Any, dict[str, Any]], dict[str, Any]]:
    @wraps(method)
    def wrapper(self: Any, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return method(self, args)
        except ToolError as exc:
            return error_payload(exc.code, exc.message)

    return wrapper


def _require_int(value: Any, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ToolError("invalid_value", f"{field} 必须是 ≥{minimum} 的整数", field=field)
    return value


class HubService:
    def __init__(self, client: HubClient) -> None:
        self.client = client

    # -- reads -----------------------------------------------------------
    @_handle_tool_errors
    def list_signals(self, args: dict[str, Any]) -> dict[str, Any]:
        status = args.get("status", "active")
        if not isinstance(status, str) or status not in SIGNAL_STATUSES:
            raise ToolError("invalid_value", "status 只接受 active/snoozed/done/all", field="status")
        decide = args.get("decide")
        decide_query: str | None = None
        if decide is not None:
            if isinstance(decide, bool):
                decide_query = "1" if decide else "0"
            elif isinstance(decide, int) and decide in (0, 1):
                decide_query = str(decide)
            else:
                raise ToolError("invalid_value", "decide 只接受 true/false/null", field="decide")
        limit = args.get("limit", 20)
        limit = _require_int(limit, "limit")
        if limit > 200:
            raise ToolError("invalid_value", "limit 必须在 1..200", field="limit")
        payload = self.client.get_json(
            "/signals",
            [
                ("status", status),
                ("decide", decide_query),
                ("limit", limit),
            ],
        )
        error = _business_error(payload)
        if error is not None:
            return error
        rows = payload.get("signals")
        signals = [_slim_signal(row) for row in rows] if isinstance(rows, list) else []
        return ok_payload(
            signals=signals,
            counts=payload.get("counts") if isinstance(payload.get("counts"), dict) else {},
            hub_as_of=payload.get("as_of"),
        )

    @_handle_tool_errors
    def get_signal(self, args: dict[str, Any]) -> dict[str, Any]:
        signal_id = _require_int(args.get("id"), "id")
        payload = self.client.get_json(f"/signals/{signal_id}")
        error = _business_error(payload)
        if error is not None:
            return error
        raw_signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else payload
        return ok_payload(
            signal=_slim_signal(raw_signal),
            analysis=_analysis_sections(payload.get("analysis")),
            untrusted_text=True,
        )

    @_handle_tool_errors
    def list_plans(self, args: dict[str, Any]) -> dict[str, Any]:
        status = args.get("status", "all")
        if not isinstance(status, str) or status not in PLAN_STATUSES:
            raise ToolError(
                "invalid_value",
                "status 只接受 proposed/active/triggered/expired/cancelled/all",
                field="status",
            )
        payload = self.client.get_json("/plans", [("status", status)])
        error = _business_error(payload)
        if error is not None:
            return error
        rows = payload.get("plans")
        plans = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        return ok_payload(
            plans=plans,
            counts=payload.get("counts") if isinstance(payload.get("counts"), dict) else {},
            hub_as_of=payload.get("as_of"),
        )

    # -- writes ----------------------------------------------------------
    @_handle_tool_errors
    def propose_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        code = normalize_code(args.get("code"))
        kind = validate_kind(args.get("kind"))
        condition = validate_condition(args.get("condition"))
        rationale = clean_rationale(args.get("rationale"))
        stop = validate_stop(args.get("stop"))
        days = validate_expires_in_days(args.get("expires_in_days", 5))
        analysis_id = validate_analysis_id(args.get("analysis_id"))
        expires_at = (_now_cn() + timedelta(days=days)).isoformat(timespec="seconds")
        body = {
            "code": code,
            "kind": kind,
            "condition": condition,
            "stop": stop,
            "rationale": rationale,
            "source": {"analysis_id": analysis_id, "label": "agent"},
            # Fixed by construction: the tool schema exposes neither field.
            "proposed_by": "agent",
            "expires_at": expires_at,
        }
        payload = self.client.post_json("/plans", body)
        error = _business_error(payload)
        if error is not None:
            return error
        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        return ok_payload(
            plan=plan,
            status="proposed",
            proposed_by="agent",
            message=PROPOSED_MESSAGE,
        )

    @_handle_tool_errors
    def cancel_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        plan_id = _require_int(args.get("id"), "id")
        plan = self._get_plan(plan_id)
        if plan is None:
            return error_payload("plan_not_found", f"计划 {plan_id} 不存在")
        if plan.get("proposed_by") != "agent":
            return error_payload("not_agent_plan", "只能取消由智能体提议的计划")
        if plan.get("status") != "proposed":
            return error_payload(
                "invalid_status",
                f"只有 proposed 状态的计划可以取消（当前 {plan.get('status')}）",
            )
        payload = self.client.post_json(f"/plans/{plan_id}/action", {"action": "cancel"})
        error = _business_error(payload)
        if error is not None:
            return error
        updated = payload.get("plan") if isinstance(payload.get("plan"), dict) else plan
        return ok_payload(plan=updated, status="cancelled", message="已取消该待确认计划")

    # -- reviews (hub v1.1) ----------------------------------------------
    @_handle_tool_errors
    def get_review_data(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self.client.get_json("/review-data")
        error = _business_error(payload)
        if error is not None:
            return error
        fields = {
            key: value
            for key, value in payload.items()
            if key not in {"ok", "private", "untrusted_text"}
        }
        if payload.get("trading_day") is False:
            # Contract: a non-trading day returns only the four-field short packet.
            return ok_payload(**fields)
        # The holdings block is private, every text field is untrusted data.
        return ok_payload(private=True, untrusted_text=True, **fields)

    @_handle_tool_errors
    def save_review(self, args: dict[str, Any]) -> dict[str, Any]:
        review = args.get("review", args)
        validated = validate_review(review)
        payload = self.client.post_json("/reviews", validated)
        error = _business_error(payload)
        if error is not None:
            return error
        revision = payload.get("revision")
        if revision is None and isinstance(payload.get("review"), dict):
            revision = payload["review"].get("revision")
        return ok_payload(
            date=validated["date"],
            kind=validated["kind"],
            revision=revision,
            status="saved",
            message="复盘已保存；「复盘」页读取的是 hub 里的结构化结果",
        )

    # -- settings (agent may only suggest) -------------------------------
    @_handle_tool_errors
    def list_settings(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self.client.get_json("/settings")
        error = _business_error(payload)
        if error is not None:
            return error
        rows = payload.get("settings")
        settings = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        return ok_payload(
            settings=settings,
            count=len(settings),
            hub_as_of=payload.get("as_of"),
            note="只读；建议用 hub_suggest_setting 提交，采纳由用户在「复盘」页完成",
        )

    @_handle_tool_errors
    def suggest_setting(self, args: dict[str, Any]) -> dict[str, Any]:
        spec = spec_for(args.get("key"))
        value = validate_value(spec, args.get("value"))
        basis = validate_basis(args.get("basis"))
        payload = self.client.post_json(
            f"/settings/{spec.key}/suggest",
            {"value": value, "basis": basis},
        )
        error = _business_error(payload)
        if error is not None:
            return error
        setting = payload.get("setting")
        fields: dict[str, Any] = {
            "key": spec.key,
            "suggested_value": value,
            "status": "suggested",
            "message": SUGGESTED_MESSAGE,
        }
        if isinstance(setting, dict):
            fields["setting"] = setting
        return ok_payload(**fields)

    # -- playbook cards (propose / cancel only) -------------------------
    @_handle_tool_errors
    def propose_card(self, args: dict[str, Any]) -> dict[str, Any]:
        card = args.get("card", args)
        validated = validate_card(card)
        body = {**validated, "proposed_by": CARD_PROPOSED_BY}
        payload = self.client.post_json("/cards", body)
        error = _business_error(payload)
        if error is not None:
            return error
        stored = payload.get("card") if isinstance(payload.get("card"), dict) else {}
        warnings = payload.get("warnings")
        return ok_payload(
            card=stored,
            status="proposed",
            proposed_by=CARD_PROPOSED_BY,
            warnings=warnings if isinstance(warnings, list) else [],
            message=CARD_PROPOSED_MESSAGE,
        )

    @_handle_tool_errors
    def list_cards(self, args: dict[str, Any]) -> dict[str, Any]:
        status = args.get("status", "all")
        if not isinstance(status, str) or status not in CARD_STATUSES:
            raise ToolError("invalid_value", "status 只接受 proposed/active/closed/all", field="status")
        date = args.get("date")
        date = safe_date(date, "date") if date is not None else None
        payload = self.client.get_json("/cards", [("status", status), ("date", date)])
        error = _business_error(payload)
        if error is not None:
            return error
        rows = payload.get("cards")
        cards = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        return ok_payload(
            cards=cards,
            counts=payload.get("counts") if isinstance(payload.get("counts"), dict) else {},
            hub_as_of=payload.get("as_of"),
            untrusted_text=True,
        )

    @_handle_tool_errors
    def get_card(self, args: dict[str, Any]) -> dict[str, Any]:
        card_id = _require_int(args.get("id"), "id")
        card = self._get_card(card_id)
        if card is None:
            return error_payload("card_not_found", f"作战卡 {card_id} 不存在")
        return ok_payload(card=card, untrusted_text=True)

    @_handle_tool_errors
    def candidate_stats(self, args: dict[str, Any]) -> dict[str, Any]:
        days = _require_int(args.get("days", 20), "days")
        if days > MAX_STATS_DAYS:
            raise ToolError("invalid_value", f"days 必须在 1..{MAX_STATS_DAYS}", field="days")
        payload = self.client.get_json("/candidates/stats", [("days", days)])
        error = _business_error(payload)
        if error is not None:
            return error
        return ok_payload(**{key: value for key, value in payload.items() if key != "ok"})

    @_handle_tool_errors
    def cancel_card(self, args: dict[str, Any]) -> dict[str, Any]:
        card_id = _require_int(args.get("id"), "id")
        card = self._get_card(card_id)
        if card is None:
            return error_payload("card_not_found", f"作战卡 {card_id} 不存在")
        if card.get("proposed_by") != CARD_PROPOSED_BY:
            return error_payload("not_agent_card", "只能取消由智能体提议的作战卡")
        if card.get("status") != "proposed":
            return error_payload(
                "invalid_status",
                f"只有 proposed 状态的作战卡可以取消（当前 {card.get('status')}）",
            )
        payload = self.client.post_json(f"/cards/{card_id}/action", {"action": "cancel"})
        error = _business_error(payload)
        if error is not None:
            return error
        updated = payload.get("card") if isinstance(payload.get("card"), dict) else card
        return ok_payload(card=updated, status="cancelled", message="已取消该待确认作战卡")

    # -- internals -------------------------------------------------------
    def _get_card(self, card_id: int) -> dict[str, Any] | None:
        payload = self.client.get_json(f"/cards/{card_id}")
        if payload.get("ok") is False:
            error = payload.get("error")
            error = error if isinstance(error, dict) else {}
            code = str(error.get("code") or "hub_error")
            if code in {"card_not_found", "not_found"}:
                return None
            raise HubError(code, str(error.get("message") or "chives-hub 返回错误"))
        card = payload.get("card")
        return card if isinstance(card, dict) else None
    def _get_plan(self, plan_id: int) -> dict[str, Any] | None:
        payload = self.client.get_json(f"/plans/{plan_id}")
        if payload.get("ok") is not False:
            plan = payload.get("plan")
            if isinstance(plan, dict):
                return plan
        # The v1 contract only guarantees the list endpoint; fall back to it.
        payload = self.client.get_json("/plans", [("status", "all")])
        error = _business_error(payload)
        if error is not None:
            raise HubError(str(error["error"]["code"]), str(error["error"]["message"]))
        rows = payload.get("plans")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("id") == plan_id:
                    return row
        return None
