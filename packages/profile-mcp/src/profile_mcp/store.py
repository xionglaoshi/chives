"""JSON persistence for the profile, with locking and atomic writes."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from profile_mcp.atomic import atomic_write_text
from profile_mcp.fields import (
    FIELD_ORDER,
    PROFILE_VERSION,
    ProfileError,
    validate_fields,
)
from profile_mcp.paths import (
    PROFILE_FILENAME,
    resolve_agents_path,
    resolve_profile_dir,
)
from profile_mcp.render import sync_agents_md

LOCK_FILENAME = ".finance-profile.lock"


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Snapshot:
    profile: dict[str, Any] = field(default_factory=dict)
    timestamps: dict[str, str] = field(default_factory=dict)
    updated_at: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Mutation:
    before: dict[str, Any]
    after: dict[str, Any]
    changed: list[str]
    timestamps: dict[str, str]
    updated_at: str | None
    warnings: list[dict[str, Any]]
    agents_md: dict[str, Any]


def _corrupt(message: str) -> dict[str, Any]:
    return {"code": "profile_corrupt", "message": message}


class ProfileStore:
    """One profile file; every mutation is read-modify-write under an exclusive lock."""

    def __init__(
        self,
        *,
        profile_dir: Path | None = None,
        agents_path: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir) if profile_dir is not None else resolve_profile_dir(env)
        self.profile_path = self.profile_dir / PROFILE_FILENAME
        self.agents_path = Path(agents_path) if agents_path is not None else resolve_agents_path(env)
        self._thread_lock = threading.Lock()

    @contextmanager
    def _locked(self, *, create: bool) -> Iterator[None]:
        with self._thread_lock:
            if create:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
            lock_path = self.profile_dir / LOCK_FILENAME
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _load(self) -> Snapshot:
        try:
            raw = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Snapshot()
        except (OSError, UnicodeDecodeError, ValueError):
            return Snapshot(warnings=[_corrupt("finance-profile.json is unreadable or not valid JSON; treated as empty")])
        if not isinstance(raw, dict) or not isinstance(raw.get("fields", {}), dict):
            return Snapshot(warnings=[_corrupt("finance-profile.json has an unexpected shape; treated as empty")])

        profile: dict[str, Any] = {}
        timestamps: dict[str, str] = {}
        for name, record in (raw.get("fields") or {}).items():
            if name not in FIELD_ORDER or not isinstance(record, dict):
                return Snapshot(warnings=[_corrupt(f"finance-profile.json has an invalid field record for {name!r}; treated as empty")])
            if "value" not in record:
                return Snapshot(warnings=[_corrupt(f"finance-profile.json is missing a value for {name!r}; treated as empty")])
            try:
                value = validate_fields({name: record["value"]})[name]
            except ProfileError:
                return Snapshot(warnings=[_corrupt(f"finance-profile.json has an invalid value for {name!r}; treated as empty")])
            profile[name] = value
            stamp = record.get("updated_at")
            if isinstance(stamp, str) and stamp:
                timestamps[name] = stamp
        updated_at = raw.get("updated_at")
        if not isinstance(updated_at, str):
            updated_at = None
        return Snapshot(profile=profile, timestamps=timestamps, updated_at=updated_at)

    def snapshot(self) -> Snapshot:
        """Read-only: no directory, lock file or profile file is created by a read.

        Writers replace the whole file with os.replace(), so a reader sees either the
        old or the new complete document, never a partial one; no lock is needed here.
        """
        if not self.profile_dir.is_dir():
            return Snapshot()
        return self._load()

    def _document(self, profile: dict[str, Any], timestamps: dict[str, str], updated_at: str | None) -> str:
        fields: dict[str, Any] = {}
        for name in FIELD_ORDER:
            if name in profile:
                fields[name] = {"value": profile[name], "updated_at": timestamps.get(name, "")}
        doc = {"version": PROFILE_VERSION, "updated_at": updated_at, "fields": fields}
        return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n"

    def apply(self, change: Callable[[dict[str, Any]], dict[str, Any]]) -> Mutation:
        """Run change() on the current profile and persist the result atomically."""
        with self._locked(create=True):
            snap = self._load()
            warnings = list(snap.warnings)
            before = copy.deepcopy(snap.profile)
            after = change(copy.deepcopy(snap.profile))
            after = {name: after[name] for name in FIELD_ORDER if name in after}

            changed = [name for name in FIELD_ORDER if before.get(name, _MISSING) != after.get(name, _MISSING)]
            timestamps = dict(snap.timestamps)
            if changed:
                now = _today()
                for name in changed:
                    if name in after:
                        timestamps[name] = now
                    else:
                        timestamps.pop(name, None)
                updated_at = _now()
            else:
                updated_at = snap.updated_at
            timestamps = {name: timestamps[name] for name in FIELD_ORDER if name in after and name in timestamps}

            if changed:
                atomic_write_text(self.profile_path, self._document(after, timestamps, updated_at), preserve_mode=False)
            agents_md, render_warnings = sync_agents_md(self.agents_path, after)
            warnings.extend(render_warnings)
            return Mutation(
                before=before,
                after=after,
                changed=changed,
                timestamps=timestamps,
                updated_at=updated_at,
                warnings=warnings,
                agents_md=agents_md,
            )


_MISSING = object()
