"""Loopback-only HTTP daemon for the strategy service."""

from __future__ import annotations

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote

from .service import HubService, StrategyNotFound

logger = logging.getLogger(__name__)
MAX_LIMIT = 1000
ROUTE = re.compile(r"^/v1/([^/]+)/(pools|round|events|levels|annotate)$")
BACKTEST = re.compile(r"^/v1/([^/]+)/backtest$")
BACKTEST_ONE = re.compile(r"^/v1/([^/]+)/backtest/([^/]+)$")
BACKTESTS = re.compile(r"^/v1/([^/]+)/backtests$")
MAX_BODY = 64 * 1024


def _int_param(params: dict[str, list[str]], name: str, default: int, *, low: int = 0, high: int = MAX_LIMIT) -> int:
    raw = (params.get(name) or [str(default)])[-1]
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"参数 {name} 需要整数：{raw}") from exc
    if value < low or value > high:
        raise ValueError(f"参数 {name} 超出范围（{low}–{high}）：{value}")
    return value


class _Handler(BaseHTTPRequestHandler):
    server_version = "chives-strategy/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self) -> HubService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"ok": False, "message": message})

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        from urllib.parse import urlsplit

        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._send(200, self.service.health())
                return
            if parsed.path == "/alerts":
                since = _int_param(params, "since_id", 0, high=2**31 - 1)
                limit = _int_param(params, "limit", 100, low=1, high=500)
                self._send(200, self.service.alerts_payload(since, limit))
                return
            if parsed.path == "/v1/strategies":
                self._send(200, self.service.list_strategies())
                return
            match = BACKTEST_ONE.match(parsed.path)
            if match is not None:
                strategy_id, job_id = unquote(match.group(1)), unquote(match.group(2))
                self._send(200, self.service.backtest_result(strategy_id, job_id))
                return
            match = BACKTESTS.match(parsed.path)
            if match is not None:
                strategy_id = unquote(match.group(1))
                limit = _int_param(params, "limit", 20, low=1, high=200)
                self._send(200, self.service.backtest_history(strategy_id, limit))
                return
            match = ROUTE.match(parsed.path)
            if match is None:
                self._error(
                    404,
                    "接口不存在；可用 /v1/strategies、/v1/<id>/pools|round|events|levels|annotate、"
                    "/v1/<id>/backtest、/v1/<id>/backtests、/alerts、/health",
                )
                return
            strategy_id, action = unquote(match.group(1)), match.group(2)
            self._dispatch(strategy_id, action, params)
        except StrategyNotFound as exc:
            self._error(404, f"没有这个策略：{exc.strategy_id}")
        except KeyError as exc:
            self._error(404, f"没有这个回测任务：{exc}")
        except RuntimeError as exc:
            self._error(503, str(exc))
        except FileNotFoundError as exc:
            self._error(503, f"策略依赖的数据库不存在：{exc}")
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception:  # noqa: BLE001 - handler must always answer JSON
            logger.exception("unhandled chives-strategy error")
            self._error(503, "策略服务处理请求时出错，请稍后再试")

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        from urllib.parse import urlsplit

        parsed = urlsplit(self.path)
        match = BACKTEST.match(parsed.path)
        if match is None:
            self._error(404, "接口不存在；回测发起用 POST /v1/<id>/backtest")
            return
        try:
            body = self._read_json()
            strategy_id = unquote(match.group(1))
            payload = self.service.start_backtest(
                strategy_id,
                str(body.get("scheme") or "").strip(),
                _text(body.get("start")),
                _text(body.get("end")),
            )
            self._send(202, payload)
        except StrategyNotFound as exc:
            self._error(404, f"没有这个策略：{exc.strategy_id}")
        except ValueError as exc:
            self._error(400, str(exc))
        except RuntimeError as exc:
            self._error(503, str(exc))
        except Exception:  # noqa: BLE001 - handler must always answer JSON
            logger.exception("unhandled chives-strategy backtest error")
            self._error(503, "发起回测时出错，请稍后再试")

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise ValueError("Content-Length 不是整数") from exc
        if length < 0 or length > MAX_BODY:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("请求体需要是 JSON 对象") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求体需要是 JSON 对象")
        return payload

    def _dispatch(self, strategy_id: str, action: str, params: dict[str, list[str]]) -> None:
        if action == "pools":
            day = self.service.valid_date((params.get("date") or [""])[-1])
            try:
                payload = self.service.pools(strategy_id, day)
            except ValueError as exc:
                self._error(503, str(exc))
                return
            self._send(200, payload)
            return
        if action == "round":
            code = (params.get("code") or [""])[-1].strip().upper()
            if code == "":
                raise ValueError("参数 code 不能为空")
            day = self.service.valid_date((params.get("date") or [""])[-1])
            payload = self.service.round(strategy_id, code, day)
            if payload is None:
                self._error(404, f"没有找到 {code} 的轮次")
                return
            self._send(200, payload)
            return
        if action == "events":
            start = self.service.valid_date((params.get("start") or [""])[-1])
            end = self.service.valid_date((params.get("end") or [""])[-1])
            kinds_raw = (params.get("kinds") or [""])[-1]
            kinds = [part.strip() for part in kinds_raw.split(",") if part.strip()] or None
            limit = _int_param(params, "limit", 200, low=1, high=MAX_LIMIT)
            self._send(200, self.service.events(strategy_id, start, end, kinds, limit))
            return
        if action == "levels":
            code = (params.get("code") or [""])[-1].strip().upper()
            if code == "":
                raise ValueError("参数 code 不能为空")
            payload = self.service.levels(strategy_id, code)
            if payload is None:
                self._error(404, f"没有找到 {code} 当前轮次或价位")
                return
            self._send(200, payload)
            return
        if action == "annotate":
            code = (params.get("code") or [""])[-1].strip().upper()
            if code == "":
                raise ValueError("参数 code 不能为空")
            round_id = _int_param(params, "round_id", 0, low=1, high=2**31 - 1)
            try:
                payload = self.service.annotate(strategy_id, code, round_id)
            except ValueError as exc:
                self._error(404, str(exc))
                return
            self._send(200, payload)
            return
        self._error(404, "接口不存在")


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


class HubDaemon:
    def __init__(self, service: HubService, *, host: str = "127.0.0.1", port: int = 8869) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("chives-strategy 只监听回环地址")
        self.service = service
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.service = service  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def start(self) -> "HubDaemon":
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="chives-strategy", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def __enter__(self) -> "HubDaemon":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def serve(service: HubService, *, host: str = "127.0.0.1", port: int = 8869) -> int:
    daemon = HubDaemon(service, host=host, port=port)
    logger.info("chives-strategy listening on %s:%s", host, daemon.port)
    try:
        daemon.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.httpd.server_close()
    return 0
