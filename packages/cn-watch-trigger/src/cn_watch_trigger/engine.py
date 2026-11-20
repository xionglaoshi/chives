"""Minimal read-only HTTP client for the cn-watch engine."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PAGE_LIMIT = 500
HTTP_TIMEOUT_SECONDS = 10.0


class EngineError(Exception):
    """Raised when the engine cannot be reached or returns an unusable payload."""


class EngineClient:
    def __init__(self, base_url: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}?{urlencode(params)}"
        request = Request(url, headers={"accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            raise EngineError(f"engine 返回 HTTP {exc.code}: {url}") from exc
        except (URLError, OSError) as exc:
            raise EngineError(f"无法连接 engine {url}: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EngineError(f"engine 返回的不是合法 JSON: {url}") from exc

    def alerts_after(self, after_id: int, limit: int = PAGE_LIMIT) -> list[dict[str, Any]]:
        payload = self._get_json("/alerts", {"after_id": after_id, "limit": limit})
        if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
            raise EngineError("engine /alerts 响应缺少 alerts 列表")
        rows: list[dict[str, Any]] = []
        for item in payload["alerts"]:
            if not isinstance(item, dict):
                raise EngineError("engine /alerts 中存在非对象告警")
            alert_id = item.get("id")
            if isinstance(alert_id, bool) or not isinstance(alert_id, int) or alert_id < 0:
                raise EngineError(f"engine 告警 id 非法: {alert_id!r}")
            rows.append(item)
        rows.sort(key=lambda row: row["id"])
        return rows

    def latest_alert_id(self) -> int:
        """Return the current maximum alert id without analysing any history."""

        after_id = 0
        latest = 0
        while True:
            rows = self.alerts_after(after_id, PAGE_LIMIT)
            if not rows:
                return latest
            page_max = max(row["id"] for row in rows)
            if page_max <= after_id:
                return latest
            latest = max(latest, page_max)
            after_id = page_max
            if len(rows) < PAGE_LIMIT:
                return latest
