from __future__ import annotations

import json
import multiprocessing
import os
import queue
import stat
from pathlib import Path
from typing import Any

import pytest

from profile_mcp.store import ProfileStore

CONCURRENT_UPDATES: list[tuple[str, Any]] = [
    ("investor_type", "long_term"),
    ("experience_years", 7),
    ("risk_level", "balanced"),
    ("horizon", "years"),
    ("capital_range", "100k_1m"),
    ("markets", ["cn"]),
    ("sectors", ["半导体"]),
    ("research_depth", "thorough"),
]


def _worker(home: str, field: str, value: Any, results: Any) -> None:
    try:
        store = ProfileStore(profile_dir=Path(home), agents_path=Path(home) / "AGENTS.md")
        store.apply(lambda current: {**current, field: value})
        results.put("ok")
    except Exception as exc:  # pragma: no cover - reported through the queue
        results.put(f"{type(exc).__name__}: {exc}")


def test_snapshot_never_creates_the_profile_dir(home: Path) -> None:
    missing = home / "not-created"
    snap = ProfileStore(profile_dir=missing, agents_path=home / "AGENTS.md").snapshot()
    assert snap.profile == {}
    assert not missing.exists()


def test_empty_store(home: Path) -> None:
    snap = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md").snapshot()
    assert snap.profile == {}
    assert snap.updated_at is None
    assert snap.warnings == []


def test_update_writes_0600_json(home: Path) -> None:
    store = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md")
    store.apply(lambda current: {**current, "risk_level": "aggressive"})
    path = home / "finance-profile.json"
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["fields"]["risk_level"]["value"] == "aggressive"
    assert doc["fields"]["risk_level"]["updated_at"]
    assert doc["updated_at"]
    assert not list(home.glob(".profile-tmp-*"))


def test_existing_profile_file_is_forced_to_0600(home: Path) -> None:
    path = home / "finance-profile.json"
    path.write_text('{"fields": {}}', encoding="utf-8")
    path.chmod(0o644)
    store = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md")
    store.apply(lambda current: {**current, "language": "zh"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_default_resolution_read_creates_nothing(local_tmp: Path) -> None:
    store = ProfileStore(env={"HOME": str(local_tmp)})
    assert store.snapshot().profile == {}
    assert not (local_tmp / ".dsh").exists()


def test_update_keeps_other_fields(home: Path) -> None:
    store = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md")
    store.apply(lambda current: {**current, "risk_level": "balanced"})
    store.apply(lambda current: {**current, "language": "en"})
    snap = store.snapshot()
    assert snap.profile == {"risk_level": "balanced", "language": "en"}
    assert set(snap.timestamps) == {"risk_level", "language"}


def test_noop_does_not_rewrite_json(home: Path) -> None:
    store = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md")
    store.apply(lambda current: {**current, "language": "zh"})
    path = home / "finance-profile.json"
    first = path.stat().st_mtime_ns
    result = store.apply(lambda current: dict(current))
    assert result.changed == []
    assert path.stat().st_mtime_ns == first


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        "[]",
        '{"fields": []}',
        '{"fields": {"investor_type": {"value": "pro"}}}',
        '{"fields": {"nickname": {"value": "老王"}}}',
        '{"fields": {"language": "zh"}}',
    ],
)
def test_corrupt_json_is_treated_as_empty(home: Path, raw: str) -> None:
    (home / "finance-profile.json").write_text(raw, encoding="utf-8")
    store = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md")
    snap = store.snapshot()
    assert snap.profile == {}
    assert [warning["code"] for warning in snap.warnings] == ["profile_corrupt"]


def test_binary_file_is_treated_as_empty(home: Path) -> None:
    (home / "finance-profile.json").write_bytes(b"\xff\xfe\x00")
    snap = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md").snapshot()
    assert snap.profile == {}
    assert snap.warnings[0]["code"] == "profile_corrupt"


def test_hand_edited_valid_json_is_loadable(home: Path) -> None:
    (home / "finance-profile.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-11-01T00:00:00+00:00",
                "fields": {"language": {"value": "en", "updated_at": "2026-11-01"}},
            }
        ),
        encoding="utf-8",
    )
    snap = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md").snapshot()
    assert snap.profile == {"language": "en"}
    assert snap.updated_at == "2026-11-01T00:00:00+00:00"


def test_concurrent_updates_lose_no_field(home: Path) -> None:
    context = multiprocessing.get_context("fork")
    results: Any = context.Queue()
    processes = [
        context.Process(target=_worker, args=(str(home), field, value, results))
        for field, value in CONCURRENT_UPDATES
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
    for process in processes:
        assert process.exitcode == 0
    replies = []
    for _ in processes:
        try:
            replies.append(results.get(timeout=5))
        except queue.Empty:  # pragma: no cover
            replies.append("missing")
    assert replies == ["ok"] * len(processes)

    doc = json.loads((home / "finance-profile.json").read_text(encoding="utf-8"))
    assert set(doc["fields"]) == {field for field, _ in CONCURRENT_UPDATES}
    for field, value in CONCURRENT_UPDATES:
        assert doc["fields"][field]["value"] == value

    snap = ProfileStore(profile_dir=home, agents_path=home / "AGENTS.md").snapshot()
    assert snap.warnings == []
    assert set(snap.profile) == {field for field, _ in CONCURRENT_UPDATES}

    agents = (home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count("<!-- dsh-finance:profile:start -->") == 1
    assert agents.count("<!-- dsh-finance:profile:end -->") == 1
    assert not list(home.glob(".profile-tmp-*"))


def test_profile_dir_is_used_for_json(home: Path, local_tmp: Path) -> None:
    other = local_tmp / "elsewhere"
    store = ProfileStore(profile_dir=other, agents_path=home / "AGENTS.md")
    store.apply(lambda current: {**current, "language": "en"})
    assert (other / "finance-profile.json").exists()
    assert not (home / "finance-profile.json").exists()


def test_store_resolves_from_env(monkeypatch: pytest.MonkeyPatch, local_tmp: Path) -> None:
    profile_dir = local_tmp / "profile-dir"
    agents_home = local_tmp / "agents-home"
    monkeypatch.setenv("DSH_FINANCE_PROFILE_DIR", str(profile_dir))
    monkeypatch.setenv("DSH_HOME", str(agents_home))
    store = ProfileStore()
    assert store.profile_path == profile_dir / "finance-profile.json"
    assert store.agents_path == agents_home / "AGENTS.md"


def test_agents_path_stays_outside_profile_dir(home: Path) -> None:
    store = ProfileStore(profile_dir=home / "profile", agents_path=home / "AGENTS.md")
    store.apply(lambda current: {**current, "language": "zh"})
    assert (home / "AGENTS.md").exists()
    assert os.path.exists(home / "profile" / "finance-profile.json")
