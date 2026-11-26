"""Deterministic hub engine: poll upstreams -> process signals -> evaluate plans.

No model is called anywhere.  Every network failure degrades gracefully: the
health payload names the dead source while already stored signals stay
available, and plan evaluation simply skips codes whose price is missing.
"""

from __future__ import annotations

import copy
import logging
import threading
from datetime import datetime, time, timedelta
from typing import Any, Mapping, Optional

from .calendar import TradingCalendar
from .cards import (
    apply_action as apply_card_action,
    card_payload,
    create_card as create_card_row,
    is_locked,
    lock_moment,
    normalize_card_code,
)
from .config import HubConfig
from .discipline import (
    apply_loss_streak,
    apply_mood,
    discipline_payload,
    headroom,
)
from .emergency import (
    LIMIT_DOWN_THRESHOLD_KEY,
    INDEX_THRESHOLD_KEY,
    evaluate as evaluate_emergency,
    market_session,
)
from .guidance import (
    due_slot,
    guidance_context,
    theme_snapshot,
)
from .models import CN_TZ, Analysis, Signal, fmt_iso, parse_iso
from .plans import (
    PlanError,
    apply_action,
    condition_met,
    create_plan,
    trigger_kind,
)
from .plan_sync import CardPlanSync, is_live_card, plan_id_for
from .portfolio_view import PortfolioView
from .quotes import latest_price, quotes_for
from .reviews import (
    build_review_data,
    review_detail_payload,
    review_list_payload,
    validate_review,
)
from .settings import SettingsService
from .signals import (
    analysis_sections,
    analysis_skipped,
    card_proposal_signal,
    card_state_signal,
    dedupe_key,
    discipline_signal,
    emergency_signal,
    expiry_signal,
    extract_conclusion,
    extract_detail,
    extract_direction,
    extract_points,
    guidance_signal,
    is_false_positive,
    merge_since,
    plan_signal,
    resolve_snooze_until,
    review_ready_signal,
    signal_from_cn_alert,
    signal_from_market_alert,
    signal_payload,
    sort_signals,
)
from .snapshots import SnapshotService
from .sources import Sources
from .spark import SparkService
from .stats import build_outcome, stats_payload
from .store import HubStore
from .triggers import (
    CARD_TRIGGER_KINDS,
    build_context_pack,
    judged_signal_text,
    judgement_payload,
    trigger_dedupe_key,
    trigger_payload,
    validate_judgement,
)
from .validation import ApiError

logger = logging.getLogger("chives_signals.engine")

PLAN_STATUSES = ("proposed", "active", "triggered", "expired", "cancelled", "all")
SIGNAL_ACTIONS = {"ack", "ignore", "snooze", "unsnooze", "done", "reopen"}


class SignalActionError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 200) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class HubEngine:
    def __init__(
        self,
        config: HubConfig,
        *,
        clock: Optional[Any] = None,
        store: Optional[HubStore] = None,
        sources: Optional[Any] = None,
        portfolio: Optional[Any] = None,
        calendar: Optional[TradingCalendar] = None,
        snapshot_service: Optional[Any] = None,
        spark_service: Optional[Any] = None,
    ) -> None:
        self.config = config
        self._clock = clock or (lambda: datetime.now(CN_TZ))
        self.store = store or HubStore(config.db_path)
        self.calendar = calendar or TradingCalendar.from_file(config.calendar_file)
        self.sources = sources or Sources(config)
        self.spark = spark_service or SparkService(
            config,
            client=getattr(self.sources, "http", None),
            calendar=self.calendar,
            clock=self._clock,
        )
        self.portfolio = portfolio or PortfolioView(
            self.store, profile_dir=config.profile_dir, now=self._clock
        )
        self.snapshots = snapshot_service or SnapshotService(
            self.store,
            self.portfolio,
            self.calendar,
            close_time=config.close_time,
            enabled=config.snapshots_enabled,
        )
        self._lock = threading.RLock()
        self.settings = SettingsService(self.store)
        self._last_cn_poll: Optional[datetime] = None
        self._last_market_poll: Optional[datetime] = None
        self._last_plan_eval: Optional[datetime] = None
        self._last_card_eval: Optional[datetime] = None
        self._last_discipline_eval: Optional[datetime] = None
        self._last_emergency_eval: Optional[datetime] = None
        self._last_quotes: dict[str, dict[str, Any]] = {}
        self._market_regime_cache: Optional[tuple[datetime, Optional[str]]] = None
        self._portfolio_cache: Optional[tuple[datetime, dict[str, Any]]] = None
        self._stopped = threading.Event()
        self._last_tick: Optional[datetime] = None
        self.card_plans = CardPlanSync(
            store=self.store,
            client=getattr(self.sources, "plan_rules", self.sources),
            clock=self.now,
            overview_provider=self._cached_overview,
            on_transition=self._record_card_state_change,
        )

    # -- time ------------------------------------------------------------
    def now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=CN_TZ)
        return value.astimezone(CN_TZ)

    # -- lifecycle -------------------------------------------------------
    def bootstrap(self) -> None:
        with self._lock:
            self.tick(force=True)

    def run(self, stop: Optional[threading.Event] = None) -> None:
        event = stop or self._stopped
        while not event.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - one bad cycle must not kill the hub
                logger.warning("tick failed: %s", type(exc).__name__)
            event.wait(1.0)

    def stop(self) -> None:
        self._stopped.set()

    def tick(self, now: Optional[datetime] = None, *, force: bool = False) -> None:
        moment = now or self.now()
        with self._lock:
            self._last_tick = moment
            self.store.restore_snoozed(moment)
            analyses = self._safe_analyses(moment)
            self._refresh_analyses(analyses, moment)
            if force or self._due(self._last_cn_poll, moment, self.config.alerts_seconds):
                self._poll_cn(moment, analyses)
                self._last_cn_poll = moment
            if force or self._due(self._last_market_poll, moment, self.config.alerts_seconds):
                self._poll_market(moment)
                self._last_market_poll = moment
            if force or self._due(self._last_plan_eval, moment, self.config.plans_seconds):
                self._evaluate_plans(moment)
                self._last_plan_eval = moment
            if force or self._due(self._last_card_eval, moment, 3.0):
                self._sync_cards(moment)
                self._last_card_eval = moment
            if force or self._due(self._last_discipline_eval, moment, 3.0):
                self._evaluate_discipline(moment)
                self._last_discipline_eval = moment
            for step in (
                self._maybe_regime,
                self._maybe_guidance,
                self._maybe_emergency,
            ):
                try:
                    step(moment)
                except Exception as exc:  # noqa: BLE001 - one rule must not kill the tick
                    logger.warning("%s failed: %s", step.__name__, type(exc).__name__)
            try:
                self._flush_pending_contexts(moment)
            except Exception as exc:  # noqa: BLE001 - context packs are best effort
                logger.warning("context pack failed: %s", type(exc).__name__)
            try:
                self._maybe_outcomes(moment)
            except Exception as exc:  # noqa: BLE001 - outcome writes are best effort
                logger.warning("candidate outcome failed: %s", type(exc).__name__)
            try:
                self.snapshots.maybe_write(moment)
            except Exception as exc:  # noqa: BLE001 - snapshot is best-effort
                logger.warning("snapshot failed: %s", type(exc).__name__)

    @staticmethod
    def _due(last: Optional[datetime], now: datetime, seconds: float) -> bool:
        return last is None or (now - last).total_seconds() >= seconds

    # -- upstream polling ------------------------------------------------
    def _safe_analyses(self, now: datetime) -> dict[int, Analysis]:
        try:
            result = self.sources.analyses()
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 - analyses are optional
            logger.warning("analyses unavailable: %s", type(exc).__name__)
            return {}

    def _poll_cn(self, now: datetime, analyses: Mapping[int, Analysis]) -> None:
        try:
            alerts = self.sources.cn_alerts(self.store.max_alert_id("cn_watch"), now=now)
        except Exception as exc:  # noqa: BLE001 - upstream down is a health state
            logger.warning("cn-watch poll failed: %s", type(exc).__name__)
            return
        for alert in alerts:
            self._ingest_cn(alert, analyses, now)

    def _poll_market(self, now: datetime) -> None:
        try:
            alerts = self.sources.market_alerts(self.store.max_alert_id("market_watch"), now=now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("market-watch poll failed: %s", type(exc).__name__)
            return
        for alert in alerts:
            self._ingest_market(alert, now)

    def _mark(
        self,
        source: str,
        alert_id: int,
        *,
        status: str,
        reason: Optional[str],
        signal_id: Optional[int],
        ts: datetime,
    ) -> None:
        self.store.mark_processed(
            source,
            alert_id,
            status=status,
            reason=reason,
            signal_id=signal_id,
            ts=ts,
        )

    def _ingest_cn(
        self,
        alert: dict[str, Any],
        analyses: Mapping[int, Analysis],
        now: datetime,
    ) -> None:
        try:
            alert_id = int(alert.get("id"))
        except (TypeError, ValueError):
            return
        if self.store.is_processed("cn_watch", alert_id):
            return
        analysis = analyses.get(alert_id)
        try:
            ts = parse_iso(alert.get("ts"))
        except ValueError:
            ts = now
        if analysis_skipped(analysis):
            self._merge_or_count("cn_watch", alert_id, alert, ts, now)
            self._mark(
                "cn_watch",
                alert_id,
                status="skipped",
                reason=(analysis.reason if analysis else "skipped"),
                signal_id=None,
                ts=ts,
            )
            return
        signal = signal_from_cn_alert(alert, analysis, now=now)
        if signal is None:
            self._mark(
                "cn_watch",
                alert_id,
                status="invalid",
                reason="unusable_alert",
                signal_id=None,
                ts=ts,
            )
            return
        candidate = self.store.find_merge_candidate(
            signal.dedupe_key, merge_since(signal.kind, is_false_positive(analysis), signal.ts)
        )
        if candidate is not None and self._mergeable(candidate, signal):
            updated = self.store.merge_signal(
                candidate["id"],
                alert_id=alert_id,
                analysis_id=alert_id if analysis is not None else None,
                now=now,
            )
            signal_id = updated["id"] if updated else candidate["id"]
        else:
            signal_id = self.store.insert_signal(signal, now)
        self._mark(
            "cn_watch",
            alert_id,
            status="signal",
            reason=None,
            signal_id=signal_id,
            ts=ts,
        )

    @staticmethod
    def _mergeable(candidate: Mapping[str, Any], signal: Signal) -> bool:
        if candidate.get("kind") != signal.kind:
            return False
        if candidate.get("status") in {"done", "ignored"} and not candidate.get("folded"):
            # A card the user closed stays closed: no re-merge, no revival.
            return False
        return True

    def _merge_or_count(
        self,
        source: str,
        alert_id: int,
        alert: dict[str, Any],
        ts: datetime,
        now: datetime,
    ) -> None:
        code = str(alert.get("code") or "")
        rule_id = str(alert.get("rule_id") or "")
        if not code:
            return
        if source == "cn_watch":
            object_type = "stock"
        else:
            rule = str(alert.get("rule_id") or "")
            raw_object = alert.get("object") if isinstance(alert.get("object"), dict) else {}
            if rule in {"R1", "R2"}:
                object_type = "market"
            elif rule in {"R3", "R4", "R5"}:
                object_type = "sector"
            else:
                object_type = str(raw_object.get("type") or "stock")
        key = dedupe_key(object_type, code, rule_id)
        candidate = self.store.find_merge_candidate(key, ts - timedelta(minutes=30))
        if candidate is None:
            return
        if candidate.get("status") in {"done", "ignored"} and not candidate.get("folded"):
            # User-closed cards never absorb later skipped/dry-run alerts.
            return
        self.store.merge_signal(candidate["id"], alert_id=alert_id, analysis_id=None, now=now)

    def _ingest_market(self, alert: dict[str, Any], now: datetime) -> None:
        try:
            alert_id = int(alert.get("id"))
        except (TypeError, ValueError):
            return
        if self.store.is_processed("market_watch", alert_id):
            return
        try:
            ts = parse_iso(alert.get("ts"))
        except ValueError:
            ts = now
        status = str(alert.get("status") or "")
        if status == "skipped":
            self._merge_or_count("market_watch", alert_id, alert, ts, now)
            self._mark(
                "market_watch",
                alert_id,
                status="skipped",
                reason="upstream_skipped",
                signal_id=None,
                ts=ts,
            )
            return
        signal = signal_from_market_alert(alert, now=now)
        if signal is None:
            self._mark(
                "market_watch",
                alert_id,
                status="invalid",
                reason="unusable_alert",
                signal_id=None,
                ts=ts,
            )
            return
        candidate = self.store.find_merge_candidate(signal.dedupe_key, merge_since(signal.kind, False, signal.ts))
        if candidate is not None and self._mergeable(candidate, signal):
            updated = self.store.merge_signal(
                candidate["id"], alert_id=alert_id, analysis_id=None, now=now
            )
            signal_id = updated["id"] if updated else candidate["id"]
        else:
            signal_id = self.store.insert_signal(signal, now)
        self._mark(
            "market_watch",
            alert_id,
            status="signal",
            reason=None,
            signal_id=signal_id,
            ts=ts,
        )

    # -- late analysis upgrades -----------------------------------------
    def _refresh_analyses(self, analyses: Mapping[int, Analysis], now: datetime) -> None:
        for alert_id, analysis in analyses.items():
            if analysis.status != "done" or not analysis.markdown:
                continue
            signal_id = self.store.processed_signal_id("cn_watch", alert_id)
            if signal_id is None:
                continue
            row = self.store.get_signal(signal_id)
            if row is None:
                continue
            false_positive = is_false_positive(analysis)
            needs_upgrade = row.get("analysis_id") is None and not row.get("detail_available")
            if not needs_upgrade and not (false_positive and row.get("kind") != "info"):
                continue
            conclusion = extract_conclusion(analysis.markdown)
            direction = extract_direction(analysis.markdown)
            points = extract_points(analysis.markdown)
            brief = "；".join(points[:2]) if points else extract_detail(analysis.markdown)
            updates: dict[str, Any] = {
                "conclusion": conclusion or None,
                "direction": direction,
                "brief": brief or None,
                "analysis_id": alert_id,
                "detail_available": True,
                "now": now,
            }
            if false_positive:
                already_closed = row.get("status") in {"done", "ignored"}
                updates.update({"kind": "info", "status": "done"})
                if not already_closed:
                    # System fold (not a user action): keep absorbing same-day noise.
                    updates["folded"] = True
            self.store.update_signal_content(signal_id, **updates)

    # -- plans -----------------------------------------------------------
    def _plan_quotes(self, plans: list[dict[str, Any]], now: datetime) -> dict[str, dict[str, Any]]:
        quotes = self._state_quotes(now)
        missing = [plan["code"] for plan in plans if plan["code"] not in quotes]
        if missing:
            try:
                fetched = self.sources.tencent_quotes(missing, now=now)
            except Exception as exc:  # noqa: BLE001 - prices are optional
                logger.warning("tencent quote poll failed: %s", type(exc).__name__)
                fetched = {}
            for code, quote in (fetched or {}).items():
                price = getattr(quote, "price", None)
                prev_close = getattr(quote, "prev_close", None)
                change = getattr(quote, "change_pct", None)
                name = getattr(quote, "name", None) or code
                if price is None or float(price) <= 0:
                    continue
                quotes[code] = {
                    "price": float(price),
                    "prev_close": None if prev_close is None else float(prev_close),
                    "change_pct": None if change is None else float(change),
                    "name": name,
                }
        self._last_quotes.update(quotes)
        return quotes

    def _state_quotes(self, now: datetime) -> dict[str, dict[str, Any]]:
        try:
            state = self.sources.cn_state(now=now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cn-watch state unavailable: %s", type(exc).__name__)
            return {}
        quotes: dict[str, dict[str, Any]] = {}
        raw_quotes = state.get("quotes") if isinstance(state, dict) else None
        if isinstance(raw_quotes, dict):
            for code, item in raw_quotes.items():
                if not isinstance(item, dict):
                    continue
                price = item.get("price")
                if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
                    continue
                quotes[str(code)] = {
                    "price": float(price),
                    "prev_close": item.get("prev_close"),
                    "change_pct": item.get("change_pct"),
                    "name": item.get("name") or str(code),
                }
        return quotes

    def _evaluate_plans(self, now: datetime) -> None:
        active = self.store.list_plans("active")
        quotes = self._plan_quotes(active, now) if active else {}
        for plan in active:
            if now >= plan["expires_at"]:
                self._expire_plan(plan, now)
                continue
            quote = quotes.get(plan["code"])
            price = quote.get("price") if quote else None
            change_pct = quote.get("change_pct") if quote else None
            if price is not None:
                self.store.update_plan(plan["id"], last_price=price, now=now)
            if not condition_met(plan["condition"], price=price, change_pct=change_pct):
                continue
            signal = plan_signal(self._to_plan(plan), trigger_kind(plan["kind"]), now=now, price=price)
            self.store.insert_signal(signal, now)
            self.store.update_plan(
                plan["id"],
                status="triggered",
                triggered_at=now,
                last_price=price,
                now=now,
            )
        for plan in self.store.list_plans("proposed"):
            if now >= plan["expires_at"]:
                self.store.update_plan(plan["id"], status="expired", now=now)

    def _expire_plan(self, plan: dict[str, Any], now: datetime) -> None:
        signal = expiry_signal(self._to_plan(plan), now=now)
        self.store.insert_signal(signal, now)
        self.store.update_plan(plan["id"], status="expired", now=now)

    @staticmethod
    def _to_plan(row: dict[str, Any]):
        from .models import Plan

        return Plan(
            id=row["id"],
            code=row["code"],
            name=row["name"],
            kind=row["kind"],
            status=row["status"],
            condition=row["condition"],
            stop=row["stop"],
            rationale=row["rationale"],
            source=row["source"],
            proposed_by=row["proposed_by"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            triggered_at=row.get("triggered_at"),
            last_price=row.get("last_price"),
        )

    # -- v1.1 cards / discipline / outcomes -----------------------------
    def _cached_overview(self, now: datetime) -> dict[str, Any]:
        """Always read live values: the caller may change holdings between ticks."""
        try:
            payload = self.portfolio.overview()
        except Exception as exc:  # noqa: BLE001 - never log holdings
            logger.warning("portfolio overview unavailable: %s", type(exc).__name__)
            payload = {"ok": True, "private": True, "empty": True, "positions": [], "totals": {}}
        self._portfolio_cache = (now, payload)
        return payload

    def _regime(self, now: datetime) -> Optional[str]:
        cached = self._market_regime_cache
        age = None if cached is None else (now - cached[0]).total_seconds()
        if cached is not None and age is not None and 0.0 <= age < 3.0:
            return cached[1]
        try:
            overview = self.sources.market_overview(now=now)
        except Exception:  # noqa: BLE001
            return None
        label = ((overview.get("regime") or {}).get("label")) if isinstance(overview, dict) else None
        regime = {"risk_on": "strong", "risk_off": "weak", "neutral": "neutral"}.get(str(label))
        self._market_regime_cache = (now, regime)
        return regime

    def _evaluate_discipline(self, now: datetime) -> None:
        if not self.calendar.is_trading_day(now.date()):
            return
        overview = self._cached_overview(now)
        payload = discipline_payload(
            store=self.store,
            settings=self.settings,
            overview=overview,
            now=now,
            regime=self._regime(now),
        )
        for reason in payload["reasons"]:
            if self.store.mark_discipline(now.date().isoformat(), reason["rule"], now):
                self.store.insert_signal(discipline_signal(reason, now=now), now)

    def _sync_cards(self, now: datetime) -> None:
        """Local bookkeeping, then push/reconcile/mirror through chives-radar."""
        for card in self.store.list_cards():
            if card["status"] not in {"active", "proposed"}:
                continue
            if now >= card["expires_at"]:
                if card["status"] == "active":
                    self.card_plans.remove_card(card["id"], now, reason="card_expired")
                self.store.update_card(card["id"], status="expired", now=now)
                continue
            if card["status"] != "active":
                continue
            if card.get("locked_at") is None:
                due = lock_moment(card["created_at"], self.calendar)
                if now >= due:
                    self.store.update_card(card["id"], locked_at=due, now=now)
                    card["locked_at"] = due
        self.card_plans.sync(now)

    def _record_card_state_change(
        self,
        card: dict[str, Any],
        *,
        old_state: Optional[str],
        new_state: str,
        reason: str,
        now: datetime,
        price: Optional[float] = None,
    ) -> Optional[int]:
        """One transaction for card state, history, signal and trigger."""
        signal_seen = self.store.saw_card_state_since(
            card["id"], new_state, now - timedelta(minutes=5)
        )
        trigger_kind = CARD_TRIGGER_KINDS.get(new_state)
        make_trigger = bool(
            trigger_kind
            and not signal_seen
            and not self.store.saw_trigger_since(
                card["id"], new_state, now - timedelta(minutes=5)
            )
        )
        trigger = (
            {
                "kind": trigger_kind,
                "card_id": card["id"],
                "code": card["code"],
                "name": card["name"],
                "from_state": old_state,
                "to_state": new_state,
                "reason": reason,
                "dedupe_key": trigger_dedupe_key(
                    str(trigger_kind), card_id=card["id"], to_state=new_state
                ),
            }
            if make_trigger
            else None
        )
        signal = (
            None
            if signal_seen
            else card_state_signal(
                card,
                from_state=old_state,
                to_state=new_state,
                reason=reason,
                now=now,
                price=price,
            )
        )
        result = self.store.record_card_transition(
            card["id"],
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            now=now,
            signal=signal,
            trigger=trigger,
            last_price=price,
        )
        trigger_id = result.get("trigger_id")
        if trigger_id:
            self._ensure_trigger_context(int(trigger_id), now)
            return int(trigger_id)
        return None

    def _maybe_outcomes(self, now: datetime) -> None:
        if not self.calendar.is_trading_day(now.date()):
            return
        if now.timetz().replace(tzinfo=None) < time(15, 5):
            return
        day = now.date().isoformat()
        marker = f"outcomes:{day}"
        if self.store.get_kv(marker):
            return
        cards = [
            card
            for card in self.store.list_cards()
            if card.get("review_date") == day
            and card["status"] in {"active", "closed"}
            and card.get("outcome") is None
        ]
        if not cards:
            self.store.set_kv(marker, True)
            return
        quotes = quotes_for(self.sources, [card["code"] for card in cards], now=now)
        for card in cards:
            outcome = build_outcome(
                card,
                quotes.get(card["code"]),
                history=self.store.list_card_history(card["id"]),
                now=now,
            )
            self.store.update_card(card["id"], outcome=outcome, now=now)
        self.store.set_kv(marker, True)

    # -- triggers / guidance / emergency ---------------------------------
    def _discipline_now(
        self, now: datetime, overview: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        return discipline_payload(
            store=self.store,
            settings=self.settings,
            overview=overview if overview is not None else self._cached_overview(now),
            now=now,
            regime=self._regime(now),
        )

    def _live_active_cards(self, now: datetime) -> list[dict[str, Any]]:
        return [
            card
            for card in self.store.list_cards(status="active")
            if card["expires_at"] > now and card.get("state") in {"observe", "await_confirm", "execute"}
        ]

    def _ensure_trigger_context(
        self,
        trigger_id: int,
        now: datetime,
        *,
        extra: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        trigger = self.store.get_trigger(trigger_id)
        if trigger is None:
            return None
        if not trigger["context_ready"]:
            card = (
                self.store.get_card(trigger["card_id"])
                if trigger.get("card_id") is not None
                else None
            )
            overview = self._cached_overview(now)
            pack = build_context_pack(
                trigger=trigger,
                card=card,
                store=self.store,
                settings=self.settings,
                sources=self.sources,
                portfolio_overview=overview,
                discipline=self._discipline_now(now, overview),
                now=now,
            )
            if extra:
                pack.update(extra)
            self.store.set_trigger_context(trigger_id, pack)
            trigger = self.store.get_trigger(trigger_id) or trigger
        return trigger

    def _flush_pending_contexts(self, now: datetime) -> None:
        for trigger_id in self.store.pending_trigger_ids(5):
            self._ensure_trigger_context(trigger_id, now)

    def _maybe_regime(self, now: datetime) -> None:
        regime = self._regime(now)
        if regime is None:
            return
        previous = self.store.get_kv("regime:last")
        if previous == regime:
            return
        self.store.set_kv("regime:last", regime)
        if previous is None:
            return
        if not self._live_active_cards(now):
            return
        if self.store.saw_regime_trigger_since(regime, now - timedelta(minutes=5)):
            return
        trigger = {
            "kind": "regime",
            "card_id": None,
            "code": None,
            "name": None,
            "from_state": str(previous),
            "to_state": regime,
            "reason": f"环境标签 {previous}→{regime}",
            "dedupe_key": trigger_dedupe_key("regime", card_id=None, to_state=regime),
        }
        trigger_id = self.store.insert_trigger(trigger, now)
        self._ensure_trigger_context(trigger_id, now)

    def _maybe_guidance(self, now: datetime) -> None:
        slot = due_slot(now, self.calendar)
        if slot is None:
            return
        day = now.date().isoformat()
        if self.store.get_guidance(day, slot) is not None:
            return
        cards = self._live_active_cards(now)
        if not cards:
            return
        overview: Optional[dict[str, Any]] = None
        try:
            overview = self.sources.market_overview(now=now)
        except Exception as exc:  # noqa: BLE001 - label degrades to 未知
            logger.warning("guidance market overview failed: %s", type(exc).__name__)
        theme = theme_snapshot(self.sources, now=now, overview=overview)
        previous_theme = self.store.previous_guidance_theme(day, slot)
        regime_raw = (overview.get("regime") or {}).get("label") if isinstance(overview, dict) else None
        regime = {"risk_on": "strong", "neutral": "neutral", "risk_off": "weak"}.get(
            str(regime_raw)
        )
        context = guidance_context(
            day=day,
            slot=slot,
            now=now,
            overview=overview,
            cards=cards,
            theme=theme,
            previous_theme=previous_theme,
            settings=self.settings,
            regime=regime,
        )
        signal = guidance_signal(context, day=day, slot=slot, now=now)
        self.store.save_guidance(
            day=day,
            slot=slot,
            signal=signal,
            context=context,
            theme=theme,
            now=now,
        )

    def _maybe_emergency(self, now: datetime) -> None:
        if not market_session(now, self.calendar):
            return
        thresholds = {
            INDEX_THRESHOLD_KEY: self.settings.value(INDEX_THRESHOLD_KEY),
            LIMIT_DOWN_THRESHOLD_KEY: self.settings.value(LIMIT_DOWN_THRESHOLD_KEY),
        }
        if all(value is None for value in thresholds.values()):
            return
        if not self._due(self._last_emergency_eval, now, 30.0):
            return
        self._last_emergency_eval = now
        overview: Optional[dict[str, Any]] = None
        try:
            overview = self.sources.market_overview(now=now)
        except Exception as exc:  # noqa: BLE001 - missing data never fires
            logger.warning("emergency market overview failed: %s", type(exc).__name__)
        quotes: dict[str, Any] = {}
        try:
            state = self.sources.cn_state(now=now)
            if isinstance(state, dict) and isinstance(state.get("quotes"), dict):
                quotes = state["quotes"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("emergency cn-watch state failed: %s", type(exc).__name__)
        overview_portfolio = self._cached_overview(now)
        positions = [
            item
            for item in overview_portfolio.get("positions") or []
            if isinstance(item, dict)
        ]
        limit_down_count: Optional[int] = None
        if thresholds.get(LIMIT_DOWN_THRESHOLD_KEY) is not None:
            breadth = overview.get("breadth") if isinstance(overview, dict) else None
            if isinstance(breadth, dict):
                value = breadth.get("limit_down")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    limit_down_count = int(value)
            if limit_down_count is None:
                try:
                    pool = self.sources.market_pool("dt", now=now)
                    count = pool.get("count") if isinstance(pool, dict) else None
                    if isinstance(count, (int, float)) and not isinstance(count, bool):
                        limit_down_count = int(count)
                except Exception:  # noqa: BLE001
                    limit_down_count = None
        hits = evaluate_emergency(
            thresholds=thresholds,
            overview=overview,
            quotes=quotes,
            positions=positions,
            limit_down_count=limit_down_count,
        )
        day = now.date().isoformat()
        for hit in hits:
            signal = emergency_signal(hit, now=now)
            trigger = {
                "kind": "emergency",
                "card_id": None,
                "code": None,
                "name": None,
                "from_state": None,
                "to_state": None,
                "reason": str(hit.get("detail") or hit.get("reason") or "应急触发"),
                "dedupe_key": f"emergency|{day}|{hit.get('reason')}",
            }
            stored = self.store.insert_emergency_once(
                day=day,
                reason=str(hit.get("reason")),
                signal=signal,
                trigger=trigger,
                now=now,
            )
            if stored and stored.get("trigger_id"):
                self._ensure_trigger_context(
                    int(stored["trigger_id"]),
                    now,
                    extra={
                        "emergency": {
                            "reason": hit.get("reason"),
                            "values": hit.get("values") or {},
                        }
                    },
                )

    # -- public API ------------------------------------------------------
    def health_dict(self) -> dict[str, Any]:
        now = self.now()
        sources = self.sources.health(now)
        counts = self.store.signal_counts()
        plans = self.store.list_plans("all")
        plan_counts = {status: 0 for status in PLAN_STATUSES if status != "all"}
        for plan in plans:
            if plan["status"] in plan_counts:
                plan_counts[plan["status"]] += 1
        return {
            "ok": True,
            "as_of": fmt_iso(now),
            "sources": sources,
            "counts": {
                **counts,
                "plans": len(plans),
                "plans_active": plan_counts.get("active", 0),
                "plans_proposed": plan_counts.get("proposed", 0),
                "processed_today": self.store.processed_count_today(
                    now.replace(hour=0, minute=0, second=0, microsecond=0)
                ),
            },
            "db": {"path": str(self.config.db_path), "ok": True},
            "calendar": {"source": self.calendar.source, "trading_day": self.calendar.is_trading_day(now.date())},
        }

    def signals_payload(
        self,
        *,
        status: str = "active",
        decide: Optional[bool] = None,
        object_type: Optional[str] = None,
        limit: int = 50,
        since_id: int = 0,
    ) -> dict[str, Any]:
        now = self.now()
        self.store.restore_snoozed(now)
        status = status or "active"
        rows = self.store.list_signals(
            status=status,
            decide=decide,
            object_type=object_type,
            limit=limit,
            since_id=since_id,
        )
        ordered = sort_signals(rows)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_id = max((row["id"] for row in ordered), default=since_id)
        raw_counts = self.store.signal_counts()
        counts = {key: raw_counts[key] for key in ("decide", "active", "snoozed", "done")}
        return {
            "ok": True,
            "as_of": fmt_iso(now),
            "signals": [signal_payload(row) for row in ordered],
            "counts": counts,
            "merged_today": self.store.merged_today(day_start),
            "next_id": next_id,
        }

    def signal_detail(self, signal_id: int) -> Optional[dict[str, Any]]:
        row = self.store.get_signal(signal_id)
        if row is None:
            return None
        payload: dict[str, Any] = {"ok": True, **signal_payload(row)}
        analysis: Optional[Analysis] = None
        alert_ids = row.get("source", {}).get("alert_ids") or []
        if alert_ids and row.get("rule_id"):
            try:
                alert_id = int(alert_ids[0])
            except (TypeError, ValueError):
                alert_id = None
            if alert_id is not None:
                analysis = self._safe_analyses(self.now()).get(alert_id)
        payload["analysis"] = analysis_sections(analysis)
        return payload

    def action_signal(self, signal_id: int, action: str, until: Optional[str]) -> dict[str, Any]:
        now = self.now()
        row = self.store.get_signal(signal_id)
        if row is None:
            raise SignalActionError("signal_not_found", "信号不存在", status=404)
        current = row["status"]
        if action == "ack":
            if current in {"done", "ignored"}:
                raise SignalActionError("invalid_status", "已结束的信号不能 ack")
            updated = self.store.update_signal(
                signal_id, status="seen", clear_snooze=True, now=now
            )
        elif action == "ignore":
            updated = self.store.update_signal(
                signal_id, status="done", ignored=True, folded=False, clear_snooze=True, now=now
            )
        elif action == "done":
            updated = self.store.update_signal(
                signal_id, status="done", ignored=False, folded=False, clear_snooze=True, now=now
            )
        elif action == "snooze":
            if until is None:
                raise SignalActionError("invalid_until", "snooze 需要 until")
            try:
                target = resolve_snooze_until(until, now=now, calendar=self.calendar)
            except ValueError as exc:
                raise SignalActionError("invalid_until", str(exc), status=400) from exc
            if current in {"done", "ignored"}:
                raise SignalActionError("invalid_status", "已结束的信号不能 snooze")
            updated = self.store.update_signal(
                signal_id, status="snoozed", snooze_until=target, now=now
            )
        elif action == "unsnooze":
            if current != "snoozed":
                raise SignalActionError("invalid_status", "只有 snoozed 信号可以 unsnooze")
            updated = self.store.update_signal(
                signal_id, status="new", clear_snooze=True, now=now
            )
        elif action == "reopen":
            if current not in {"done", "ignored", "snoozed"}:
                raise SignalActionError("invalid_status", "只有已结束或 snoozed 的信号可以 reopen")
            updated = self.store.update_signal(
                signal_id, status="new", clear_snooze=True, ignored=False, folded=False, now=now
            )
        else:
            raise SignalActionError("invalid_action", "不支持的 action")
        if updated is None:
            raise SignalActionError("signal_not_found", "信号不存在", status=404)
        return {"ok": True, "signal": signal_payload(updated)}

    def plans_payload(self, status: str = "all") -> dict[str, Any]:
        status = status or "all"
        if status not in PLAN_STATUSES:
            raise PlanError(
                "invalid_status",
                "status 只接受 proposed/active/triggered/expired/cancelled/all",
                status=200,
            )
        rows = self.store.list_plans(status)
        counts = {name: 0 for name in PLAN_STATUSES if name != "all"}
        for plan in self.store.list_plans("all"):
            if plan["status"] in counts:
                counts[plan["status"]] += 1
        return {"ok": True, "plans": [self._plan_payload(row) for row in rows], "counts": counts}

    @staticmethod
    def _plan_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "kind": row["kind"],
            "status": row["status"],
            "condition": row["condition"],
            "stop": row["stop"],
            "rationale": row["rationale"],
            "source": row["source"],
            "proposed_by": row["proposed_by"],
            "created_at": fmt_iso(row["created_at"]),
            "expires_at": fmt_iso(row["expires_at"]),
            "triggered_at": fmt_iso(row["triggered_at"]),
            "last_price": row["last_price"],
        }

    def create_plan(self, payload: Any) -> dict[str, Any]:
        now = self.now()
        with self._lock:
            plan = create_plan(
                payload,
                now=now,
                calendar=self.calendar,
                max_active_plans=self.config.max_active_plans,
                max_plan_days=self.config.max_plan_days,
                active_count=self.store.count_active_plans(),
                name_resolver=self.lookup_name,
            )
            plan_id = self.store.insert_plan(plan, now)
            plan.id = plan_id
            if plan.status == "proposed":
                self.store.insert_signal(plan_signal(plan, "plan_proposal", now=now, price=None), now)
            stored = self.store.get_plan(plan_id)
            return self._plan_payload(stored) if stored else plan.to_dict()

    def plan_action(self, plan_id: int, payload: Any) -> Optional[dict[str, Any]]:
        now = self.now()
        with self._lock:
            row = self.store.get_plan(plan_id)
            if row is None:
                return None
            plan = self._to_plan(row)
            fields = apply_action(
                plan,
                payload,
                now=now,
                calendar=self.calendar,
                max_plan_days=self.config.max_plan_days,
            )
            self.store.update_plan(
                plan_id,
                status=fields.get("status"),
                expires_at=fields.get("expires_at"),
                clear_triggered=bool(fields.get("clear_triggered")),
                now=now,
            )
            if fields.get("status") in {"active", "cancelled"}:
                self.store.close_plan_proposals(plan_id, now)
            stored = self.store.get_plan(plan_id)
            return self._plan_payload(stored) if stored else None

    def lookup_name(self, code: str) -> str:
        quote = self._last_quotes.get(code)
        if quote and quote.get("name"):
            return str(quote["name"])
        try:
            fetched = self.sources.tencent_quotes([code], now=self.now())
        except Exception as exc:  # noqa: BLE001 - name is cosmetic
            logger.warning("name lookup failed: %s", type(exc).__name__)
            return code
        quote = fetched.get(code) if fetched else None
        if quote is not None and getattr(quote, "name", None):
            return str(quote.name)
        return code

    def overview(self) -> dict[str, Any]:
        payload = self.portfolio.overview()
        try:
            payload["limits"] = headroom(
                payload, self.settings, regime=self._regime(self.now())
            )
        except Exception as exc:  # noqa: BLE001 - limits degrade to nulls
            logger.warning("limits unavailable: %s", type(exc).__name__)
            payload["limits"] = headroom(payload, self.settings, regime=None)
        return payload

    def history(self, days: int) -> dict[str, Any]:
        return self.portfolio.history(days)

    # -- settings --------------------------------------------------------
    def settings_payload(self) -> dict[str, Any]:
        return self.settings.payload()

    def setting_action(self, key: str, payload: Any) -> dict[str, Any]:
        return self.settings.action(key, payload, now=self.now())

    def setting_suggest(self, key: str, payload: Any) -> dict[str, Any]:
        return self.settings.suggest(key, payload, now=self.now())

    # -- discipline ------------------------------------------------------
    def discipline(self) -> dict[str, Any]:
        now = self.now()
        return discipline_payload(
            store=self.store,
            settings=self.settings,
            overview=self._cached_overview(now),
            now=now,
            regime=self._regime(now),
        )

    def discipline_loss_streak(self, payload: Any) -> dict[str, Any]:
        return apply_loss_streak(self.store, payload, now=self.now())

    def discipline_mood(self, payload: Any) -> dict[str, Any]:
        return apply_mood(self.store, payload, now=self.now())

    def _paused(self, now: datetime) -> bool:
        return bool(
            discipline_payload(
                store=self.store,
                settings=self.settings,
                overview=self._cached_overview(now),
                now=now,
                regime=self._regime(now),
            )["paused"]
        )

    # -- reviews ---------------------------------------------------------
    def review_data(self) -> dict[str, Any]:
        now = self.now()
        payload = discipline_payload(
            store=self.store,
            settings=self.settings,
            overview=self._cached_overview(now),
            now=now,
            regime=self._regime(now),
        )
        return build_review_data(
            sources=self.sources,
            store=self.store,
            settings_service=self.settings,
            portfolio=self.portfolio,
            calendar=self.calendar,
            discipline_payload=payload,
            now=now,
        )

    def save_review(self, payload: Any) -> dict[str, Any]:
        now = self.now()
        review = validate_review(payload, now=now)
        stored = self.store.save_review(review["date"], review["kind"], review, now)
        signal = review_ready_signal(stored, now=now)
        self.store.insert_signal(signal, now)
        return {
            "ok": True,
            "review": {
                **stored["payload"],
                "revision": stored["revision"],
                "updated_at": fmt_iso(stored["updated_at"]),
                "untrusted_text": True,
            },
            "revision": stored["revision"],
        }

    def reviews_payload(self, *, limit: int = 20, kind: Optional[str] = None) -> dict[str, Any]:
        return review_list_payload(self.store, limit=limit, kind=kind)

    def review_detail(self, day: str, kind: str) -> Optional[dict[str, Any]]:
        return review_detail_payload(self.store, day, kind)

    # -- cards -----------------------------------------------------------
    def _card_with_history(self, card: dict[str, Any]) -> dict[str, Any]:
        return card_payload(card, self.store.list_card_history(card["id"]))

    def cards_payload(self, *, status: str = "all", day: Optional[str] = None) -> dict[str, Any]:
        if status == "closed":
            rows = []
            for terminal in ("expired", "cancelled", "closed"):
                rows.extend(self.store.list_cards(status=terminal, date=day))
            rows.sort(key=lambda item: item["id"], reverse=True)
        else:
            rows = self.store.list_cards(status=status, date=day)
        counts = {name: 0 for name in ("proposed", "active", "expired", "cancelled", "closed")}
        for card in self.store.list_cards():
            if card["status"] in counts:
                counts[card["status"]] += 1
        counts["closed"] = (
            counts["expired"] + counts["cancelled"] + counts["closed"]
        )
        return {
            "ok": True,
            "engine": self.card_plans.status_payload(),
            "cards": [self._card_with_history(card) for card in rows],
            "counts": counts,
        }

    def card_detail(self, card_id: int) -> Optional[dict[str, Any]]:
        card = self.store.get_card(card_id)
        if card is None:
            return None
        return {"ok": True, "card": self._card_with_history(card)}

    def create_card(self, payload: Any) -> dict[str, Any]:
        now = self.now()
        with self._lock:
            code: Optional[str] = None
            if isinstance(payload, dict) and isinstance(payload.get("code"), str):
                code = normalize_card_code(payload.get("code"))
            latest = latest_price(self.sources, code, now=now) if code else None
            overview = self._cached_overview(now)
            regime = self._regime(now)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            card = create_card_row(
                payload,
                now=now,
                calendar=self.calendar,
                live_count=self.store.count_live_cards(),
                code_day_count=self.store.count_cards_for_code_day(
                    code, day_start, day_start + timedelta(days=1)
                ),
                name_resolver=self.lookup_name,
                settings=self.settings,
                overview=overview,
                regime=regime,
                latest_price=latest,
            )
            card_id = self.store.insert_card(card, now)
            card["id"] = card_id
            if card["status"] == "proposed":
                self.store.insert_signal(card_proposal_signal(card, now=now), now)
            stored = self.store.get_card(card_id) or card
            warnings: list[str] = []
            if self._paused(now):
                warnings.append("paused")
            if card.get("sizing_error"):
                warnings.append(str(card["sizing_error"]))
            if card["status"] == "active":
                pushed = self.card_plans.push_card(stored, now, force=True)
                if pushed.get("rejected"):
                    warnings.append("engine_rejected")
                stored = self.store.get_card(card_id) or stored
            return {
                "ok": True,
                "card": self._card_with_history(stored),
                "warnings": warnings,
            }

    def card_action(self, card_id: int, payload: Any) -> Optional[dict[str, Any]]:
        now = self.now()
        with self._lock:
            card = self.store.get_card(card_id)
            if card is None:
                return None
            overview = self._cached_overview(now)
            result = apply_card_action(
                card,
                payload,
                now=now,
                calendar=self.calendar,
                settings=self.settings,
                overview=overview,
                regime=self._regime(now),
                paused=self._paused(now),
            )
            fields = dict(result["fields"])
            if fields.get("status") == "active" and card.get("locked_at") is None:
                due = lock_moment(card["created_at"], self.calendar)
                if now >= due:
                    fields["locked_at"] = due
            change = result.get("state_change")
            if change:
                fields.pop("state", None)
            if fields:
                self.store.update_card(card_id, now=now, **fields)
            if change:
                old_state, new_state, reason = change
                self._record_card_state_change(
                    card,
                    old_state=old_state,
                    new_state=new_state,
                    reason=reason,
                    now=now,
                    price=card.get("last_price"),
                )
            if fields.get("status") in {"cancelled", "active"}:
                self.store.close_card_signals(card_id, now)
            stored = self.store.get_card(card_id) or card
            warnings = list(result.get("warnings") or [])
            if stored["status"] in {"cancelled", "closed", "expired"} or stored.get("state") in {
                "abandon",
                "exit",
            }:
                self.card_plans.remove_card(card_id, now, reason="card_not_evaluated")
            elif stored["status"] == "active" and is_live_card(stored, now):
                pushed = self.card_plans.push_card(stored, now, force=True)
                if pushed.get("rejected"):
                    warnings.append("engine_rejected")
            stored = self.store.get_card(card_id) or stored
            return {
                "ok": True,
                "card": self._card_with_history(stored),
                "warnings": warnings,
            }

    # -- triggers / guidance endpoints ----------------------------------
    def triggers_payload(self, *, since_id: int = 0, limit: int = 50) -> dict[str, Any]:
        rows = self.store.list_triggers(since_id=since_id, limit=limit)
        next_id = int(rows[-1]["id"]) if rows else int(since_id)
        return {
            "ok": True,
            "triggers": [trigger_payload(row) for row in rows],
            "next_id": next_id,
        }

    def trigger_context(self, trigger_id: int) -> Optional[dict[str, Any]]:
        now = self.now()
        trigger = self.store.get_trigger(trigger_id)
        if trigger is None:
            return None
        if not trigger["context_ready"]:
            trigger = self._ensure_trigger_context(trigger_id, now) or trigger
        context = trigger.get("context")
        if context is None:
            return {
                "ok": True,
                "private": True,
                "trigger": trigger_payload(trigger),
                "context": None,
                "missing": ["context"],
            }
        served = copy.deepcopy(context)
        today = served.get("today")
        if isinstance(today, dict):
            today["fast_judgements_used"] = self.store.fast_judgements_used(
                trigger["day"]
            )
        return {
            "ok": True,
            "private": True,
            "trigger": trigger_payload(trigger),
            "context": served,
            "missing": list(served.get("missing") or []),
        }

    def trigger_judgement(self, trigger_id: int, payload: Any) -> dict[str, Any]:
        now = self.now()
        existing = self.store.get_trigger(trigger_id)
        if existing is None:
            raise ApiError("not_found", "触发不存在", status=404)
        judgement = validate_judgement(payload, now=now)
        day = str(existing.get("day") or now.date().isoformat())
        stored = judgement_payload(trigger_id=trigger_id, judgement=judgement, now=now)
        status, trigger = self.store.record_judgement(
            trigger_id, stored, now=now, day=day
        )
        if status == "not_found" or trigger is None:
            raise ApiError("not_found", "触发不存在", status=404)
        if status == "already_judged":
            raise ApiError("already_judged", "该触发已经写回判断，不能重复写")
        if trigger.get("signal_id") is not None:
            row = self.store.get_signal(int(trigger["signal_id"]))
            if row is not None:
                text = judged_signal_text(row, judgement)
                self.store.update_signal_content(
                    int(trigger["signal_id"]),
                    conclusion=text["conclusion"],
                    brief=text["brief"],
                    now=now,
                )
        card = (
            self.store.get_card(int(trigger["card_id"]))
            if trigger.get("card_id") is not None
            else None
        )
        diverges = bool(card is not None and judgement["action"] != card.get("state"))
        return {
            "ok": True,
            "private": True,
            "trigger": trigger_payload(trigger),
            "judgement": stored,
            "diverges_from_state": diverges,
        }

    def guidance_payload(self, day: Optional[str] = None) -> dict[str, Any]:
        target = day or self.now().date().isoformat()
        rows = self.store.list_guidance(target)
        return {
            "ok": True,
            "date": target,
            "count": len(rows),
            "guidance": [
                {
                    "id": row["id"],
                    "ts": fmt_iso(row["ts"]),
                    "slot": row["slot"],
                    "signal_id": row["signal_id"],
                    "context": row["context"],
                }
                for row in rows
            ],
        }

    def candidates_stats(self, *, days: int = 20) -> dict[str, Any]:
        return stats_payload(self.store, days=days, now=self.now())

    def spark_payload(self, raw_codes: Optional[str]) -> dict[str, Any]:
        return self.spark.payload(raw_codes)
