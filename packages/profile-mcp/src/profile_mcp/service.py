"""Tool implementations: profile_get, profile_update, profile_clear."""

from __future__ import annotations

from typing import Any

from profile_mcp.envelope import envelope
from profile_mcp.fields import (
    ProfileError,
    validate_field_names,
    validate_fields,
)
from profile_mcp.store import ProfileStore

EMPTY_HINT = (
    "还没有保存用户画像。只有在用户本人于对话中说明偏好或明确要求记住时才调用 profile_update；"
    "不要根据对话内容自行推断并写入。"
)


def _error(exc: ProfileError) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if exc.field is not None:
        data["field"] = exc.field
    return envelope(
        status="error",
        data=data,
        error_code=exc.code,
        error_message=exc.message,
    )


class ProfileService:
    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    def get(self, args: Any = None) -> dict[str, Any]:
        snap = self._store.snapshot()
        data: dict[str, Any] = {
            "profile": snap.profile,
            "fields": dict(snap.profile),
            "timestamps": snap.timestamps,
            "field_records": {
                name: {"value": value, "updated_at": snap.timestamps.get(name)}
                for name, value in snap.profile.items()
            },
            "updated_at": snap.updated_at,
            "empty": not snap.profile,
        }
        if not snap.profile:
            data["hint"] = EMPTY_HINT
        return envelope(
            status="empty" if not snap.profile else "ready",
            data=data,
            warnings=snap.warnings,
        )

    def update(self, args: Any) -> dict[str, Any]:
        try:
            fields = self._extract_fields(args)
            cleaned = validate_fields(fields)
        except ProfileError as exc:
            return _error(exc)

        def change(current: dict[str, Any]) -> dict[str, Any]:
            merged = dict(current)
            merged.update(cleaned)
            return merged

        mutation = self._store.apply(change)
        data = {
            "before": mutation.before,
            "after": mutation.after,
            "changed": mutation.changed,
            "timestamps": mutation.timestamps,
            "updated_at": mutation.updated_at,
            "empty": not mutation.after,
            "agents_md": mutation.agents_md,
        }
        return envelope(status="ready", data=data, warnings=mutation.warnings)

    def clear(self, args: Any) -> dict[str, Any]:
        try:
            names = self._extract_clear_fields(args)
        except ProfileError as exc:
            return _error(exc)

        targets = set(names) if names is not None else None

        def change(current: dict[str, Any]) -> dict[str, Any]:
            if targets is None:
                return {}
            return {name: value for name, value in current.items() if name not in targets}

        mutation = self._store.apply(change)
        data = {
            "before": mutation.before,
            "after": mutation.after,
            "changed": mutation.changed,
            "cleared": mutation.changed,
            "timestamps": mutation.timestamps,
            "updated_at": mutation.updated_at,
            "empty": not mutation.after,
            "agents_md": mutation.agents_md,
        }
        return envelope(status="ready", data=data, warnings=mutation.warnings)

    @staticmethod
    def _extract_fields(args: Any) -> Any:
        if args is None:
            return {}
        if not isinstance(args, dict):
            raise ProfileError("invalid_argument", "arguments must be a JSON object")
        if "fields" not in args:
            return args
        extra = sorted(key for key in args if key != "fields")
        if extra:
            raise ProfileError("invalid_argument", "unexpected argument(s): " + ", ".join(extra))
        return args["fields"]

    @staticmethod
    def _extract_clear_fields(args: Any) -> list[str] | None:
        if args is None:
            return None
        if not isinstance(args, dict):
            raise ProfileError("invalid_argument", "arguments must be a JSON object")
        extra = sorted(key for key in args if key != "fields")
        if extra:
            raise ProfileError("invalid_argument", "unexpected argument(s): " + ", ".join(extra))
        if "fields" not in args or args["fields"] is None:
            return None
        return validate_field_names(args["fields"])
