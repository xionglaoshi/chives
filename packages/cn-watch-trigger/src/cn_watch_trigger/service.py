"""Alert filtering, budgets and the trigger -> analysis -> file loop."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .clock import format_moment, parse_moment
from .config import TriggerConfig
from .engine import EngineClient, EngineError
from .runner import RunResult, run_runner
from .store import AnalysisStore, State, StateError

logger = logging.getLogger("cn_watch_trigger")
ACTUAL_STATUSES = {"done", "failed", "timeout"}

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class CycleResult:
    fetched: int = 0
    processed: int = 0
    baseline: int | None = None


def _alert_code(alert: dict[str, Any]) -> str:
    value = alert.get("code")
    return value if isinstance(value, str) else ""


def _alert_rule(alert: dict[str, Any]) -> str:
    value = alert.get("rule_id")
    return value if isinstance(value, str) else ""


def _is_plan_alert(alert: dict[str, Any]) -> bool:
    rule_type = alert.get("rule_type")
    if isinstance(rule_type, str) and rule_type == "plan":
        return True
    return _alert_rule(alert).startswith("plan:")


def _header_value(value: Any) -> str:
    if value is None:
        return "（无）"
    text = " ".join(str(value).split())
    return text or "（无）"


def build_prompt(template_text: str, alert: dict[str, Any]) -> str:
    alert_json = json.dumps(alert, ensure_ascii=False, indent=2)
    # Keep third-party text from closing the <alert_data> block early. JSON escapes
    # decode back to the original value, so every field is still passed unchanged.
    alert_json = alert_json.replace("<", "\\u003c").replace(">", "\\u003e")
    return template_text.replace("{alert_json}", alert_json)


def render_analysis(alert: dict[str, Any], result: RunResult) -> str:
    session = result.session_id if result.session_id else "（无）"
    header = [
        f"# 告警分析 {alert['id']}",
        "",
        f"- 告警 ID：{alert['id']}",
        f"- 告警时间：{_header_value(alert.get('ts'))}",
        f"- 代码：{_header_value(alert.get('code'))}",
        f"- 名称：{_header_value(alert.get('name'))}",
        f"- 规则：{_header_value(alert.get('rule_id'))}",
        f"- 状态：{result.status}",
        f"- 开始时间：{format_moment(result.started_at)}",
        f"- 结束时间：{format_moment(result.finished_at)}",
        f"- sessionId：{_header_value(session)}",
        "",
        "## 分析",
        "",
    ]
    if result.status == "done":
        body = result.text or ""
    else:
        body = f"运行未完成：{result.reason or result.status}"
    return "\n".join(header) + body.rstrip("\n") + "\n"


class TriggerService:
    def __init__(
        self,
        config: TriggerConfig,
        client: EngineClient,
        store: AnalysisStore,
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

    def _selected(self, alert: dict[str, Any]) -> bool:
        rule_id = _alert_rule(alert)
        code = _alert_code(alert).upper()
        for trigger in self.config.triggers:
            rule_match = "*" in trigger.rule_ids or rule_id in trigger.rule_ids
            code_match = "*" in trigger.codes or code in trigger.codes
            if rule_match and code_match:
                return True
        return False

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

    def _advance(self, state: State, alert_id: int) -> None:
        state.last_alert_id = alert_id
        self.store.save_state(state)

    def _record_skip(self, state: State, alert: dict[str, Any], reason: str) -> None:
        record = {
            "alert_id": alert["id"],
            "code": _alert_code(alert),
            "rule_id": _alert_rule(alert),
            "status": "skipped",
            "reason": reason,
        }
        self.store.append_record(record)
        self._advance(state, alert["id"])
        logger.info("告警 %s 跳过（%s）", alert["id"], reason)

    def _cooldown_active(self, state: State, alert: dict[str, Any], alert_ts: datetime) -> bool:
        key = f"{_alert_code(alert)}|{_alert_rule(alert)}"
        previous = state.last_run_ts.get(key)
        if not previous:
            return False
        try:
            previous_ts = parse_moment(previous)
        except ValueError:
            return False
        return (alert_ts - previous_ts).total_seconds() < self.config.limits.cooldown_seconds

    def _run_alert(self, state: State, alert: dict[str, Any], alert_ts: datetime) -> None:
        prompt = build_prompt(self.config.template_text, alert)
        result = run_runner(
            self.config.runner,
            prompt,
            self.config.limits.run_timeout_seconds,
            self.clock,
        )
        content = render_analysis(alert, result)
        path = self.store.write_analysis(alert["id"], content)
        record: dict[str, Any] = {
            "alert_id": alert["id"],
            "code": _alert_code(alert),
            "rule_id": _alert_rule(alert),
            "status": result.status,
            "started_at": format_moment(result.started_at),
            "finished_at": format_moment(result.finished_at),
            "file": str(path),
        }
        if result.session_id:
            record["session_id"] = result.session_id
        if result.reason:
            record["reason"] = result.reason
        self.store.append_record(record)
        state.last_run_ts[f"{_alert_code(alert)}|{_alert_rule(alert)}"] = format_moment(alert_ts)
        self._advance(state, alert["id"])
        logger.info("告警 %s 运行 %s", alert["id"], result.status)

    def _process_alert(self, state: State, alert: dict[str, Any]) -> None:
        if self.store.stop_requested():
            self._record_skip(state, alert, "kill_switch")
            return
        if _is_plan_alert(alert):
            self._record_skip(state, alert, "plan_alert")
            return
        if not self._selected(alert):
            self._record_skip(state, alert, "not_selected")
            return
        try:
            alert_ts = parse_moment(str(alert.get("ts")))
        except ValueError:
            self._record_skip(state, alert, "invalid_alert_ts")
            return
        now = self.clock()
        age = (now - alert_ts).total_seconds()
        if age > self.config.limits.max_alert_age_seconds:
            self._record_skip(state, alert, "stale_alert")
            return
        if self._cooldown_active(state, alert, alert_ts):
            self._record_skip(state, alert, "cooldown")
            return
        if self._runs_on(now.date()) >= self.config.limits.max_runs_per_day:
            self._record_skip(state, alert, "daily_limit")
            return
        if self.dry_run:
            self._record_skip(state, alert, "dry_run")
            return
        self._run_alert(state, alert, alert_ts)

    def run_cycle(self) -> CycleResult:
        state = self.store.load_state()
        if state is None and self.from_id is None:
            latest = self.client.latest_alert_id()
            state = State(last_alert_id=latest, last_run_ts={})
            self.store.save_state(state)
            logger.info("没有状态文件且未指定 --from-id：基线设为 %s，不分析历史告警", latest)
            return CycleResult(baseline=latest)

        if state is None:
            assert self.from_id is not None
            state = State(last_alert_id=self.from_id, last_run_ts={})
            self.store.save_state(state)

        if self.from_id is not None and state.last_alert_id != self.from_id:
            state.last_alert_id = self.from_id
            self.store.save_state(state)

        cursor = state.last_alert_id
        assert cursor is not None
        rows = [row for row in self.client.alerts_after(cursor) if row["id"] > cursor]
        if not rows:
            return CycleResult()
        rows.sort(key=lambda row: row["id"])

        overflow: list[dict[str, Any]] = []
        if len(rows) > self.config.limits.max_queue:
            overflow = rows[: len(rows) - self.config.limits.max_queue]
            rows = rows[-self.config.limits.max_queue :]
        for alert in overflow:
            reason = "plan_alert" if _is_plan_alert(alert) else "queue_overflow"
            self._record_skip(state, alert, reason)
        for alert in rows:
            self._process_alert(state, alert)
        return CycleResult(fetched=len(overflow) + len(rows), processed=len(overflow) + len(rows))

    def run_forever(self, stop: threading.Event) -> int:
        while not stop.is_set():
            try:
                self.run_cycle()
            except EngineError as exc:
                logger.warning("读取 engine 失败：%s", exc)
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
