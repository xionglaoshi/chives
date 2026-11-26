"""Delegate battle-card evaluation to chives-radar plan rules.

The hub no longer evaluates conditions.  When a card becomes active it pushes a
``Plan`` (``id = card-<card id>``) to cn-watch; every tick it reads ``GET
/plans`` and mirrors ``state``/``last_price``/``conds``/``history`` back.  State
transitions keep the T106 side effects (``card_state`` signal, trigger for
``execute``/``abandon``/``exit`` and a frozen context pack), but only once per
transition.

Failure policy: an unreachable cn-watch never changes a card's state (only the
top-level engine flag), a rejected upsert keeps the card active and records
``engine.error`` with exponential backoff, and reconciliation touches only plans
whose id carries the ``card-`` prefix.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Optional

from .cards import CARD_STATES, empty_conds, normalize_conds
from .models import CN_TZ, fmt_iso, parse_iso
from .sources import SourceError, UpstreamRejection

logger = logging.getLogger("chives_signals.plan_sync")

PLAN_PREFIX = "card-"
LIVE_CARD_STATES = ("observe", "await_confirm", "execute")
COND_FIELD = {
    "market": "market_conditions",
    "sector": "sector_conditions",
    "stock": "stock_conditions",
    "giveup": "giveup",
}
DEFAULT_BACKOFF = (3.0, 6.0, 12.0, 30.0, 60.0)
HOLDINGS_REFRESH_SECONDS = 30.0
MAX_LABEL = 40


def plan_id_for(card_id: Any) -> str:
    return f"{PLAN_PREFIX}{int(card_id)}"


def card_id_for(plan_id: Any) -> Optional[int]:
    if not isinstance(plan_id, str) or not plan_id.startswith(PLAN_PREFIX):
        return None
    try:
        return int(plan_id[len(PLAN_PREFIX) :])
    except ValueError:
        return None


def is_live_card(card: Mapping[str, Any], now: Optional[datetime] = None) -> bool:
    if card.get("status") != "active":
        return False
    if card.get("state") not in LIVE_CARD_STATES:
        return False
    if now is not None and card.get("expires_at") is not None:
        return card["expires_at"] > now
    return True


def plan_label(card: Mapping[str, Any]) -> str:
    name = str(card.get("name") or card.get("code") or "").strip()
    suffix = " 作战卡"
    return f"{name[: MAX_LABEL - len(suffix)]}{suffix}"


def plan_payload(card: Mapping[str, Any], *, held: bool) -> dict[str, Any]:
    """Map one card onto the chives-radar Plan schema (no size, cost or cash)."""
    risk = card.get("risk") or {}
    stop = risk.get("stop_price")
    return {
        "id": plan_id_for(card["id"]),
        "code": card["code"],
        "market": list(card.get("market_conditions") or []),
        "sector": list(card.get("sector_conditions") or []),
        "stock": list(card.get("stock_conditions") or []),
        "policy": card.get("confirm_policy") or "all",
        "giveup": list(card.get("giveup") or []),
        "stop_price": float(stop) if isinstance(stop, (int, float)) else None,
        "held": bool(held),
        "expires_at": fmt_iso(card.get("expires_at")),
        "label": plan_label(card),
    }


def _signature(plan: Mapping[str, Any]) -> str:
    return json.dumps(dict(plan), sort_keys=True, ensure_ascii=False, allow_nan=False)


def _engine_error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": f"{code}: {message}"[:300]}


def _reason(exc: BaseException) -> str:
    code = getattr(exc, "code", None) or type(exc).__name__
    return f"{code}: {exc}"[:300]


class CardPlanSync:
    """Push active cards to chives-radar and mirror the evaluated plan states."""

    def __init__(
        self,
        *,
        store: Any,
        client: Any,
        clock: Callable[[], datetime],
        overview_provider: Callable[[datetime], Mapping[str, Any]],
        on_transition: Callable[..., Any],
        backoff: Iterable[float] = DEFAULT_BACKOFF,
        holdings_refresh_seconds: float = HOLDINGS_REFRESH_SECONDS,
    ) -> None:
        self.store = store
        self.client = client
        self.clock = clock
        self.overview_provider = overview_provider
        self.on_transition = on_transition
        self.backoff = tuple(float(value) for value in backoff) or DEFAULT_BACKOFF
        self.holdings_refresh_seconds = float(holdings_refresh_seconds)
        self.ok: Optional[bool] = None
        self.reason: Optional[str] = None
        self._pushed: dict[str, str] = {}
        self._pushed_held: dict[str, bool] = {}
        self._next_try: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}
        self._startup = True
        self._held: set[str] = set()
        self._held_at: Optional[datetime] = None
        self._held_loaded = False

    # -- status ----------------------------------------------------------
    def status_payload(self) -> dict[str, Any]:
        if self.ok is False:
            return {"ok": False, "reason": self.reason or "engine_unreachable"}
        return {"ok": True}

    # -- holdings --------------------------------------------------------
    def _holdings(self, now: datetime, *, force: bool = False) -> set[str]:
        stale = (
            self._held_at is None
            or (now - self._held_at).total_seconds() >= self.holdings_refresh_seconds
        )
        if force or not self._held_loaded or stale:
            try:
                overview = self.overview_provider(now)
            except Exception:  # noqa: BLE001 - keep the last known held set
                overview = None
            if isinstance(overview, Mapping):
                self._held = {
                    str(item.get("code"))
                    for item in overview.get("positions") or []
                    if isinstance(item, Mapping) and item.get("code")
                }
                self._held_loaded = True
            self._held_at = now
        return self._held

    # -- push ------------------------------------------------------------
    def push_card(
        self, card: Mapping[str, Any], now: datetime, *, force: bool = False
    ) -> dict[str, Any]:
        """Push one live card.  Never raises for upstream failures."""
        if not is_live_card(card, now):
            return {"ok": False, "rejected": False, "code": "not_live"}
        plan = plan_payload(card, held=card["code"] in self._holdings(now, force=True))
        plan_id = plan["id"]
        if not force and self._in_backoff(plan_id, now):
            return {"ok": False, "rejected": False, "code": "backoff"}
        try:
            result = self.client.upsert_plan(plan, now=now)
        except UpstreamRejection as exc:
            self._note_failure(plan_id, now)
            self._store_engine(card["id"], _engine_error(exc.code, str(exc)), now)
            return {"ok": False, "rejected": True, "code": exc.code}
        except SourceError as exc:
            self._mark_down(exc)
            self._note_failure(plan_id, now)
            self._store_engine(card["id"], _engine_error(exc.code, str(exc)), now)
            return {"ok": False, "rejected": False, "code": exc.code}
        self._clear_failure(plan_id)
        self._pushed[plan_id] = _signature(plan)
        self._pushed_held[plan_id] = bool(plan["held"])
        self._store_engine(card["id"], {"ok": True, "error": None, "synced_at": fmt_iso(now)}, now)
        remote = result.get("plan") if isinstance(result, Mapping) else None
        return {"ok": True, "rejected": False, "code": None, "plan": remote}

    def remove_card(
        self, card_id: Any, now: datetime, *, reason: str = "card_not_active"
    ) -> bool:
        return self.remove_plan(plan_id_for(card_id), now, reason=reason)

    def remove_plan(self, plan_id: str, now: datetime, *, reason: str = "removed") -> bool:
        if not str(plan_id).startswith(PLAN_PREFIX):
            return False
        try:
            self.client.remove_plan(plan_id, now=now)
        except UpstreamRejection as exc:
            if exc.code == "not_found":
                self._forget(plan_id)
                return True
            self._note_failure(plan_id, now)
            logger.warning("plan remove rejected: %s", exc.code)
            return False
        except SourceError as exc:
            self._mark_down(exc)
            self._note_failure(plan_id, now)
            return False
        self._forget(plan_id)
        return True

    # -- sync ------------------------------------------------------------
    def sync(self, now: datetime) -> None:
        try:
            payload = self.client.plans(now=now)
        except SourceError as exc:
            self._mark_down(exc)
            return
        except Exception as exc:  # noqa: BLE001 - an upstream bug is not fatal
            self._mark_down(exc)
            return
        self.ok = True
        self.reason = None
        plans = payload.get("plans") if isinstance(payload, Mapping) else None
        remote = {
            str(item["id"]): item
            for item in plans or []
            if isinstance(item, Mapping) and str(item.get("id") or "").startswith(PLAN_PREFIX)
        }
        cards = [
            card
            for card in self.store.list_cards(status="active")
            if is_live_card(card, now)
        ]
        desired: dict[str, dict[str, Any]] = {}
        held = self._holdings(now)
        for card in cards:
            plan = plan_payload(card, held=card["code"] in held)
            desired[plan["id"]] = plan
            if self._needs_push(card, plan, remote.get(plan["id"]), now):
                pushed = self.push_card(card, now, force=not self._needs_backoff(plan["id"], now))
                if pushed.get("plan"):
                    remote[plan["id"]] = pushed["plan"]
        for plan_id, state in remote.items():
            if plan_id in desired:
                continue
            if self._in_backoff(plan_id, now) or self._needs_backoff(plan_id, now):
                continue
            self.remove_plan(plan_id, now)
        for card in cards:
            state = remote.get(plan_id_for(card["id"]))
            if not isinstance(state, Mapping):
                continue
            if state.get("state") == "expired":
                self.remove_plan(plan_id_for(card["id"]), now, reason="plan_expired")
                self.store.update_card(card["id"], status="expired", now=now)
                continue
            self._mirror(card, state, now)
        self._startup = False

    def _needs_push(
        self,
        card: Mapping[str, Any],
        plan: Mapping[str, Any],
        remote: Optional[Mapping[str, Any]],
        now: datetime,
    ) -> bool:
        if self._startup:
            return not self._needs_backoff(plan["id"], now)
        if remote is None:
            return not self._needs_backoff(plan["id"], now)
        if self._pushed.get(plan["id"]) != _signature(plan):
            return not self._needs_backoff(plan["id"], now)
        if remote.get("held") is not None and bool(remote.get("held")) != bool(plan["held"]):
            return True
        if remote.get("active") is False:
            return True
        if str(remote.get("expires_at") or "") != str(plan.get("expires_at") or ""):
            return True
        if str(remote.get("label") or "") != str(plan.get("label") or ""):
            return True
        return False

    # -- mirror ----------------------------------------------------------
    def _mirror(self, card: Mapping[str, Any], state: Mapping[str, Any], now: datetime) -> None:
        new_state = state.get("state")
        if new_state not in CARD_STATES:
            return
        entries = _history_entries(state.get("history"))
        local = self.store.list_card_history(card["id"])
        seen = {_entry_key(entry) for entry in local}
        transition = None
        if card.get("state") != new_state:
            transition = _pick_transition(entries, new_state)
            if transition is None:
                try:
                    since = parse_iso(state.get("since"))
                except ValueError:
                    since = now
                transition = {
                    "ts": since,
                    "from": card.get("state"),
                    "to": new_state,
                    "reason": f"cn-watch 状态同步为 {new_state}",
                }
            elif _entry_key(transition) in seen:
                # The transition is already in local history but the card row was
                # rolled back (or reset); stamp the new detection instead of
                # duplicating an old timestamp.
                transition = dict(transition, ts=now)
        for entry in entries:
            if entry is transition:
                continue
            key = _entry_key(entry)
            if key in seen:
                continue
            self.store.append_card_history(
                card["id"],
                from_state=entry.get("from"),
                to_state=entry["to"],
                reason=entry.get("reason") or "",
                now=entry["ts"],
            )
            seen.add(key)
        updates: dict[str, Any] = {
            "conds": normalize_conds(state.get("conds")),
            "engine": {"ok": True, "error": None, "synced_at": fmt_iso(now)},
        }
        price = state.get("last_price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            updates["last_price"] = float(price)
        if transition is not None:
            self.on_transition(
                card,
                old_state=transition.get("from") or card.get("state"),
                new_state=new_state,
                reason=str(transition.get("reason") or f"cn-watch 状态 {new_state}"),
                now=transition["ts"],
                price=float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) else None,
            )
        self.store.update_card(card["id"], now=now, **updates)

    # -- bookkeeping -----------------------------------------------------
    def _store_engine(self, card_id: int, engine: Mapping[str, Any], now: datetime) -> None:
        self.store.update_card(int(card_id), now=now, engine=dict(engine))

    def _mark_down(self, exc: BaseException) -> None:
        self.ok = False
        self.reason = _reason(exc)

    def _forget(self, plan_id: str) -> None:
        self._pushed.pop(plan_id, None)
        self._pushed_held.pop(plan_id, None)
        self._next_try.pop(plan_id, None)
        self._failures.pop(plan_id, None)

    def _in_backoff(self, plan_id: str, now: datetime) -> bool:
        next_try = self._next_try.get(plan_id)
        return next_try is not None and now < next_try

    def _needs_backoff(self, plan_id: str, now: datetime) -> bool:
        return self._in_backoff(plan_id, now)

    def _note_failure(self, plan_id: str, now: datetime) -> None:
        count = self._failures.get(plan_id, 0) + 1
        self._failures[plan_id] = count
        delay = self.backoff[min(count - 1, len(self.backoff) - 1)]
        self._next_try[plan_id] = now + timedelta(seconds=delay)

    def _clear_failure(self, plan_id: str) -> None:
        self._failures.pop(plan_id, None)
        self._next_try.pop(plan_id, None)


# -- history helpers -----------------------------------------------------
def _history_entries(raw: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, Mapping):
            continue
        to_state = item.get("to")
        if to_state not in CARD_STATES:
            continue
        try:
            moment = parse_iso(item.get("ts"))
        except (TypeError, ValueError):
            continue
        from_state = item.get("from")
        entries.append(
            {
                "ts": moment,
                "from": from_state if from_state in CARD_STATES else None,
                "to": to_state,
                "reason": str(item.get("reason") or ""),
            }
        )
    return entries


def _entry_key(entry: Mapping[str, Any]) -> tuple[str, str]:
    moment = entry.get("ts")
    stamp = fmt_iso(moment) if isinstance(moment, datetime) else str(moment)
    return (stamp, str(entry.get("to")))


def _pick_transition(
    entries: list[dict[str, Any]], new_state: str
) -> Optional[dict[str, Any]]:
    for entry in reversed(entries):
        if entry["to"] == new_state:
            return entry
    return None


def card_conds(card: Mapping[str, Any]) -> dict[str, list[Optional[bool]]]:
    return normalize_conds(card.get("conds"))


def empty_card_conds() -> dict[str, list[Optional[bool]]]:
    return empty_conds()


def local_iso(value: Optional[datetime]) -> Optional[str]:
    return fmt_iso(value.astimezone(CN_TZ) if value else None)
