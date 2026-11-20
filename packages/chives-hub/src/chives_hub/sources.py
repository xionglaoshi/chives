"""Upstream access: cn-watch (8865), market-watch (8866), Tencent quotes, analyses.

Only loopback upstreams and the fixed Tencent host are allowed.  Redirects are
refused, bodies are capped and timeouts are short.  The package never reads a
credential and never uses a proxy.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .config import (
    LOOPBACK_HOSTS,
    TENCENT_ENV,
    TENCENT_HOST,
    TEST_MODE_ENV,
    HubConfig,
)
from .models import CN_TZ, Analysis

logger = logging.getLogger("chives_hub.sources")

USER_AGENT = "chives-hub/0.1 (local deterministic research tool)"
MAX_BYTES = 2 * 1024 * 1024
MAX_ANALYSIS_BYTES = 200_000
ANALYSIS_FILE_RE = re.compile(r"^analysis-[0-9]+\.md$")
STALE_SECONDS = 30.0
PLAN_ACTOR = "chives-hub"


class SourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UpstreamRejection(SourceError):
    """The upstream answered ``{ok:false, code}`` instead of accepting the write."""

    def __init__(
        self, code: str, message: str, *, field: Optional[str] = None
    ) -> None:
        super().__init__(code, message)
        self.field = field


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _validate_loopback_url(url: str, *, test_mode: bool) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise SourceError("host_not_allowed", "上游地址必须是 http(s)")
    if parsed.hostname not in LOOPBACK_HOSTS:
        raise SourceError("host_not_allowed", f"不允许访问的主机: {parsed.hostname}")
    if parsed.username or parsed.password:
        raise SourceError("host_not_allowed", "上游地址不能带用户名或密码")
    if not test_mode and parsed.port not in {8865, 8866}:
        raise SourceError("host_not_allowed", "生产环境只允许 8865/8866 端口")


def validate_public_url(
    url: str, *, hosts: Sequence[str], test_mode: bool = False
) -> None:
    """Only the fixed public quote hosts over https, or loopback in test mode."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        raise SourceError("host_not_allowed", "上游地址不能带用户名或密码")
    if test_mode:
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS:
            raise SourceError("host_not_allowed", "测试模式上游必须指向回环地址")
        return
    if parsed.scheme != "https":
        raise SourceError("host_not_allowed", "公开行情只允许 https")
    if parsed.hostname not in set(hosts):
        raise SourceError("host_not_allowed", f"不允许访问的主机: {parsed.hostname}")


class HttpClient:
    """Minimal no-redirect HTTP client with per-source health bookkeeping."""

    def __init__(
        self,
        *,
        timeout: float = 3.0,
        max_bytes: int = MAX_BYTES,
        env: Optional[Mapping[str, str]] = None,
        opener: Optional[urllib.request.OpenerDirector] = None,
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._env = os.environ if env is None else env
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {}

    def _state_for(self, name: str) -> dict[str, Any]:
        return self._state.setdefault(
            name,
            {"last_success": None, "last_error": None, "failures": 0, "last_attempt": None},
        )

    def _record_success(self, name: str, moment: datetime) -> None:
        with self._lock:
            state = self._state_for(name)
            state["last_success"] = moment
            state["last_error"] = None
            state["failures"] = 0
            state["last_attempt"] = moment

    def _record_failure(self, name: str, moment: datetime, exc: BaseException) -> None:
        with self._lock:
            state = self._state_for(name)
            state["failures"] = int(state.get("failures") or 0) + 1
            state["last_error"] = f"{getattr(exc, 'code', type(exc).__name__)}: {exc}"[:300]
            state["last_attempt"] = moment

    def get_json(
        self,
        name: str,
        base: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        now: Optional[datetime] = None,
        test_mode: bool = False,
    ) -> Any:
        moment = now or datetime.now(CN_TZ)
        url = self._url(base, path, params)
        _validate_loopback_url(url, test_mode=test_mode)
        try:
            text = self._fetch(url, "utf-8")
            payload = json.loads(text)
        except (SourceError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._record_failure(name, moment, exc)
            if isinstance(exc, SourceError):
                raise
            raise SourceError("invalid_json", f"{name} 返回不是合法 JSON") from exc
        self._record_success(name, moment)
        return payload

    def post_json(
        self,
        name: str,
        base: str,
        path: str,
        payload: Any,
        *,
        now: Optional[datetime] = None,
        test_mode: bool = False,
        actor: Optional[str] = None,
    ) -> Any:
        """One loopback POST with an optional ``X-Actor`` audit header.

        A business rejection (HTTP 400 + ``{ok:false, code, message}``) raises
        :class:`UpstreamRejection`; the upstream is reachable, so its health stays
        green.  Network failures raise the usual :class:`SourceError`.
        """
        moment = now or datetime.now(CN_TZ)
        url = self._url(base, path, None)
        _validate_loopback_url(url, test_mode=test_mode)
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SourceError("invalid_json", "请求体无法序列化") from exc
        if len(body) > self.max_bytes:
            raise SourceError("request_too_large", "请求体过大")
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        }
        if actor:
            headers["X-Actor"] = actor
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                if 300 <= status < 400:
                    raise SourceError("redirect_refused", "拒绝跟随重定向")
                if status not in (200, 201, 202, 203, 204):
                    raise SourceError("upstream_http", f"上游 HTTP {status}")
                raw = response.read(self.max_bytes + 1)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise SourceError(
                    "redirect_refused", f"拒绝跟随重定向 HTTP {exc.code}"
                ) from exc
            try:
                raw = exc.read(self.max_bytes + 1)
            except OSError:
                raw = b""
            rejection = self._rejection(raw)
            if rejection is not None:
                self._record_success(name, moment)
                raise rejection
            self._record_failure(
                name, moment, SourceError("upstream_http", f"上游 HTTP {exc.code}")
            )
            raise SourceError("upstream_http", f"上游 HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            failure = SourceError("upstream_network", f"请求失败: {exc.reason}")
            self._record_failure(name, moment, failure)
            raise failure from exc
        except (TimeoutError, OSError) as exc:
            failure = SourceError("upstream_network", f"请求失败: {exc}")
            self._record_failure(name, moment, failure)
            raise failure from exc
        if len(raw) > self.max_bytes:
            raise SourceError("response_too_large", "上游响应过大")
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            self._record_failure(name, moment, SourceError("invalid_json", "上游返回不是合法 JSON"))
            raise SourceError("invalid_json", f"{name} 返回不是合法 JSON") from exc
        rejection = self._rejection(raw)
        if rejection is not None:
            self._record_success(name, moment)
            raise rejection
        self._record_success(name, moment)
        return parsed

    @staticmethod
    def _rejection(raw: bytes) -> Optional[UpstreamRejection]:
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(parsed, dict) or parsed.get("ok") is not False:
            return None
        code = str(parsed.get("code") or "upstream_rejected")
        message = str(parsed.get("message") or parsed.get("error") or "上游拒绝该请求")
        field = parsed.get("field")
        return UpstreamRejection(code, message, field=str(field) if field else None)

    def get_text(
        self,
        name: str,
        url: str,
        *,
        encoding: str = "utf-8",
        now: Optional[datetime] = None,
        test_mode: bool = False,
        allowed_hosts: Sequence[str] = (TENCENT_HOST,),
        timeout: Optional[float] = None,
    ) -> str:
        moment = now or datetime.now(CN_TZ)
        validate_public_url(url, hosts=allowed_hosts, test_mode=test_mode)
        try:
            text = self._fetch(url, encoding, timeout=timeout)
        except SourceError as exc:
            self._record_failure(name, moment, exc)
            raise
        self._record_success(name, moment)
        return text

    def get_json_public(
        self,
        name: str,
        url: str,
        *,
        now: Optional[datetime] = None,
        test_mode: bool = False,
        allowed_hosts: Sequence[str] = (TENCENT_HOST,),
        timeout: Optional[float] = None,
    ) -> Any:
        """One GET against a fixed public quote host, parsed as JSON."""
        moment = now or datetime.now(CN_TZ)
        validate_public_url(url, hosts=allowed_hosts, test_mode=test_mode)
        try:
            text = self._fetch(url, "utf-8", timeout=timeout)
            payload = json.loads(text)
        except (SourceError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._record_failure(name, moment, exc)
            if isinstance(exc, SourceError):
                raise
            raise SourceError("invalid_json", f"{name} 返回不是合法 JSON") from exc
        self._record_success(name, moment)
        return payload

    def _url(self, base: str, path: str, params: Optional[Mapping[str, Any]]) -> str:
        if not path.startswith("/"):
            path = "/" + path
        url = base.rstrip("/") + path
        if params:
            query = urllib.parse.urlencode(
                {key: value for key, value in params.items() if value is not None}
            )
            url = f"{url}?{query}"
        return url

    def _fetch(self, url: str, encoding: str, *, timeout: Optional[float] = None) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "identity",
            },
            method="GET",
        )
        effective_timeout = self.timeout if timeout is None else max(0.05, float(timeout))
        try:
            with self._opener.open(request, timeout=effective_timeout) as response:
                status = getattr(response, "status", 200)
                if status not in (200, 201, 202, 203, 204):
                    raise SourceError("upstream_http", f"上游 HTTP {status}")
                body = response.read(self.max_bytes + 1)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise SourceError("redirect_refused", f"拒绝跟随重定向 HTTP {exc.code}") from exc
            raise SourceError("upstream_http", f"上游 HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise SourceError("upstream_network", f"请求失败: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise SourceError("upstream_network", f"请求失败: {exc}") from exc
        if len(body) > self.max_bytes:
            raise SourceError("response_too_large", "上游响应过大")
        return body.decode(encoding, errors="replace")

    def health(self, now: datetime) -> dict[str, dict[str, Any]]:
        with self._lock:
            result: dict[str, dict[str, Any]] = {}
            for name, state in self._state.items():
                last = state.get("last_success")
                age = None if last is None else max(0.0, (now - last).total_seconds())
                result[name] = {
                    "ok": state.get("last_error") is None and age is not None and age <= STALE_SECONDS,
                    "age_s": None if age is None else round(age, 1),
                }
                if state.get("last_error"):
                    result[name]["last_error"] = state["last_error"]
            return result


@dataclass
class _AnalysisRecord:
    alert_id: int
    status: str
    reason: Optional[str]
    file: Optional[str]


class Sources:
    def __init__(
        self,
        config: HubConfig,
        *,
        client: Optional[Any] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.config = config
        self.env = os.environ if env is None else env
        self.test_mode = self.env.get(TEST_MODE_ENV) == "1"
        self.http = client or HttpClient(timeout=config.timeout_seconds, env=self.env)
        self.cn_watch_base = config.cn_watch_base
        self.market_watch_base = config.market_watch_base
        self.tencent_base = config.tencent_base
        self._analyses_lock = threading.Lock()
        self._analyses_state: dict[str, Any] = {
            "last_success": None,
            "last_error": None,
        }

    # -- cn-watch --------------------------------------------------------
    def cn_state(self, *, now: Optional[datetime] = None) -> dict[str, Any]:
        payload = self.http.get_json(
            "cn_watch", self.cn_watch_base, "/state", None, now=now, test_mode=self.test_mode
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "cn-watch /state 不是对象")
        return payload

    # -- cn-watch plan rules (cards are delegated to the single evaluator) --
    def plans(self, *, now: Optional[datetime] = None) -> Any:
        return self.http.get_json(
            "cn_watch", self.cn_watch_base, "/plans", None, now=now, test_mode=self.test_mode
        )

    def upsert_plan(
        self, plan: Mapping[str, Any], *, now: Optional[datetime] = None
    ) -> Any:
        return self.http.post_json(
            "cn_watch",
            self.cn_watch_base,
            "/plans/upsert",
            dict(plan),
            now=now,
            test_mode=self.test_mode,
            actor=PLAN_ACTOR,
        )

    def remove_plan(self, plan_id: str, *, now: Optional[datetime] = None) -> Any:
        return self.http.post_json(
            "cn_watch",
            self.cn_watch_base,
            "/plans/remove",
            {"id": plan_id},
            now=now,
            test_mode=self.test_mode,
            actor=PLAN_ACTOR,
        )

    def cn_alerts(self, after_id: int, limit: int = 200, *, now: Optional[datetime] = None) -> list[dict[str, Any]]:
        payload = self.http.get_json(
            "cn_watch",
            self.cn_watch_base,
            "/alerts",
            {"after_id": int(after_id), "limit": int(limit)},
            now=now,
            test_mode=self.test_mode,
        )
        alerts = payload.get("alerts") if isinstance(payload, dict) else None
        if not isinstance(alerts, list):
            raise SourceError("invalid_payload", "cn-watch /alerts 缺少 alerts")
        return [item for item in alerts if isinstance(item, dict)]

    # -- market-watch ----------------------------------------------------
    def market_alerts(self, since_id: int, limit: int = 100, *, now: Optional[datetime] = None) -> list[dict[str, Any]]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/alerts",
            {"since_id": int(since_id), "limit": int(limit)},
            now=now,
            test_mode=self.test_mode,
        )
        alerts = payload.get("alerts") if isinstance(payload, dict) else None
        if not isinstance(alerts, list):
            raise SourceError("invalid_payload", "market-watch /alerts 缺少 alerts")
        return [item for item in alerts if isinstance(item, dict)]

    def market_overview(self, *, now: Optional[datetime] = None) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch", self.market_watch_base, "/overview", None, now=now, test_mode=self.test_mode
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /overview 不是对象")
        return payload

    def market_sectors(
        self, level: str = "sw1", *, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/sectors",
            {"level": level},
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /sectors 不是对象")
        return payload

    def market_pool(
        self,
        kind: str,
        *,
        day: Optional[str] = None,
        limit: int = 200,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/pool",
            {"kind": kind, "date": day, "limit": int(limit)},
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /pool 不是对象")
        return payload

    def market_pool_ladder(
        self, *, day: Optional[str] = None, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/pool/ladder",
            {"date": day},
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /pool/ladder 不是对象")
        return payload

    def market_pool_history(
        self, days: int = 10, *, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/pool/history",
            {"days": int(days)},
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /pool/history 不是对象")
        return payload

    def market_pool_by_industry(
        self, *, day: Optional[str] = None, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/pool/by-industry",
            {"date": day},
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /pool/by-industry 不是对象")
        return payload

    def market_pool_yesterday(
        self, *, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/pool/yesterday",
            None,
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /pool/yesterday 不是对象")
        return payload

    def market_themes(
        self, *, limit: int = 10, sort: str = "change", now: Optional[datetime] = None
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/themes",
            {"kind": "concept", "limit": int(limit), "sort": sort},
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /themes 不是对象")
        return payload

    def market_flows(
        self, kind: str = "sector_in", *, limit: int = 5, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        payload = self.http.get_json(
            "market_watch",
            self.market_watch_base,
            "/flows",
            {"kind": kind, "limit": int(limit)},
            now=now,
            test_mode=self.test_mode,
        )
        if not isinstance(payload, dict):
            raise SourceError("invalid_payload", "market-watch /flows 不是对象")
        return payload

    # -- Tencent quotes --------------------------------------------------
    def tencent_quotes(
        self, codes: Sequence[str], *, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        unique: list[str] = []
        seen: set[str] = set()
        for code in codes:
            if code not in seen:
                seen.add(code)
                unique.append(code)
        if len(unique) > self.config.max_tencent_codes:
            raise SourceError("too_many_codes", "腾讯快照一次最多 80 只")
        if not unique:
            return {}
        from .portfolio_view import ensure_portfolio_path

        ensure_portfolio_path()
        from portfolio_mcp.quotes import build_url, parse_quote_text
        from portfolio_mcp.symbols import normalize_symbol

        symbols = [normalize_symbol(code).tencent for code in unique]
        base = self.tencent_base
        url = build_url(base, symbols)
        if not self.test_mode:
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname != "qt.gtimg.cn":
                raise SourceError("host_not_allowed", "腾讯行情只允许 https://qt.gtimg.cn")
        text = self.http.get_text(
            "tencent", url, encoding="gbk", now=now, test_mode=self.test_mode
        )
        return parse_quote_text(text)

    # -- analyses --------------------------------------------------------
    def analyses(self) -> dict[int, Analysis]:
        directory = self.config.analyses_dir
        index_path = directory / "analyses.jsonl"
        records: dict[int, _AnalysisRecord] = {}
        if not index_path.is_file():
            return {}
        try:
            with index_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, dict):
                        continue
                    try:
                        alert_id = int(raw.get("alert_id"))
                    except (TypeError, ValueError):
                        continue
                    records[alert_id] = _AnalysisRecord(
                        alert_id=alert_id,
                        status=str(raw.get("status") or ""),
                        reason=(str(raw.get("reason")) if raw.get("reason") else None),
                        file=(str(raw.get("file")) if raw.get("file") else None),
                    )
        except OSError as exc:
            with self._analyses_lock:
                self._analyses_state["last_error"] = type(exc).__name__
            return {}
        result: dict[int, Analysis] = {}
        for alert_id, record in records.items():
            markdown = ""
            if record.status == "done":
                markdown = self._read_analysis_file(record.file, alert_id)
            result[alert_id] = Analysis(
                alert_id=alert_id,
                status=record.status,
                reason=record.reason,
                file=record.file,
                markdown=markdown,
            )
        with self._analyses_lock:
            self._analyses_state["last_success"] = datetime.now(CN_TZ)
            self._analyses_state["last_error"] = None
        return result

    def _read_analysis_file(self, raw_path: Optional[str], alert_id: int) -> str:
        name = Path(raw_path).name if raw_path else f"analysis-{alert_id}.md"
        if not ANALYSIS_FILE_RE.match(name):
            return ""
        path = self.config.analyses_dir / name
        try:
            if path.resolve().parent != self.config.analyses_dir.resolve():
                return ""
            if not path.is_file():
                return ""
            with path.open("rb") as handle:
                return handle.read(MAX_ANALYSIS_BYTES).decode("utf-8", errors="replace")
        except OSError:
            return ""

    # -- health ----------------------------------------------------------
    def health(self, now: datetime) -> dict[str, Any]:
        per_source = self.http.health(now) if hasattr(self.http, "health") else {}
        sources: dict[str, Any] = {}
        for name in ("cn_watch", "market_watch"):
            entry = per_source.get(name, {"ok": False, "age_s": None})
            sources[name] = {
                "ok": bool(entry.get("ok")),
                "age_s": entry.get("age_s"),
            }
            if entry.get("last_error"):
                sources[name]["last_error"] = entry["last_error"]
        analyses_dir = self.config.analyses_dir
        analyses_ok = analyses_dir.is_dir() and (analyses_dir / "analyses.jsonl").is_file()
        with self._analyses_lock:
            last = self._analyses_state.get("last_success")
        sources["analyses"] = {
            "ok": bool(analyses_ok),
            "age_s": None if last is None else round(max(0.0, (now - last).total_seconds()), 1),
        }
        return sources
