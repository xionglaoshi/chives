"""Deterministic watch engine: polling loop, rule state, cooldown/hysteresis.

Wall time and quote retrieval are injected, so this module never touches the
network or the system clock.  The HTTP layer only reads the snapshots exposed
by :meth:`Engine.state_dict` / :meth:`Engine.alerts`.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol

from .calendar import TradingCalendar, build_calendar
from .config import ConfigError, SymbolError, load_config, normalize_watch_code
from .market_context import MarketContextClient, MarketSnapshot, snapshot_dict
from .models import Metrics, Quote, Rule, WatchConfig, fmt_iso, parse_iso, to_cn
from .plans import (
    ALERT_DEBOUNCE_SECONDS,
    ALERT_STATES,
    MAX_HISTORY as MAX_PLAN_HISTORY,
    MAX_PLANS,
    PLANS_FILE_NAME,
    PlanError,
    PlanRuntime,
    PlansState,
    RuntimePlanStore,
    evaluate_plan,
    EvalContext,
    make_runtime,
    plan_state_dict,
    step_state,
    validate_plan_payload,
)
from .rule_store import (
    MAX_HISTORY,
    RUNTIME_RULES_FILE_NAME,
    RuleError,
    RuntimeOverride,
    RuntimeRulesState,
    RuntimeRulesStore,
    history_entry,
    rule_row,
    sanitize_actor,
    validate_rule_id,
    validate_rule_payload,
)
from .rules import compute_metrics, hot_distance, retreated, trigger
from .watchlist import RUNTIME_FILE_NAME, RuntimeWatchlist

logger = logging.getLogger("chives_radar.engine")


class WatchlistError(Exception):
    """A runtime watchlist request was rejected with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _seq_of(alert: dict[str, Any]) -> int:
    try:
        return int(str(alert.get("dedupe_key", "")).rsplit("|", 1)[1])
    except (IndexError, ValueError):
        return 1


class SourceError(Exception):
    """The quote source failed (timeout, non-200, unparsable payload)."""


class Source(Protocol):
    def fetch(self, codes: list[str], now: datetime) -> dict[str, Quote]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


class Store(Protocol):
    def existing_alerts(self) -> list[dict[str, Any]]: ...

    def write_alert(self, alert: dict[str, Any]) -> None: ...

    def write_poll(self, row: dict[str, Any]) -> None: ...

    def write_state(self, state: dict[str, Any]) -> None: ...


@dataclass
class RuleState:
    armed: bool = True
    last_fired: Optional[datetime] = None
    fired_count: int = 0
    retreated: bool = False


@dataclass
class PollOutcome:
    ok: bool
    mode: str
    next_interval: float
    health: str
    stale: bool
    alerts: list[dict[str, Any]] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        config: WatchConfig,
        source: Source,
        clock: Clock,
        store: Store,
        rng: Optional[random.Random] = None,
        calendar: Optional[TradingCalendar] = None,
        runtime_path: str | Path | None = None,
        rules_runtime_path: str | Path | None = None,
        plans_runtime_path: str | Path | None = None,
        market_client: Any = None,
        config_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.clock = clock
        self.store = store
        self.rng = rng or random.Random()
        self.calendar = calendar or build_calendar(config.calendar, Path.cwd())

        self._lock = threading.RLock()
        resolved_config_path = config_path if config_path is not None else config.config_path
        self._config_path = (
            Path(resolved_config_path) if resolved_config_path is not None else None
        )
        self._config_sig = self._config_signature()
        self._config_reload_error: Optional[str] = None
        self._config_codes = list(config.watchlist)
        self._runtime = self._make_runtime_store(runtime_path)
        self._runtime_codes: list[str] = []
        self._runtime_names: dict[str, str] = {}
        self._load_runtime()
        self._codes = [*self._config_codes, *self._runtime_codes]
        self._code_set = set(self._codes)
        self._sources = {code: "config" for code in self._config_codes}
        self._sources.update({code: "runtime" for code in self._runtime_codes})

        self._rules_store = self._make_rules_store(rules_runtime_path)
        self._runtime_rules = (
            self._rules_store.load() if self._rules_store is not None else RuntimeRulesState()
        )
        self._rules: list[Rule] = []
        self._rule_rows: list[dict[str, Any]] = []
        self._rule_sources: dict[str, str] = {}
        self._normalize_runtime_rules()
        self._compose_effective_rules()
        self._rule_states: dict[tuple[str, str], RuleState] = {}
        self._reconcile_rule_states({})

        self._plans_store = self._make_plans_store(plans_runtime_path)
        self._plans: dict[str, PlanRuntime] = {}
        self._plan_auto_codes: set[str] = set()
        self._plan_load_error: Optional[str] = None
        self._load_plans(now=None)
        for code in self._runtime_codes:
            if code in self._plan_auto_codes:
                self._sources[code] = "plan"
        self._market = (
            market_client
            if market_client is not None
            else MarketContextClient(config.market_watch_url)
        )

        self._latest: dict[str, Quote] = {}
        self._metrics: dict[str, Metrics] = {}
        self._prev_price: dict[str, Optional[float]] = {}
        self._last_exch: dict[str, datetime] = {}
        self._last_advance: dict[str, datetime] = {}
        self._history: dict[str, list[tuple[datetime, float]]] = {code: [] for code in self._codes}
        self._missing: set[str] = set()

        self._now: Optional[datetime] = None
        self._last_poll_ts: Optional[datetime] = None
        self._last_hot: Optional[datetime] = None
        self._lag_seconds: Optional[float] = None
        self._stale = False
        self._health = "ok"
        self._mode = "base"
        self._next_interval = config.polling.base_seconds
        self._trading_day = False
        self._session = "non_trading_day"
        self._last_rule_eval_ts: Optional[datetime] = None
        self._calendar_status = self.calendar.status
        self.consecutive_failures = 0
        self._last_error: Optional[str] = None

        existing = self.store.existing_alerts()
        self._alerts = list(existing)
        self._next_id = max((int(a.get("id", 0)) for a in existing), default=0) + 1
        for alert in existing:
            key = (str(alert.get("code")), str(alert.get("rule_id")))
            state = self._rule_states.get(key)
            if state is None:
                continue
            state.fired_count = max(state.fired_count, _seq_of(alert))
            state.armed = False
            try:
                state.last_fired = parse_iso(alert.get("ts"))
            except ValueError:
                state.last_fired = None

    # ------------------------------------------------------------------ helpers
    def _make_runtime_store(self, override: str | Path | None) -> Optional[RuntimeWatchlist]:
        if override is not None:
            return RuntimeWatchlist(override)
        if self.config.watchlist_runtime_file is not None:
            return RuntimeWatchlist(self.config.watchlist_runtime_file)
        out_dir = getattr(self.store, "out_dir", None)
        if out_dir is None:
            state_path = getattr(self.store, "state_path", None)
            if state_path is not None:
                out_dir = Path(state_path).parent
        if out_dir is None:
            return None
        return RuntimeWatchlist(Path(out_dir) / RUNTIME_FILE_NAME)

    def _make_rules_store(
        self, override: str | Path | None
    ) -> Optional[RuntimeRulesStore]:
        if override is not None:
            return RuntimeRulesStore(override)
        out_dir = getattr(self.store, "out_dir", None)
        if out_dir is None:
            state_path = getattr(self.store, "state_path", None)
            if state_path is not None:
                out_dir = Path(state_path).parent
        if out_dir is None:
            return None
        return RuntimeRulesStore(Path(out_dir) / RUNTIME_RULES_FILE_NAME)

    def _make_plans_store(
        self, override: str | Path | None
    ) -> Optional[RuntimePlanStore]:
        if override is not None:
            return RuntimePlanStore(override)
        out_dir = getattr(self.store, "out_dir", None)
        if out_dir is None:
            state_path = getattr(self.store, "state_path", None)
            if state_path is not None:
                out_dir = Path(state_path).parent
        if out_dir is None:
            return None
        return RuntimePlanStore(Path(out_dir) / PLANS_FILE_NAME)

    def _load_plans(self, now: Optional[datetime] = None) -> None:
        if self._plans_store is None:
            return
        moment = now or self.clock.now()
        try:
            state = self._plans_store.load(moment)
        except OSError as exc:
            logger.warning("读取计划规则失败: %s", exc)
            state = PlansState(load_error=str(exc))
        self._plans = {item.plan.id: item for item in state.plans}
        self._plan_auto_codes = set(state.auto_codes)
        self._plan_load_error = state.load_error

    def _save_plans(self) -> None:
        if self._plans_store is None:
            return
        self._plans_store.save(
            PlansState(
                plans=list(self._plans.values()),
                auto_codes=set(self._plan_auto_codes),
            )
        )

    def _config_signature(self) -> Optional[tuple[int, int, int]]:
        if self._config_path is None:
            return None
        try:
            stat = self._config_path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    def _save_rules_state(self, state: RuntimeRulesState) -> None:
        if self._rules_store is not None:
            self._rules_store.save(state)

    def _normalize_runtime_rules(self) -> None:
        """Keep overrides only for rule ids that still exist in the config."""
        state = self._runtime_rules
        config_ids = {rule.id for rule in self.config.rules}
        changed = False
        kept: list[Rule] = []
        for rule in state.rules:
            if rule.id in config_ids:
                if rule.id not in state.overrides:
                    state.overrides[rule.id] = RuntimeOverride(rule=rule)
                changed = True
                continue
            kept.append(rule)
        for rule_id in list(state.overrides):
            if rule_id in config_ids:
                continue
            override = state.overrides.pop(rule_id)
            if not override.disabled and override.rule is not None:
                if not any(rule.id == rule_id for rule in kept):
                    kept.append(override.rule)
            changed = True
        state.rules = kept
        if changed:
            try:
                self._save_rules_state(state)
            except OSError as exc:
                logger.warning("写入运行时规则失败: %s", exc)

    def _compose_effective_rules(self) -> None:
        rows: list[dict[str, Any]] = []
        effective: list[Rule] = []
        for rule in self.config.rules:
            override = self._runtime_rules.overrides.get(rule.id)
            if override is not None:
                if override.disabled:
                    rows.append(rule_row(rule, "override", True))
                    continue
                if override.rule is not None:
                    rows.append(rule_row(override.rule, "override", False))
                    effective.append(override.rule)
                    continue
            rows.append(rule_row(rule, "config", False))
            effective.append(rule)
        for rule in self._runtime_rules.rules:
            rows.append(rule_row(rule, "runtime", False))
            effective.append(rule)
        self._rules = effective
        self._rule_rows = rows
        self._rule_sources = {row["id"]: str(row["source"]) for row in rows}

    def _reconcile_rule_states(self, old_rules: dict[str, Rule]) -> None:
        new_rules = {rule.id: rule for rule in self._rules}
        for key in list(self._rule_states):
            if key[1] not in new_rules:
                del self._rule_states[key]
        for rule_id, rule in new_rules.items():
            previous = old_rules.get(rule_id)
            applies = {code for code in self._codes if rule.applies_to(code)}
            if previous is None or previous != rule:
                for key in [item for item in self._rule_states if item[1] == rule_id]:
                    del self._rule_states[key]
                for code in applies:
                    self._rule_states[(code, rule_id)] = RuleState()
                continue
            for code in applies:
                self._rule_states.setdefault((code, rule_id), RuleState())
            for key in [
                item
                for item in self._rule_states
                if item[1] == rule_id and item[0] not in applies
            ]:
                del self._rule_states[key]

    def _row_from_state(
        self, state: RuntimeRulesState, rule_id: str
    ) -> Optional[dict[str, Any]]:
        config_rules = {rule.id: rule for rule in self.config.rules}
        if rule_id in config_rules:
            override = state.overrides.get(rule_id)
            if override is not None:
                if override.disabled:
                    return rule_row(config_rules[rule_id], "override", True)
                if override.rule is not None:
                    return rule_row(override.rule, "override", False)
            return rule_row(config_rules[rule_id], "config", False)
        override = state.overrides.get(rule_id)
        if override is not None and override.rule is not None:
            return rule_row(override.rule, "override", False)
        for rule in state.rules:
            if rule.id == rule_id:
                return rule_row(rule, "runtime", False)
        return None

    def _row_by_id(self, rule_id: str) -> Optional[dict[str, Any]]:
        return self._row_from_state(self._runtime_rules, rule_id)

    def _forget_code(self, code: str) -> None:
        for key in [item for item in self._rule_states if item[0] == code]:
            del self._rule_states[key]
        self._latest.pop(code, None)
        self._metrics.pop(code, None)
        self._prev_price.pop(code, None)
        self._last_exch.pop(code, None)
        self._last_advance.pop(code, None)
        self._history.pop(code, None)
        self._missing.discard(code)
        self._sources.pop(code, None)

    def maybe_reload_config(self) -> None:
        """Reload rules and alert parameters when the YAML file changed.

        A parse/validation failure leaves the running configuration untouched
        and is exposed through ``/health`` as ``config_reload_error``.
        """
        with self._lock:
            if self._config_path is None:
                return
            signature = self._config_signature()
            if signature == self._config_sig:
                return
            self._config_sig = signature
            try:
                new_config = load_config(self._config_path)
            except Exception as exc:  # noqa: BLE001 - a bad file must never stop the engine
                self._config_reload_error = f"{type(exc).__name__}: {exc}"[:500]
                logger.warning(
                    "rules action=config_reload result=error error=%s",
                    self._config_reload_error,
                )
                return
            self._apply_reloaded_config(new_config)
            self._config_reload_error = None
            logger.info(
                "rules action=config_reload result=ok rules=%s watchlist=%s",
                len(new_config.rules),
                len(new_config.watchlist),
            )

    def _apply_reloaded_config(self, new_config: WatchConfig) -> None:
        old_config = self.config
        if new_config.api != old_config.api:
            logger.warning(
                "配置 api.host/port 变更需要重启，当前实例继续监听 %s:%s",
                old_config.api.host,
                old_config.api.port,
            )
        if new_config.calendar != old_config.calendar:
            logger.warning("配置 calendar 变更需要重启，当前实例继续使用旧交易日历")
        if new_config.watchlist_runtime_file != old_config.watchlist_runtime_file:
            logger.warning("配置 watchlist_runtime_file 变更需要重启，当前实例继续使用旧路径")

        old_rules = {rule.id: rule for rule in self._rules}
        old_codes = set(self._codes)
        self.config = new_config
        self._config_codes = list(new_config.watchlist)
        config_set = set(self._config_codes)
        promoted = [code for code in self._runtime_codes if code in config_set]
        if promoted:
            self._runtime_codes = [
                code for code in self._runtime_codes if code not in config_set
            ]
            for code in promoted:
                self._runtime_names.pop(code, None)
            try:
                self._save_runtime(self._runtime_codes)
            except OSError as exc:
                logger.warning("写入运行时自选股失败: %s", exc)

        codes: list[str] = []
        for code in [*self._config_codes, *self._runtime_codes]:
            if code not in codes:
                codes.append(code)
        self._codes = codes
        self._code_set = set(codes)
        self._sources = {code: "config" for code in self._config_codes}
        self._sources.update(
            {
                code: ("plan" if code in self._plan_auto_codes else "runtime")
                for code in self._runtime_codes
            }
        )
        for code in old_codes - self._code_set:
            self._forget_code(code)
        for code in self._codes:
            self._history.setdefault(code, [])
            self._missing.discard(code)

        self._normalize_runtime_rules()
        self._compose_effective_rules()
        self._reconcile_rule_states(old_rules)

    def _load_runtime(self) -> None:
        if self._runtime is None:
            return
        state = self._runtime.load()
        limit = self.config.limits.max_watchlist
        seen = set(self._config_codes)
        for raw in state.codes:
            try:
                code = normalize_watch_code(raw)
            except SymbolError as exc:
                logger.warning("运行时自选股文件里的代码 %r 已忽略: %s", raw, exc.code)
                continue
            if code in seen:
                continue
            if len(seen) >= limit:
                logger.warning("运行时自选股超过上限 %s，多余条目已忽略", limit)
                break
            self._runtime_codes.append(code)
            seen.add(code)
            name = state.names.get(raw) or state.names.get(code)
            if name:
                self._runtime_names[code] = name

    def _save_runtime(self, codes: list[str]) -> None:
        if self._runtime is not None:
            self._runtime.save(codes)

    def _audit(self, action: str, value: Any, result: str) -> None:
        text = value if isinstance(value, str) else repr(value)
        logger.info(
            "watchlist action=%s code=%s result=%s",
            action,
            repr(str(text)[:64]),
            result,
        )

    def _entry_name(self, code: str) -> Optional[str]:
        quote = self._latest.get(code)
        if quote is not None and quote.name and quote.name.strip():
            return quote.name.strip()
        return self._runtime_names.get(code)

    def _entry(self, code: str) -> dict[str, Any]:
        return {
            "code": code,
            "name": self._entry_name(code),
            "source": self._sources.get(code),
        }

    def _watchlist_result(self, code: str, status: str) -> dict[str, Any]:
        return {
            "ok": True,
            "status": status,
            **self._entry(code),
            "count": len(self._codes),
            "limit": self.config.limits.max_watchlist,
        }

    def watchlist_dict(self) -> dict[str, Any]:
        with self._lock:
            self.maybe_reload_config()
            rows = [self._entry(code) for code in self._codes]
            return {
                "watchlist": rows,
                "count": len(rows),
                "limit": self.config.limits.max_watchlist,
            }

    def _fetch_for_add(self, code: str) -> Quote:
        try:
            quotes = self.source.fetch([code], self.clock.now())
        except Exception as exc:  # noqa: BLE001 - any source failure means "unavailable"
            logger.warning("自选股 %s 的行情验证失败: %s", code, type(exc).__name__)
            raise WatchlistError("quote_unavailable", "取不到该代码的行情，未加入自选股") from exc
        quote = quotes.get(code)
        name = str(quote.name).strip() if quote is not None and quote.name is not None else ""
        if quote is None or not name:
            raise WatchlistError("quote_unavailable", "取不到该代码的行情，未加入自选股")
        return quote

    def _apply_add(self, code: str, source: str = "runtime") -> None:
        self._codes.append(code)
        self._code_set.add(code)
        self._sources[code] = source
        for rule in self._rules:
            if rule.applies_to(code):
                self._rule_states[(code, rule.id)] = RuleState()
        self._history.setdefault(code, [])
        self._missing.discard(code)

    def _apply_remove(self, code: str) -> None:
        self._codes = [item for item in self._codes if item != code]
        self._code_set.discard(code)
        self._sources.pop(code, None)
        for key in [key for key in self._rule_states if key[0] == code]:
            del self._rule_states[key]
        self._latest.pop(code, None)
        self._metrics.pop(code, None)
        self._prev_price.pop(code, None)
        self._last_exch.pop(code, None)
        self._last_advance.pop(code, None)
        self._history.pop(code, None)
        self._missing.discard(code)

    def add_symbol(self, value: Any) -> dict[str, Any]:
        try:
            code = normalize_watch_code(value)
        except SymbolError as exc:
            self._audit("add", value, exc.code)
            raise WatchlistError(exc.code, str(exc)) from exc
        with self._lock:
            if code in self._code_set:
                if self._sources.get(code) == "plan":
                    self._plan_auto_codes.discard(code)
                    self._sources[code] = "runtime"
                    try:
                        self._save_plans()
                    except OSError as exc:
                        logger.warning("写入计划规则失败: %s", exc)
                self._audit("add", code, "already_present")
                return self._watchlist_result(code, "already_present")
            limit = self.config.limits.max_watchlist
            if len(self._codes) >= limit:
                self._audit("add", code, "watchlist_full")
                raise WatchlistError("watchlist_full", f"自选股数量已达上限 {limit} 个")
            try:
                quote = self._fetch_for_add(code)
            except WatchlistError as exc:
                self._audit("add", code, exc.code)
                raise
            names = {**self._runtime_names, code: str(quote.name).strip()}
            codes = [*self._runtime_codes, code]
            try:
                self._save_runtime(codes)
            except OSError as exc:
                logger.warning("写入运行时自选股失败: %s", exc)
                self._audit("add", code, "persistence_error")
                raise WatchlistError("persistence_error", "无法写入运行时自选股文件") from exc
            self._runtime_codes = codes
            self._runtime_names = names
            self._apply_add(code)
            self._audit("add", code, "added")
            return self._watchlist_result(code, "added")

    def remove_symbol(self, value: Any) -> dict[str, Any]:
        try:
            code = normalize_watch_code(value)
        except SymbolError as exc:
            self._audit("remove", value, exc.code)
            raise WatchlistError(exc.code, str(exc)) from exc
        with self._lock:
            if code not in self._code_set:
                self._audit("remove", code, "not_present")
                return {
                    "ok": True,
                    "status": "not_present",
                    "code": code,
                    "name": None,
                    "source": None,
                    "count": len(self._codes),
                    "limit": self.config.limits.max_watchlist,
                }
            if self._sources.get(code) == "config":
                self._audit("remove", code, "protected_symbol")
                raise WatchlistError(
                    "protected_symbol",
                    "该标的来自配置文件，不能通过接口删除；请修改 config/watch.yaml",
                )
            entry = self._entry(code)
            names = {key: val for key, val in self._runtime_names.items() if key != code}
            codes = [item for item in self._runtime_codes if item != code]
            try:
                self._save_runtime(codes)
            except OSError as exc:
                logger.warning("写入运行时自选股失败: %s", exc)
                self._audit("remove", code, "persistence_error")
                raise WatchlistError("persistence_error", "无法写入运行时自选股文件") from exc
            self._runtime_codes = codes
            self._runtime_names = names
            if self._sources.get(code) == "plan":
                self._plan_auto_codes.discard(code)
                try:
                    self._save_plans()
                except OSError as exc:
                    logger.warning("写入计划规则失败: %s", exc)
            self._apply_remove(code)
            self._audit("remove", code, "removed")
            return {
                "ok": True,
                "status": "removed",
                **entry,
                "count": len(self._codes),
                "limit": self.config.limits.max_watchlist,
            }

    def _rule_result(
        self,
        status: str,
        rule_id: str,
        before: Optional[dict[str, Any]],
        after: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": status,
            "rule_id": rule_id,
            "source": (after or {}).get("source"),
            "before": before,
            "after": after,
            "count": len(self._rules),
            "limit": self.config.limits.max_rules,
        }

    def _audit_rule(self, action: str, rule_id: str, actor: str, result: str) -> None:
        logger.info(
            "rules action=%s rule_id=%s actor=%s result=%s",
            action,
            rule_id,
            actor,
            result,
        )

    def upsert_rule(self, raw: Any, actor: Any = None) -> dict[str, Any]:
        with self._lock:
            rule = validate_rule_payload(raw)
            actor_text = sanitize_actor(actor)
            rule_id = rule.id
            before = self._row_by_id(rule_id)
            enabled_ids = {item.id for item in self._rules}
            if rule_id not in enabled_ids and len(self._rules) >= self.config.limits.max_rules:
                raise RuleError(
                    "rules_full",
                    f"规则数量已达上限 {self.config.limits.max_rules} 条",
                )

            state = self._runtime_rules.clone()
            config_ids = {item.id for item in self.config.rules}
            if rule_id in config_ids:
                state.overrides[rule_id] = RuntimeOverride(rule=rule)
            elif any(item.id == rule_id for item in state.rules):
                state.rules = [
                    rule if item.id == rule_id else item for item in state.rules
                ]
            elif rule_id in state.overrides:
                state.overrides[rule_id] = RuntimeOverride(rule=rule)
            else:
                state.rules.append(rule)

            after = self._row_from_state(state, rule_id)
            if before is None:
                status = "created"
            elif before.get("source") == "config":
                status = "override"
            elif before.get("disabled"):
                status = "override"
            else:
                status = "replaced"
            state.history.append(
                history_entry(
                    fmt_iso(self.clock.now()),
                    "upsert",
                    rule_id,
                    before,
                    after,
                    actor_text,
                )
            )
            state.history = state.history[-MAX_HISTORY:]
            try:
                self._save_rules_state(state)
            except OSError as exc:
                self._audit_rule("upsert", rule_id, actor_text, "persistence_error")
                raise RuleError("persistence_error", "无法写入运行时规则文件") from exc

            old_rules = {item.id: item for item in self._rules}
            self._runtime_rules = state
            self._compose_effective_rules()
            self._reconcile_rule_states(old_rules)
            self._audit_rule("upsert", rule_id, actor_text, status)
            return self._rule_result(status, rule_id, before, after)

    def remove_rule(self, rule_id: Any, actor: Any = None) -> dict[str, Any]:
        with self._lock:
            rule_id = validate_rule_id(rule_id)
            actor_text = sanitize_actor(actor)
            before = self._row_by_id(rule_id)
            if before is None:
                raise RuleError("rule_not_found", f"规则不存在: {rule_id}")
            if before.get("disabled"):
                return self._rule_result("already_disabled", rule_id, before, before)

            state = self._runtime_rules.clone()
            config_ids = {item.id for item in self.config.rules}
            if rule_id in config_ids:
                state.overrides[rule_id] = RuntimeOverride(disabled=True)
                status = "disabled"
            elif rule_id in state.overrides:
                state.overrides.pop(rule_id, None)
                status = "removed"
            else:
                state.rules = [item for item in state.rules if item.id != rule_id]
                status = "removed"

            after = self._row_from_state(state, rule_id)
            state.history.append(
                history_entry(
                    fmt_iso(self.clock.now()),
                    "remove",
                    rule_id,
                    before,
                    after,
                    actor_text,
                )
            )
            state.history = state.history[-MAX_HISTORY:]
            try:
                self._save_rules_state(state)
            except OSError as exc:
                self._audit_rule("remove", rule_id, actor_text, "persistence_error")
                raise RuleError("persistence_error", "无法写入运行时规则文件") from exc

            old_rules = {item.id: item for item in self._rules}
            self._runtime_rules = state
            self._compose_effective_rules()
            self._reconcile_rule_states(old_rules)
            self._audit_rule("remove", rule_id, actor_text, status)
            return self._rule_result(status, rule_id, before, after)

    def revert_rule(self, rule_id: Any, actor: Any = None) -> dict[str, Any]:
        with self._lock:
            rule_id = validate_rule_id(rule_id)
            actor_text = sanitize_actor(actor)
            before = self._row_by_id(rule_id)
            if before is None:
                raise RuleError("rule_not_found", f"规则不存在: {rule_id}")
            config_ids = {item.id for item in self.config.rules}
            if rule_id in config_ids and rule_id not in self._runtime_rules.overrides:
                return self._rule_result("unchanged", rule_id, before, before)

            state = self._runtime_rules.clone()
            if rule_id in state.overrides:
                state.overrides.pop(rule_id, None)
            else:
                state.rules = [item for item in state.rules if item.id != rule_id]

            after = self._row_from_state(state, rule_id)
            state.history.append(
                history_entry(
                    fmt_iso(self.clock.now()),
                    "revert",
                    rule_id,
                    before,
                    after,
                    actor_text,
                )
            )
            state.history = state.history[-MAX_HISTORY:]
            try:
                self._save_rules_state(state)
            except OSError as exc:
                self._audit_rule("revert", rule_id, actor_text, "persistence_error")
                raise RuleError("persistence_error", "无法写入运行时规则文件") from exc

            old_rules = {item.id: item for item in self._rules}
            self._runtime_rules = state
            self._compose_effective_rules()
            self._reconcile_rule_states(old_rules)
            self._audit_rule("revert", rule_id, actor_text, "reverted")
            return self._rule_result("reverted", rule_id, before, after)

    def rule_history(self, limit: int = 50) -> dict[str, Any]:
        with self._lock:
            rows = list(reversed(self._runtime_rules.history))[:limit]
            return {"history": rows, "count": len(rows)}

    # ------------------------------------------------------------------- plans
    def _audit_plan(self, action: str, plan_id: str, actor: str, result: str) -> None:
        logger.info(
            "plans action=%s plan_id=%s actor=%s result=%s",
            action,
            plan_id,
            actor,
            result,
        )

    def _market_snapshot(self, now: Optional[datetime] = None) -> MarketSnapshot:
        moment = now or self.clock.now()
        try:
            return self._market.snapshot(moment)
        except Exception as exc:  # noqa: BLE001 - a client bug must not break the engine
            logger.warning("市场上下文读取失败: %s", type(exc).__name__)
            return MarketSnapshot()

    def _market_payload(self, now: Optional[datetime] = None) -> dict[str, Any]:
        return snapshot_dict(self._market_snapshot(now))

    def _release_plan_code(self, code: str) -> None:
        if code not in self._plan_auto_codes:
            return
        self._plan_auto_codes.discard(code)
        if code not in self._runtime_codes:
            try:
                self._save_plans()
            except OSError as exc:
                logger.warning("写入计划规则失败: %s", exc)
            return
        codes = [item for item in self._runtime_codes if item != code]
        try:
            self._save_runtime(codes)
        except OSError as exc:
            logger.warning("写入运行时自选股失败: %s", exc)
            return
        self._runtime_codes = codes
        self._apply_remove(code)
        try:
            self._save_plans()
        except OSError as exc:
            logger.warning("写入计划规则失败: %s", exc)

    def _plan_references(self, code: str) -> list[PlanRuntime]:
        return [item for item in self._plans.values() if item.plan.code == code]

    def _release_unused_plan_codes(self, now: datetime, *, force: bool = False) -> None:
        for code in list(self._plan_auto_codes):
            if code not in self._runtime_codes:
                self._plan_auto_codes.discard(code)
                continue
            references = self._plan_references(code)
            if force:
                if references:
                    continue
                self._release_plan_code(code)
                continue
            if any(item.active for item in references) or not references:
                if not references:
                    self._release_plan_code(code)
                continue
            expired = [item.expired_at for item in references if item.expired_at is not None]
            if expired and all(self._after_one_trading_day(moment, now) for moment in expired):
                self._release_plan_code(code)

    def _after_one_trading_day(self, expired_at: datetime, now: datetime) -> bool:
        moment = to_cn(expired_at)
        for offset in range(1, 11):
            candidate_day = moment.date().fromordinal(moment.date().toordinal() + offset)
            candidate = moment.replace(
                year=candidate_day.year, month=candidate_day.month, day=candidate_day.day
            )
            if self.calendar.is_trading_day(candidate):
                return now >= candidate
        return now >= moment

    def _expire_plans(self, now: datetime) -> bool:
        changed = False
        for runtime in self._plans.values():
            if not runtime.active or runtime.plan.expires_at is None:
                continue
            if now < runtime.plan.expires_at:
                continue
            previous = runtime.state
            runtime.state = "expired"
            runtime.active = False
            runtime.expired_at = now
            runtime.since = now
            runtime.streak = 0
            runtime.pending = None
            runtime.history.append(
                {
                    "ts": fmt_iso(now),
                    "from": previous,
                    "to": "expired",
                    "reason": "计划已过期",
                }
            )
            runtime.history = runtime.history[-MAX_PLAN_HISTORY:]
            changed = True
        if changed:
            try:
                self._save_plans()
            except OSError as exc:
                logger.warning("写入计划规则失败: %s", exc)
        return changed

    def _plan_alert(
        self,
        now: datetime,
        runtime: PlanRuntime,
        previous: str,
        current: str,
        reason: str,
    ) -> None:
        last = runtime.last_alert_ts.get(current)
        if last is not None and (now - last).total_seconds() < ALERT_DEBOUNCE_SECONDS:
            return
        quote = self._latest.get(runtime.plan.code)
        metrics = self._metrics.get(runtime.plan.code)
        runtime.alert_seq += 1
        alert = {
            "id": self._next_id,
            "ts": fmt_iso(now),
            "code": runtime.plan.code,
            "name": quote.name if quote is not None else None,
            "rule_id": f"plan:{runtime.plan.id}",
            "rule_type": "plan",
            "direction": None,
            "price": quote.price if quote is not None else None,
            "prev_close": quote.prev_close if quote is not None else None,
            "change_pct": (
                (quote.price / quote.prev_close - 1.0) * 100.0
                if quote is not None and quote.prev_close > 0
                else None
            ),
            "vwap": metrics.vwap if metrics is not None else None,
            "limit_up": quote.limit_up if quote is not None else None,
            "limit_down": quote.limit_down if quote is not None else None,
            "detail": {
                "plan_id": runtime.plan.id,
                "from": previous,
                "to": current,
                "reason": reason,
                "label": runtime.plan.label,
            },
            "severity": "L1" if current == "await_confirm" else "L2",
            "dedupe_key": f"{runtime.plan.code}|plan:{runtime.plan.id}|{runtime.alert_seq}",
        }
        self._next_id += 1
        self._alerts.append(alert)
        self.store.write_alert(alert)
        runtime.last_alert_ts[current] = now

    def _evaluate_plans(self, now: datetime) -> None:
        if not self._plans:
            return
        if self._trading_day and self._session == "open":
            try:
                self._market.refresh(now)
            except Exception as exc:  # noqa: BLE001 - market-watch must not break polling
                logger.warning("市场上下文刷新失败: %s", type(exc).__name__)
        snapshot = self._market_snapshot(now)
        changed = False
        for runtime in self._plans.values():
            if not runtime.active:
                continue
            quote = self._latest.get(runtime.plan.code)
            context = EvalContext(
                now=now,
                quote=quote,
                regime=snapshot.regime,
                indexes=snapshot.indexes,
                sectors=snapshot.sectors,
            )
            target, reason, conds, _unknown = evaluate_plan(runtime.plan, context)
            runtime.conds = conds
            runtime.last_price = quote.price if quote is not None and quote.price > 0 else None
            if runtime.restored:
                runtime.restored = False
                continue
            new_state, streak, pending, stepped = step_state(
                runtime.state, target, runtime.streak, runtime.pending
            )
            runtime.streak = streak
            runtime.pending = pending
            if not stepped:
                continue
            previous = runtime.state
            runtime.state = new_state
            runtime.since = now
            runtime.history.append(
                {
                    "ts": fmt_iso(now),
                    "from": previous,
                    "to": new_state,
                    "reason": reason,
                }
            )
            runtime.history = runtime.history[-MAX_PLAN_HISTORY:]
            changed = True
            if new_state in ALERT_STATES:
                self._plan_alert(now, runtime, previous, new_state, reason)
        if changed:
            try:
                self._save_plans()
            except OSError as exc:
                logger.warning("写入计划规则失败: %s", exc)

    def _plan_status(self, before: Optional[PlanRuntime], runtime: PlanRuntime) -> str:
        if before is None:
            return "created"
        if before.plan != runtime.plan:
            return "replaced"
        return "unchanged"

    def upsert_plan(self, raw: Any, actor: Any = None) -> dict[str, Any]:
        with self._lock:
            plan = validate_plan_payload(raw)
            actor_text = sanitize_actor(actor)
            before = self._plans.get(plan.id)
            if before is None and len(self._plans) >= MAX_PLANS:
                raise PlanError(
                    "too_many_plans", f"计划数量已达上限 {MAX_PLANS} 条"
                )
            auto_add = plan.code not in self._code_set
            if auto_add and len(self._codes) >= self.config.limits.max_watchlist:
                raise PlanError(
                    "watchlist_full",
                    f"自选股数量已达上限 {self.config.limits.max_watchlist} 个",
                    field="code",
                )

            now = self.clock.now()
            old_plans = dict(self._plans)
            old_auto = set(self._plan_auto_codes)
            if before is None:
                runtime = make_runtime(plan, now)
            else:
                runtime = before.clone()
                runtime.plan = plan
                if runtime.state == "expired" and (
                    plan.expires_at is None or now < plan.expires_at
                ):
                    runtime.state = "observe"
                    runtime.active = True
                    runtime.expired_at = None
                    runtime.since = now
                    runtime.streak = 0
                    runtime.pending = None
                    runtime.restored = False
                    runtime.history.append(
                        {
                            "ts": fmt_iso(now),
                            "from": "expired",
                            "to": "observe",
                            "reason": "计划重新启用",
                        }
                    )
                    runtime.history = runtime.history[-MAX_PLAN_HISTORY:]
            self._plans[plan.id] = runtime
            if auto_add:
                self._plan_auto_codes.add(plan.code)

            try:
                self._save_plans()
            except OSError as exc:
                self._plans = old_plans
                self._plan_auto_codes = old_auto
                self._audit_plan("upsert", plan.id, actor_text, "persistence_error")
                raise PlanError("persistence_error", "无法写入计划规则文件") from exc

            if auto_add:
                codes = [*self._runtime_codes, plan.code]
                try:
                    self._save_runtime(codes)
                except OSError as exc:
                    self._plans = old_plans
                    self._plan_auto_codes = old_auto
                    try:
                        self._save_plans()
                    except OSError:
                        pass
                    self._audit_plan("upsert", plan.id, actor_text, "persistence_error")
                    raise PlanError("persistence_error", "无法写入运行时自选股文件") from exc
                self._runtime_codes = codes
                self._apply_add(plan.code, "plan")

            try:
                self._market.refresh(now)
            except Exception as exc:  # noqa: BLE001 - context is optional for upsert
                logger.warning("市场上下文刷新失败: %s", type(exc).__name__)
            self._release_unused_plan_codes(now)
            status = self._plan_status(before, runtime)
            self._audit_plan("upsert", plan.id, actor_text, status)
            return {"ok": True, "status": status, "plan": plan_state_dict(runtime)}

    def remove_plan(self, value: Any, actor: Any = None) -> dict[str, Any]:
        with self._lock:
            plan_id = value
            if not isinstance(plan_id, str) or not plan_id.strip():
                raise PlanError("invalid_plan", "缺少 id", field="id")
            plan_id = plan_id.strip()
            actor_text = sanitize_actor(actor)
            runtime = self._plans.get(plan_id)
            if runtime is None:
                raise PlanError("not_found", f"计划不存在: {plan_id}")
            code = runtime.plan.code
            del self._plans[plan_id]
            try:
                self._save_plans()
            except OSError as exc:
                self._plans[plan_id] = runtime
                raise PlanError("persistence_error", "无法写入计划规则文件") from exc
            if not self._plan_references(code):
                self._release_plan_code(code)
            self._audit_plan("remove", plan_id, actor_text, "removed")
            return {"ok": True, "status": "removed", "id": plan_id, "code": code}

    def plans_payload(self) -> dict[str, Any]:
        with self._lock:
            self.maybe_reload_config()
            now = self.clock.now()
            self._expire_plans(now)
            self._release_unused_plan_codes(now)
            return {
                "ok": True,
                "as_of": fmt_iso(now),
                "market_context": self._market_payload(now),
                "plans": [plan_state_dict(item) for item in self._plans.values()],
            }

    def plan_payload(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            self.maybe_reload_config()
            now = self.clock.now()
            self._expire_plans(now)
            runtime = self._plans.get(plan_id)
            if runtime is None:
                raise PlanError("not_found", f"计划不存在: {plan_id}")
            state = plan_state_dict(runtime)
            return {
                "ok": True,
                "plan": state,
                **state,
            }

    def plan_history(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            runtime = self._plans.get(plan_id)
            if runtime is None:
                raise PlanError("not_found", f"计划不存在: {plan_id}")
            return {
                "plan_id": plan_id,
                "history": runtime.history[-MAX_PLAN_HISTORY:],
                "count": len(runtime.history[-MAX_PLAN_HISTORY:]),
            }

    def _jittered(self, seconds: float) -> float:
        pct = self.config.polling.jitter_pct
        if pct <= 0:
            return float(seconds)
        factor = 1.0 + self.rng.uniform(-pct, pct) / 100.0
        return float(seconds) * factor

    def _latest_exchange_time(self) -> Optional[datetime]:
        if not self._last_exch:
            return None
        return max(self._last_exch.values())

    def _session_for(self, now: datetime, trading_day: bool) -> str:
        """Where ``now`` sits relative to the configured active windows.

        Unlike :meth:`WatchConfig.active_at` (which decides polling cadence and
        staleness and keeps an exclusive end), the session is inclusive on both
        ends: the closing second is still ``open``.
        """
        if not trading_day:
            return "non_trading_day"
        windows = self.config.active_windows
        if not windows:
            return "after_hours"
        clock = to_cn(now).time().replace(tzinfo=None)
        ordered = sorted(windows, key=lambda window: window[0])
        for start, end in ordered:
            if start <= clock <= end:
                return "open"
        if clock < ordered[0][0]:
            return "pre_open"
        if clock > max(end for _, end in ordered):
            return "after_hours"
        return "break"

    def _lag_for(self, now: datetime) -> Optional[float]:
        latest = self._latest_exchange_time()
        if latest is None:
            return None
        return (now - latest).total_seconds()

    def _mode_for(self, now: datetime, trading_day: bool) -> tuple[str, float]:
        if not trading_day or not self.config.active_at(now):
            return "idle", self._jittered(self.config.polling.idle_seconds)
        if self._stale:
            return "base", self._jittered(self.config.polling.base_seconds)
        hot = False
        for code in self._codes:
            quote = self._latest.get(code)
            metrics = self._metrics.get(code)
            if quote is None or metrics is None:
                continue
            for rule in self._rules:
                if not rule.applies_to(code):
                    continue
                state = self._rule_states[(code, rule.id)]
                if not state.armed:
                    continue
                distance = hot_distance(rule, quote, metrics, self._prev_price.get(code))
                if distance is not None and distance <= self.config.polling.hot_band_pct + 1e-9:
                    hot = True
                    break
            if hot:
                break
        if hot:
            self._last_hot = now
        hold = self.config.polling.fast_hold_seconds
        if hot or (
            self._last_hot is not None
            and (now - self._last_hot).total_seconds() <= hold
        ):
            return "fast", self._jittered(self.config.polling.fast_seconds)
        return "base", self._jittered(self.config.polling.base_seconds)

    def _fire(
        self,
        now: datetime,
        code: str,
        quote: Quote,
        metrics: Metrics,
        rule: Rule,
        direction: Optional[str],
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._rule_states[(code, rule.id)]
        state.fired_count += 1
        state.armed = False
        state.last_fired = now
        state.retreated = False
        alert = {
            "id": self._next_id,
            "ts": fmt_iso(now),
            "code": code,
            "name": quote.name,
            "rule_id": rule.id,
            "rule_type": rule.type,
            "direction": direction,
            "price": quote.price,
            "prev_close": quote.prev_close,
            "change_pct": metrics.change_pct,
            "vwap": metrics.vwap,
            "limit_up": quote.limit_up,
            "limit_down": quote.limit_down,
            "detail": detail,
            "dedupe_key": f"{code}|{rule.id}|{state.fired_count}",
        }
        self._next_id += 1
        self._alerts.append(alert)
        return alert

    # -------------------------------------------------------------------- poll
    def poll(self) -> PollOutcome:
        with self._lock:
            self.maybe_reload_config()
            now = self.clock.now()
            self._now = now
            self._last_poll_ts = now
            trading_day = self.calendar.is_trading_day(now)
            self._trading_day = trading_day
            self._session = self._session_for(now, trading_day)
            self._calendar_status = self.calendar.status
            active = self.config.active_at(now) and trading_day
            self._expire_plans(now)
            self._release_unused_plan_codes(now)
            fired: list[dict[str, Any]] = []
            evaluated = False
            try:
                quotes = self.source.fetch(list(self._codes), now)
                ok = True
                self._last_error = None
            except Exception as exc:  # noqa: BLE001 - any source failure triggers backoff
                quotes = {}
                ok = False
                self._last_error = str(exc)
                logger.warning("quote fetch failed at %s: %s", fmt_iso(now), exc)

            if not ok:
                self.consecutive_failures += 1
                self._health = "down" if self.consecutive_failures >= 3 else "degraded"
                if trading_day:
                    backoff = self.config.polling.backoff_seconds
                    index = min(self.consecutive_failures - 1, len(backoff) - 1)
                    interval = self._jittered(backoff[index])
                    mode = "backoff"
                else:
                    interval = self._jittered(self.config.polling.idle_seconds)
                    mode = "idle"
                    self._stale = False
                self._mode = mode
                self._next_interval = interval
                self._lag_seconds = self._lag_for(now)
                self.store.write_poll(
                    {
                        "t": fmt_iso(now),
                        "ok": False,
                        "mode": mode,
                        "next_interval": interval,
                        "stale": self._stale,
                        "health": self._health,
                        "consecutive_failures": self.consecutive_failures,
                        "lag_seconds": self._lag_seconds,
                        "max_lag_seconds": self.config.polling.max_lag_seconds,
                        "trading_day": trading_day,
                        "calendar_status": self._calendar_status,
                        "session": self._session,
                        "last_rule_eval_ts": (
                            fmt_iso(self._last_rule_eval_ts) if self._last_rule_eval_ts else None
                        ),
                    }
                )
                self._write_state()
                return PollOutcome(
                    ok=False,
                    mode=mode,
                    next_interval=interval,
                    health=self._health,
                    stale=self._stale,
                )

            self.consecutive_failures = 0
            fresh: dict[str, Quote] = {}
            for code, quote in quotes.items():
                if code not in self._code_set:
                    continue
                previous_exch = self._last_exch.get(code)
                if previous_exch is not None and quote.exch_time <= previous_exch:
                    continue
                self._last_exch[code] = quote.exch_time
                self._last_advance[code] = now
                fresh[code] = quote
                self._missing.discard(code)
                self._latest[code] = quote
                self._metrics[code] = compute_metrics(quote)

            self._missing = {code for code in self._codes if code not in quotes}
            self._lag_seconds = self._lag_for(now)

            threshold = self.config.polling.stale_after_seconds
            max_lag = self.config.polling.max_lag_seconds
            if not active or not self._last_exch:
                self._stale = False
            else:
                last_advance = max(self._last_advance.values(), default=now)
                not_advancing = (
                    not fresh and (now - last_advance).total_seconds() > threshold
                )
                # A source can keep advancing its exchange timestamp while still
                # trailing wall time (slow vendor feed); that is stale too.  Take
                # the newest timestamp across the watchlist so one suspended stock
                # cannot make every other quote look stale.
                data_received = any(code in self._code_set for code in quotes)
                lagging = (
                    data_received
                    and self._lag_seconds is not None
                    and self._lag_seconds > max_lag
                )
                self._stale = not_advancing or lagging
            self._health = "stale" if self._stale else "ok"

            # State (latest price, flow history) advances for every valid snapshot,
            # even outside the active window; only rule evaluation is gated below.
            for code, quote in fresh.items():
                if quote.price <= 0:
                    self._prev_price[code] = quote.price
                    continue
                metrics = self._metrics[code]
                prev_price = self._prev_price.get(code)
                history = self._history.setdefault(code, [])
                if quote.amount_yuan is not None:
                    history.append((now, quote.amount_yuan))
                if self._session == "open" and not self._stale:
                    evaluated = True
                    for rule in self._rules:
                        if not rule.applies_to(code):
                            continue
                        state = self._rule_states[(code, rule.id)]
                        if state.armed:
                            result = trigger(rule, quote, metrics, prev_price, history, now)
                            if result is not None:
                                direction, detail = result
                                alert = self._fire(now, code, quote, metrics, rule, direction, detail)
                                self.store.write_alert(alert)
                                fired.append(alert)
                        else:
                            if retreated(
                                rule,
                                quote,
                                metrics,
                                prev_price,
                                history,
                                now,
                                self.config.alerts.rearm_pct,
                            ):
                                state.retreated = True
                            last_fired = state.last_fired
                            if (
                                state.retreated
                                and last_fired is not None
                                and (now - last_fired).total_seconds()
                                >= self.config.alerts.cooldown_seconds
                            ):
                                state.armed = True
                                # Re-armed on this snapshot; if the condition still holds it
                                # fires on the next valid snapshot, per the spec.
                self._prev_price[code] = quote.price

            if evaluated:
                self._last_rule_eval_ts = now

            if active and self._plans:
                self._evaluate_plans(now)
                self._release_unused_plan_codes(now)

            mode, interval = self._mode_for(now, trading_day)
            self._mode = mode
            self._next_interval = interval
            self.store.write_poll(
                {
                    "t": fmt_iso(now),
                    "ok": True,
                    "mode": mode,
                    "next_interval": interval,
                    "stale": self._stale,
                    "health": self._health,
                    "consecutive_failures": 0,
                    "lag_seconds": self._lag_seconds,
                    "max_lag_seconds": max_lag,
                    "trading_day": trading_day,
                    "calendar_status": self._calendar_status,
                    "session": self._session,
                    "last_rule_eval_ts": (
                        fmt_iso(self._last_rule_eval_ts) if self._last_rule_eval_ts else None
                    ),
                }
            )
            self._write_state()
            return PollOutcome(
                ok=True,
                mode=mode,
                next_interval=interval,
                health=self._health,
                stale=self._stale,
                alerts=fired,
            )

    # -------------------------------------------------------------------- views
    def _quotes_state(self) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for code in self._codes:
            quote = self._latest.get(code)
            if quote is None:
                continue
            item = quote.as_dict()
            metrics = self._metrics.get(code)
            if metrics is not None:
                item.update(metrics.as_dict())
            output[code] = item
        return output

    def _rules_state(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in self._codes:
            for rule in self._rules:
                if not rule.applies_to(code):
                    continue
                state = self._rule_states[(code, rule.id)]
                rows.append(
                    {
                        "code": code,
                        "rule_id": rule.id,
                        "source": self._rule_sources.get(rule.id),
                        "armed": state.armed,
                        "last_fired": fmt_iso(state.last_fired) if state.last_fired else None,
                        "fired_count": state.fired_count,
                    }
                )
        return rows

    def state_dict(self) -> dict[str, Any]:
        with self._lock:
            self.maybe_reload_config()
            last_exch = self._latest_exchange_time()
            return {
                "updated_at": fmt_iso(self._now) if self._now else None,
                "health": self._health,
                "status": self._health,
                "mode": self._mode,
                "next_interval": self._next_interval,
                "stale": self._stale,
                "trading_day": self._trading_day,
                "calendar_status": self._calendar_status,
                "session": self._session,
                "last_rule_eval_ts": (
                    fmt_iso(self._last_rule_eval_ts) if self._last_rule_eval_ts else None
                ),
                "lag_seconds": self._lag_seconds,
                "max_lag_seconds": self.config.polling.max_lag_seconds,
                "consecutive_failures": self.consecutive_failures,
                "last_poll_ts": fmt_iso(self._last_poll_ts) if self._last_poll_ts else None,
                "last_exchange_time": fmt_iso(last_exch) if last_exch else None,
                "last_error": self._last_error,
                "config_reload_error": self._config_reload_error,
                "missing": sorted(self._missing),
                "quotes": self._quotes_state(),
                "rules": self._rules_state(),
                "watchlist": [self._entry(code) for code in self._codes],
                "market_context": self._market_payload(self._now),
                "plan_count": len(self._plans),
            }

    def health_dict(self) -> dict[str, Any]:
        state = self.state_dict()
        return {
            "status": state["health"],
            "health": state["health"],
            "mode": state["mode"],
            "next_interval": state["next_interval"],
            "consecutive_failures": state["consecutive_failures"],
            "last_poll_ts": state["last_poll_ts"],
            "last_exchange_time": state["last_exchange_time"],
            "stale": state["stale"],
            "trading_day": state["trading_day"],
            "calendar_status": state["calendar_status"],
            "session": state["session"],
            "last_rule_eval_ts": state["last_rule_eval_ts"],
            "lag_seconds": state["lag_seconds"],
            "max_lag_seconds": state["max_lag_seconds"],
            "config_reload_error": state["config_reload_error"],
            "market_context": state["market_context"],
            "plan_count": state["plan_count"],
        }

    def rules_payload(self) -> dict[str, Any]:
        with self._lock:
            self.maybe_reload_config()
            rules = [dict(row) for row in self._rule_rows]
            return {
                "rules": rules,
                "count": len(rules),
                "enabled_count": len(self._rules),
            }

    def alerts(self, after_id: Optional[int] = None, limit: int = 100) -> dict[str, Any]:
        with self._lock:
            rows = [
                dict(alert)
                for alert in self._alerts
                if after_id is None or int(alert.get("id", 0)) > after_id
            ]
            rows.sort(key=lambda item: int(item.get("id", 0)))
            rows = rows[:limit]
            return {"alerts": rows, "count": len(rows)}

    def _write_state(self) -> None:
        self.store.write_state(self.state_dict())

    def run(
        self,
        stop: Any,
        end_at: Optional[datetime] = None,
    ) -> None:
        """Poll until ``stop`` is set (or ``end_at`` passes in simulated time)."""
        while not stop.is_set():
            now = self.clock.now()
            if end_at is not None and now > end_at:
                break
            outcome = self.poll()
            self.clock.sleep(outcome.next_interval)


def run_once(
    config: WatchConfig,
    source: Source,
    clock: Clock,
    store: Store,
    calendar: Optional[TradingCalendar] = None,
) -> dict[str, Any]:
    if not config.rules and not config.watchlist:
        raise ConfigError("空配置")
    engine = Engine(config, source, clock, store, calendar=calendar)
    outcome = engine.poll()
    state = engine.state_dict()
    return {
        "snapshot_time": fmt_iso(clock.now()),
        "health": state["health"],
        "stale": state["stale"],
        "mode": state["mode"],
        "trading_day": state["trading_day"],
        "calendar_status": state["calendar_status"],
        "quotes": state["quotes"],
        "missing": state["missing"],
        "alerts": outcome.alerts,
    }
