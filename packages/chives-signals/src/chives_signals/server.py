"""Loopback HTTP API for chives-hub (127.0.0.1:8867 by default).

Read endpoints are plain GET.  The three write endpoints accept only
``POST + application/json`` with a strict 64 KiB body cap, reject unknown
fields, and only change signal/plan state -- they can never place an order.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, urlsplit

from .engine import SignalActionError
from .plans import PlanError
from .spark import SparkParamError
from .validation import ApiError

logger = logging.getLogger("chives_signals.server")

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
MAX_BODY_BYTES = 64 * 1024
SIGNAL_PATH = re.compile(r"^/signals/([0-9]+)$")
SIGNAL_ACTION_PATH = re.compile(r"^/signals/([0-9]+)/action$")
PLAN_ACTION_PATH = re.compile(r"^/plans/([0-9]+)/action$")
SETTING_ACTION_PATH = re.compile(r"^/settings/([a-z0-9_]+)/action$")
SETTING_SUGGEST_PATH = re.compile(r"^/settings/([a-z0-9_]+)/suggest$")
REVIEW_DETAIL_PATH = re.compile(r"^/reviews/([0-9]{4}-[0-9]{2}-[0-9]{2})$")
CARD_DETAIL_PATH = re.compile(r"^/cards/([0-9]+)$")
CARD_ACTION_PATH = re.compile(r"^/cards/([0-9]+)/action$")
TRIGGER_CONTEXT_PATH = re.compile(r"^/triggers/([0-9]+)/context$")
TRIGGER_JUDGEMENT_PATH = re.compile(r"^/triggers/([0-9]+)/judgement$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class BadRequest(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class HubHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], engine: Any) -> None:
        self.engine = engine
        super().__init__(address, HubRequestHandler)


class HubRequestHandler(BaseHTTPRequestHandler):
    server_version = "chives-signals/0.1"
    timeout = 5

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    # -- responses -------------------------------------------------------
    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str, *, private: bool = False) -> None:
        payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
        if private:
            payload["private"] = True
        self._send(status, payload)

    def _reject_method(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, POST")
        body = json.dumps({"ok": False, "error": {"code": "method_not_allowed", "message": "只允许 GET/POST"}}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- host / body -----------------------------------------------------
    def _host_allowed(self) -> bool:
        host = self.headers.get("Host")
        if not host:
            return True
        parsed = urlsplit("//" + host.strip())
        return parsed.hostname in LOOPBACK_HOSTS

    def _read_json(self) -> dict[str, Any]:
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise BadRequest("invalid_content_type", "Content-Type 必须是 application/json")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise BadRequest("missing_content_length", "缺少 Content-Length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise BadRequest("invalid_content_length", "Content-Length 非法") from exc
        if length < 0:
            raise BadRequest("invalid_content_length", "Content-Length 非法")
        if length > MAX_BODY_BYTES:
            raise BadRequest("body_too_large", "请求体不得超过 64KB", status=413)
        try:
            body = self.rfile.read(length)
        except OSError as exc:
            raise BadRequest("bad_body", "无法读取请求体") from exc
        if len(body) != length:
            raise BadRequest("bad_body", "请求体被截断")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BadRequest("invalid_json", "请求体必须是 UTF-8 JSON") from exc

        def reject_constant(value: str) -> Any:
            raise ValueError(f"unsupported constant {value}")

        try:
            payload = json.loads(text, parse_constant=reject_constant)
        except (json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise BadRequest("invalid_json", "请求体必须是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise BadRequest("invalid_json", "请求体必须是 JSON 对象")
        return payload

    @staticmethod
    def _only(payload: Mapping[str, Any], allowed: set[str]) -> None:
        extra = sorted(set(payload) - allowed)
        if extra:
            raise BadRequest("unexpected_field", "不支持的字段: " + ", ".join(extra))

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._error(403, "forbidden_host", "只接受回环 Host")
            return
        engine = self.server.engine  # type: ignore[attr-defined]
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if path == "/health":
                self._send(200, engine.health_dict())
                return
            if path == "/signals":
                self._get_signals(engine, query)
                return
            match = SIGNAL_PATH.match(path)
            if match:
                payload = engine.signal_detail(int(match.group(1)))
                if payload is None:
                    self._error(404, "signal_not_found", "信号不存在")
                else:
                    self._send(200, payload)
                return
            if path == "/plans":
                status = self._one(query, "status", "all")
                self._send(200, engine.plans_payload(status))
                return
            if path == "/portfolio/overview":
                self._send(200, engine.overview())
                return
            if path == "/portfolio/history":
                days = self._int_param(query, "days", 90, minimum=1, maximum=3650)
                self._send(200, engine.history(days))
                return
            if path == "/spark":
                self._get_spark(engine, query)
                return
            if path == "/settings":
                self._send(200, engine.settings_payload())
                return
            if path == "/discipline":
                self._send(200, engine.discipline())
                return
            if path == "/review-data":
                self._send(200, engine.review_data())
                return
            if path == "/reviews":
                self._get_reviews(engine, query)
                return
            match = REVIEW_DETAIL_PATH.match(path)
            if match:
                kind = self._one(query, "kind", "evening")
                if kind not in {"evening", "premarket"}:
                    raise BadRequest("invalid_param", "kind 只接受 evening/premarket")
                payload = engine.review_detail(match.group(1), kind)
                if payload is None:
                    self._error(404, "review_not_found", "复盘不存在")
                else:
                    self._send(200, payload)
                return
            if path == "/cards":
                status = self._one(query, "status", "all")
                if status not in {"proposed", "active", "closed", "expired", "cancelled", "all"}:
                    raise BadRequest("invalid_param", "status 只接受 proposed/active/closed/all")
                day = self._one(query, "date", "") or None
                if day is not None and not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", day):
                    raise BadRequest("invalid_param", "date 必须是 YYYY-MM-DD")
                self._send(200, engine.cards_payload(status=status, day=day))
                return
            match = CARD_DETAIL_PATH.match(path)
            if match:
                payload = engine.card_detail(int(match.group(1)))
                if payload is None:
                    self._error(404, "card_not_found", "作战卡不存在")
                else:
                    self._send(200, payload)
                return
            if path == "/candidates/stats":
                days = self._int_param(query, "days", 20, minimum=1, maximum=365)
                self._send(200, engine.candidates_stats(days=days))
                return
            if path == "/triggers":
                self._get_triggers(engine, query)
                return
            match = TRIGGER_CONTEXT_PATH.match(path)
            if match:
                payload = engine.trigger_context(int(match.group(1)))
                if payload is None:
                    self._error(404, "not_found", "触发不存在")
                else:
                    self._send(200, payload)
                return
            if path == "/guidance":
                self._get_guidance(engine, query)
                return
            self._error(404, "not_found", f"未知路径: {path}")
        except BadRequest as exc:
            self._error(200, exc.code, exc.message)
        except SparkParamError as exc:
            self._error(200, "bad_params", exc.message)
        except PlanError as exc:
            self._error(200, exc.code, exc.message)
        except ApiError as exc:
            self._error(exc.status, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - never leak holdings or stack traces
            if path.startswith("/portfolio/"):
                logger.warning("portfolio endpoint failed: %s", type(exc).__name__)
                self._error(200, "portfolio_unavailable", "持仓视图暂不可用", private=True)
            else:
                logger.warning("GET failed: %s", type(exc).__name__)
                self._error(200, "internal_error", "服务内部错误")

    def _get_signals(self, engine: Any, query: Mapping[str, list[str]]) -> None:
        status = self._one(query, "status", "active")
        if status not in {"active", "snoozed", "done", "all"}:
            raise BadRequest("invalid_param", "status 只接受 active/snoozed/done/all")
        decide: Optional[bool] = None
        if "decide" in query:
            raw = self._one(query, "decide", "")
            if raw not in {"0", "1"}:
                raise BadRequest("invalid_param", "decide 只接受 0/1")
            decide = raw == "1"
        object_type: Optional[str] = None
        if "object" in query:
            object_type = self._one(query, "object", "")
            if object_type not in {"stock", "sector", "market"}:
                raise BadRequest("invalid_param", "object 只接受 stock/sector/market")
        limit = self._int_param(query, "limit", 50, minimum=1, maximum=200)
        since_id = self._int_param(query, "since_id", 0, minimum=0, maximum=2**31 - 1)
        payload = engine.signals_payload(
            status=status,
            decide=decide,
            object_type=object_type,
            limit=limit,
            since_id=since_id,
        )
        self._send(200, payload)

    def _get_spark(self, engine: Any, query: Mapping[str, list[str]]) -> None:
        extra = sorted(set(query) - {"codes"})
        if extra:
            raise SparkParamError("不支持的参数: " + ", ".join(extra))
        values = query.get("codes")
        if values is None or len(values) != 1:
            raise SparkParamError("codes 必须且只能出现一次")
        self._send(200, engine.spark_payload(values[0]))

    def _get_reviews(self, engine: Any, query: Mapping[str, list[str]]) -> None:
        extra = sorted(set(query) - {"limit", "kind"})
        if extra:
            raise BadRequest("invalid_param", "不支持的参数: " + ", ".join(extra))
        limit = self._int_param(query, "limit", 20, minimum=1, maximum=200)
        kind = self._one(query, "kind", "") or None
        if kind is not None and kind not in {"evening", "premarket"}:
            raise BadRequest("invalid_param", "kind 只接受 evening/premarket")
        self._send(200, engine.reviews_payload(limit=limit, kind=kind))

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._error(403, "forbidden_host", "只接受回环 Host")
            return
        engine = self.server.engine  # type: ignore[attr-defined]
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            payload = self._read_json()
            match = SIGNAL_ACTION_PATH.match(path)
            if match:
                self._post_signal_action(engine, int(match.group(1)), payload)
                return
            if path == "/plans":
                self._send(200, {"ok": True, "plan": engine.create_plan(payload)})
                return
            match = PLAN_ACTION_PATH.match(path)
            if match:
                result = engine.plan_action(int(match.group(1)), payload)
                if result is None:
                    self._error(404, "plan_not_found", "计划不存在")
                else:
                    self._send(200, {"ok": True, "plan": result})
                return
            match = SETTING_ACTION_PATH.match(path)
            if match:
                self._send(200, engine.setting_action(match.group(1), payload))
                return
            match = SETTING_SUGGEST_PATH.match(path)
            if match:
                self._send(200, engine.setting_suggest(match.group(1), payload))
                return
            if path == "/discipline/loss-streak":
                self._send(200, engine.discipline_loss_streak(payload))
                return
            if path == "/discipline/mood":
                self._send(200, engine.discipline_mood(payload))
                return
            if path == "/reviews":
                self._send(200, engine.save_review(payload))
                return
            if path == "/cards":
                self._send(200, engine.create_card(payload))
                return
            match = CARD_ACTION_PATH.match(path)
            if match:
                result = engine.card_action(int(match.group(1)), payload)
                if result is None:
                    self._error(404, "card_not_found", "作战卡不存在")
                else:
                    self._send(200, result)
                return
            match = TRIGGER_JUDGEMENT_PATH.match(path)
            if match:
                self._send(200, engine.trigger_judgement(int(match.group(1)), payload))
                return
            self._error(404, "not_found", f"未知路径: {path}")
        except BadRequest as exc:
            self._error(exc.status, exc.code, exc.message)
        except SignalActionError as exc:
            self._error(exc.status, exc.code, exc.message)
        except PlanError as exc:
            self._error(exc.status, exc.code, exc.message)
        except ApiError as exc:
            self._error(exc.status, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - never echo request bodies
            logger.warning("POST failed: %s", type(exc).__name__)
            self._error(200, "internal_error", "服务内部错误")

    def _get_triggers(self, engine: Any, query: Mapping[str, list[str]]) -> None:
        extra = sorted(set(query) - {"since_id", "limit"})
        if extra:
            raise BadRequest("invalid_param", "不支持的参数: " + ", ".join(extra))
        since_id = self._int_param(query, "since_id", 0, minimum=0, maximum=2**31 - 1)
        limit = self._int_param(query, "limit", 50, minimum=1, maximum=200)
        self._send(200, engine.triggers_payload(since_id=since_id, limit=limit))

    def _get_guidance(self, engine: Any, query: Mapping[str, list[str]]) -> None:
        extra = sorted(set(query) - {"date"})
        if extra:
            raise BadRequest("invalid_param", "不支持的参数: " + ", ".join(extra))
        day = self._one(query, "date", "") or None
        if day is not None and not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", day):
            raise BadRequest("invalid_param", "date 必须是 YYYY-MM-DD")
        self._send(200, engine.guidance_payload(day))

    def _post_signal_action(self, engine: Any, signal_id: int, payload: Mapping[str, Any]) -> None:
        self._only(payload, {"action", "until"})
        action = payload.get("action")
        if not isinstance(action, str) or action not in {
            "ack",
            "ignore",
            "snooze",
            "unsnooze",
            "done",
            "reopen",
        }:
            raise BadRequest("invalid_action", "action 只接受 ack/ignore/snooze/unsnooze/done/reopen")
        until = payload.get("until")
        if action == "snooze":
            if not isinstance(until, str) or not until.strip():
                raise BadRequest("invalid_until", "snooze 需要 until")
            if until.strip() not in {"30m", "close", "next_open"}:
                from .models import parse_iso

                try:
                    parse_iso(until)
                except ValueError as exc:
                    raise BadRequest("invalid_until", "until 只接受 30m/close/next_open 或 ISO 时间") from exc
        elif "until" in payload:
            raise BadRequest("unexpected_field", "只有 snooze 接受 until")
        self._send(200, engine.action_signal(signal_id, action, until if isinstance(until, str) else None))

    # -- query helpers ---------------------------------------------------
    @staticmethod
    def _one(query: Mapping[str, list[str]], key: str, default: str) -> str:
        values = query.get(key)
        if not values:
            return default
        return values[-1]

    @classmethod
    def _int_param(
        cls,
        query: Mapping[str, list[str]],
        key: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        raw = cls._one(query, key, str(default))
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise BadRequest("invalid_param", f"{key} 必须是整数") from exc
        if value < minimum or value > maximum:
            raise BadRequest("invalid_param", f"{key} 必须在 {minimum}..{maximum}")
        return value

    def _method_not_allowed(self) -> None:
        self._reject_method()

    do_PUT = _method_not_allowed  # type: ignore[assignment]
    do_DELETE = _method_not_allowed  # type: ignore[assignment]
    do_PATCH = _method_not_allowed  # type: ignore[assignment]
    do_HEAD = _method_not_allowed  # type: ignore[assignment]
    do_OPTIONS = _method_not_allowed  # type: ignore[assignment]


def make_server(engine: Any, host: str, port: int) -> HubHTTPServer:
    # The API is loopback-only by contract; never bind a wildcard address.
    return HubHTTPServer(("127.0.0.1", int(port)), engine)


def start_server(engine: Any, host: str, port: int) -> tuple[HubHTTPServer, threading.Thread]:
    httpd = make_server(engine, host, port)
    thread = threading.Thread(target=httpd.serve_forever, name="chives-signals-http", daemon=True)
    thread.start()
    return httpd, thread


def stop_server(httpd: HubHTTPServer, thread: threading.Thread) -> None:
    httpd.shutdown()
    thread.join(timeout=5)
    httpd.server_close()
