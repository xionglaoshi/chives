"""Minimal read/write HTTP client for the chives hub trigger API."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import validate_hub_url

PAGE_LIMIT = 50
HTTP_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 512 * 1024
MAX_PAGES = 1000


class HubError(Exception):
    """Raised when the hub cannot be reached or returns an unusable payload."""


class HubClient:
    def __init__(self, base_url: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> None:
        self.base_url = validate_hub_url(base_url)
        self.timeout = timeout

    def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        data = None
        headers = {"accept": "application/json"}
        if body is not None:
            data = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
            headers["content-type"] = "application/json; charset=utf-8"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise HubError(f"hub 返回 HTTP {exc.code}: {url}") from exc
        except (URLError, OSError) as exc:
            raise HubError(f"无法连接 hub {url}: {exc}") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise HubError(f"hub 响应超过 {MAX_RESPONSE_BYTES} 字节: {url}")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HubError(f"hub 返回的不是合法 JSON: {url}") from exc

    def _page(self, since_id: int, limit: int = PAGE_LIMIT) -> list[dict[str, Any]]:
        payload = self._request_json("/triggers", params={"since_id": since_id, "limit": limit})
        if not isinstance(payload, dict) or not isinstance(payload.get("triggers"), list):
            raise HubError("hub /triggers 响应缺少 triggers 列表")
        rows: list[dict[str, Any]] = []
        for item in payload["triggers"]:
            if not isinstance(item, dict):
                raise HubError("hub /triggers 中存在非对象触发")
            trigger_id = item.get("id")
            if isinstance(trigger_id, bool) or not isinstance(trigger_id, int) or trigger_id < 0:
                raise HubError(f"hub 触发 id 非法: {trigger_id!r}")
            if not isinstance(item.get("kind"), str) or not item["kind"].strip():
                raise HubError(f"hub 触发 kind 非法: {item.get('kind')!r}")
            rows.append(item)
        rows.sort(key=lambda row: row["id"])
        return rows

    def triggers_since(self, since_id: int, limit: int = PAGE_LIMIT) -> list[dict[str, Any]]:
        rows = self._page(since_id, limit)
        return [row for row in rows if row["id"] > since_id]

    def latest_trigger_id(self) -> int:
        """Return the current maximum trigger id without processing history."""

        after_id = 0
        latest = 0
        for _ in range(MAX_PAGES):
            rows = self._page(after_id, PAGE_LIMIT)
            if not rows:
                return latest
            page_max = max(row["id"] for row in rows)
            if page_max <= after_id:
                return latest
            latest = max(latest, page_max)
            after_id = page_max
            if len(rows) < PAGE_LIMIT:
                return latest
        raise HubError("hub /triggers 分页超过上限，拒绝继续")

    def context(self, trigger_id: int) -> dict[str, Any]:
        payload = self._request_json(f"/triggers/{int(trigger_id)}/context")
        if not isinstance(payload, dict):
            raise HubError("hub 上下文包响应必须是对象")
        if payload.get("ok") is False:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise HubError(f"hub 上下文包不可用: {code or 'unknown'}")
        context = payload.get("context")
        if not isinstance(context, dict):
            raise HubError("hub 上下文包响应缺少 context 对象")
        return context

    def judge(
        self,
        trigger_id: int,
        *,
        action: str,
        reason: str,
        next_check: str,
        risk: str,
    ) -> dict[str, Any]:
        payload = self._request_json(
            f"/triggers/{int(trigger_id)}/judgement",
            method="POST",
            body={
                "action": action,
                "reason": reason,
                "next_check": next_check,
                "risk": risk,
            },
        )
        if not isinstance(payload, dict):
            raise HubError("hub 判断回写响应必须是对象")
        return payload
