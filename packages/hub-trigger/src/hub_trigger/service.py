"""Trigger queue filtering, budgets and the trigger -> fast judgement loop."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .clock import format_moment, parse_moment
from .config import FastJudgeConfig
from .hub import HubClient, HubError
from .parse import parse_judgement
from .render import build_prompt
from .runner import RunResult, run_runner
from .store import FastJudgeStore, State, StateError

logger = logging.getLogger("hub_trigger")

ACTUAL_STATUSES = {"done", "failed", "timeout"}
REGIME_KINDS = {"regime", "emergency"}

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class CycleResult:
    fetched: int = 0
    processed: int = 0
    baseline: int | None = None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _reason(trigger: dict[str, Any]) -> str:
    return " ".join(_text(trigger.get("reason")).split())


def cooldown_key(trigger: dict[str, Any]) -> str:
    kind = _text(trigger.get("kind"))
    if kind in REGIME_KINDS:
        return f"{kind}|{_reason(trigger)}"
    card_id = trigger.get("card_id")
    if isinstance(card_id, bool) or not isinstance(card_id, int):
        return f"{kind}|{_reason(trigger)}"
    return f"card|{card_id}|{_text(trigger.get('to_state'))}"


class FastJudgeService:
    def __init__(
        self,
        config: FastJudgeConfig,
        client: HubClient,
        store: FastJudgeStore,
        clock: Clock,
        *,
        dry_run: bool = False,
        from_id: int | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.store = store
        self.clock = clock
        self.dry_run = dry_run
        self.from_id = from_id

    def _runs_on(self, day: Any) -> int:
        count = 0
        for record in self.store.read_records():
            if record.get("status") not in ACTUAL_STATUSES:
                continue
            started = record.get("started_at")
            if not isinstance(started, str):
                continue
            try:
                moment = parse_moment(started)
            except ValueError:
                continue
            if moment.date() == day:
                count += 1
        return count

    def _advance(self, state: State, trigger_id: int) -> None:
        state.last_trigger_id = trigger_id
        self.store.save_state(state)

    def _record_skip(self, state: State, trigger: dict[str, Any], reason: str) -> None:
        record = {
            "trigger_id": trigger["id"],
            "kind": _text(trigger.get("kind")),
            "code": _text(trigger.get("code")),
            "status": "skipped",
            "reason": reason,
        }
        self.store.append_record(record)
        self._advance(state, trigger["id"])
        logger.info("触发 %s 跳过（%s）", trigger["id"], reason)

    def _cooldown_active(self, state: State, trigger: dict[str, Any], moment: datetime) -> bool:
        previous = state.last_run_ts.get(cooldown_key(trigger))
        if not previous:
            return False
        try:
            previous_ts = parse_moment(previous)
        except ValueError:
            return False
        return (moment - previous_ts).total_seconds() < self.config.limits.cooldown_seconds

    def _record_run(
        self,
        trigger: dict[str, Any],
        result: RunResult,
        duration_ms: int,
        *,
        action: str | None = None,
        outcome: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "trigger_id": trigger["id"],
            "kind": _text(trigger.get("kind")),
            "code": _text(trigger.get("code")),
            "status": result.status,
            "duration_ms": duration_ms,
            "started_at": format_moment(result.started_at),
            "finished_at": format_moment(result.finished_at),
        }
        if action is not None:
            record["action"] = action
        if outcome is not None:
            record["result"] = outcome
        if reason_code is not None:
            record["reason_code"] = reason_code
        if result.reason and result.status != "done":
            record["error"] = result.reason
        self.store.append_record(record)
        logger.info("触发 %s 运行 %s%s", trigger["id"], result.status, f"/{outcome}" if outcome else "")

    def _submit(self, trigger: dict[str, Any], judgement: Any) -> tuple[str, str | None]:
        try:
            payload = self.client.judge(
                trigger["id"],
                action=judgement.action,
                reason=judgement.reason,
                next_check=judgement.next_check,
                risk=judgement.risk,
            )
        except HubError as exc:
            logger.warning("触发 %s 判断回写失败：%s", trigger["id"], exc)
            return "judgement_rejected", "hub_unreachable"
        if payload.get("ok") is False:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            return "judgement_rejected", code if isinstance(code, str) else "rejected"
        return "written", None

    def _run_trigger(self, state: State, trigger: dict[str, Any], moment: datetime) -> None:
        if trigger.get("context_ready") is False:
            self._record_skip(state, trigger, "no_context")
            return
        try:
            context = self.client.context(trigger["id"])
        except HubError as exc:
            logger.warning("触发 %s 取不到上下文包：%s", trigger["id"], exc)
            self._record_skip(state, trigger, "no_context")
            return
        try:
            prompt = build_prompt(self.config.template_text, context)
        except Exception as exc:  # RenderError and unexpected serialization failures
            logger.warning("触发 %s 渲染提示词失败：%s", trigger["id"], exc)
            self._record_skip(state, trigger, "render_error")
            return

        started = time.monotonic()
        result = run_runner(
            self.config.runner,
            prompt,
            self.config.limits.run_timeout_seconds,
            self.clock,
        )
        duration_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        state.last_run_ts[cooldown_key(trigger)] = format_moment(moment)

        if result.status != "done":
            self._record_run(trigger, result, duration_ms)
            self._advance(state, trigger["id"])
            return

        judgement = parse_judgement(result.text)
        if judgement is None:
            self._record_run(trigger, result, duration_ms, outcome="unparsed")
            self._advance(state, trigger["id"])
            return

        outcome, reason_code = self._submit(trigger, judgement)
        self._record_run(
            trigger,
            result,
            duration_ms,
            action=judgement.action,
            outcome=outcome,
            reason_code=reason_code,
        )
        self._advance(state, trigger["id"])

    def _process_trigger(self, state: State, trigger: dict[str, Any]) -> None:
        if self.store.stop_requested():
            self._record_skip(state, trigger, "kill_switch")
            return
        try:
            moment = parse_moment(_text(trigger.get("ts")))
        except ValueError:
            self._record_skip(state, trigger, "invalid_trigger_ts")
            return
        now = self.clock()
        age = (now - moment).total_seconds()
        if age > self.config.limits.max_trigger_age_seconds:
            self._record_skip(state, trigger, "stale_trigger")
            return
        if self._cooldown_active(state, trigger, moment):
            self._record_skip(state, trigger, "cooldown")
            return
        if self._runs_on(now.date()) >= self.config.limits.max_runs_per_day:
            self._record_skip(state, trigger, "daily_limit")
            return
        if self.dry_run:
            self._record_skip(state, trigger, "dry_run")
            return
        self._run_trigger(state, trigger, moment)

    def run_cycle(self) -> CycleResult:
        state = self.store.load_state()
        if state is None and self.from_id is None:
            latest = self.client.latest_trigger_id()
            state = State(last_trigger_id=latest, last_run_ts={})
            self.store.save_state(state)
            logger.info("没有状态文件且未指定 --from-id：基线设为 %s，不处理历史触发", latest)
            return CycleResult(baseline=latest)

        if state is None:
            assert self.from_id is not None
            state = State(last_trigger_id=self.from_id, last_run_ts={})
            self.store.save_state(state)

        if self.from_id is not None and state.last_trigger_id != self.from_id:
            state.last_trigger_id = self.from_id
            self.store.save_state(state)

        cursor = state.last_trigger_id
        assert cursor is not None
        rows = [row for row in self.client.triggers_since(cursor) if row["id"] > cursor]
        if not rows:
            return CycleResult()
        rows.sort(key=lambda row: row["id"])

        overflow: list[dict[str, Any]] = []
        if len(rows) > self.config.limits.max_queue:
            overflow = rows[: len(rows) - self.config.limits.max_queue]
            rows = rows[-self.config.limits.max_queue :]
        for trigger in overflow:
            self._record_skip(state, trigger, "queue_overflow")
        for trigger in rows:
            self._process_trigger(state, trigger)
        return CycleResult(fetched=len(overflow) + len(rows), processed=len(overflow) + len(rows))

    def run_forever(self, stop: threading.Event) -> int:
        while not stop.is_set():
            try:
                self.run_cycle()
            except HubError as exc:
                logger.warning("读取 hub 失败：%s", exc)
            except StateError as exc:
                logger.error("状态文件损坏，停止：%s", exc)
                return 1
            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("本轮处理失败")
                return 1
            if stop.wait(self.config.poll_seconds):
                break
        return 0
