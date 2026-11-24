"""Plan, stage, activate or roll back an offline Chives data migration."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import tempfile
from contextlib import closing

USER_ENTRIES = {
    "audit", "bots", "chives.sqlite", "dsh", "equity-research", "harness", "library", "paper",
    "profile", "secrets", "user", "user-archive-state",
}
MECHANICAL_ENTRIES = {"market", "marketdata"}
SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
SKIP_NAMES = {".DS_Store", "update.lock"}


def destination(relative):
    top, *rest = relative.parts
    if top == "bots" and len(rest) >= 2 and rest[1] == "workspace":
        return Path("workspace", "bots", rest[0], *rest[2:])
    if top in USER_ENTRIES:
        return Path("user-data") / relative
    if top in MECHANICAL_ENTRIES:
        return Path("public-data/mechanical-cache") / relative
    if top == "hotspots":
        return Path("public-data/chives-build") / relative
    return Path("review") / relative


def plan(root):
    legacy = root / "data"
    if legacy.is_symlink() or not legacy.is_dir():
        raise ValueError("Expected a real legacy data/ directory")
    for source in sorted(legacy.rglob("*")):
        relative = source.relative_to(legacy)
        sqlite_base = source.with_name(source.name.rsplit("-", 1)[0])
        sqlite_sidecar = (source.name.endswith(("-wal", "-shm", "-journal"))
                          and sqlite_base.suffix in SQLITE_SUFFIXES and sqlite_base.is_file())
        if source.name in SKIP_NAMES or relative == Path("hotspots/status.json") or sqlite_sidecar:
            continue
        target = destination(relative)
        if source.is_symlink():
            resolved = source.resolve(strict=True)
            if relative.parts[:1] != ("bots",) or relative.parts[2:3] != ("skills",) or not resolved.is_relative_to(root / "skills"):
                raise ValueError(f"Review symbolic link before staging: {source.relative_to(root)}")
            yield source, target, "skill-link"
        elif source.is_dir():
            yield source, target, "directory"
        elif source.is_file():
            method = "sqlite-backup" if source.suffix in SQLITE_SUFFIXES else "copy"
            yield source, target, method
        else:
            raise ValueError(f"Unsupported legacy entry: {source.relative_to(root)}")


def digest(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
        return result.hexdigest()


def stage_entry(root, stage, source, relative, method):
    target = stage / relative
    if method == "directory":
        target.mkdir(parents=True, exist_ok=True)
        if relative.parts[0] in {"user-data", "workspace", "review"}:
            target.chmod(0o700)
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if method == "skill-link":
        # Preserve the source directory inside the same install when activated.
        target.symlink_to(source.resolve(strict=True), target_is_directory=source.is_dir())
        return None
    if method == "sqlite-backup":
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(target)) as copy:
                original.backup(copy)
                if copy.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError(f"SQLite validation failed: {source.relative_to(root)}")
        shutil.copymode(source, target)
    else:
        checksum = digest(source)
        shutil.copy2(source, target)
        if digest(target) != checksum:
            raise ValueError(f"File changed while copying: {source.relative_to(root)}")
    return digest(target)


def relocate_session_workspaces(root, staged, manifest):
    bot_root = root / "data" / "bots"
    replacements = {
        str(bot / "workspace"): str(root / "workspace" / "bots" / bot.name)
        for bot in bot_root.iterdir() if (bot / "workspace").is_dir()
    } if bot_root.is_dir() else {}
    changed = 0
    for entry in manifest:
        relative = Path(entry["target"])
        if entry["method"] != "copy" or relative.parts[:2] not in {
            ("user-data", "dsh"), ("user-data", "harness")
        } or relative.suffix not in {".json", ".yml", ".yaml"}:
            continue
        target = staged / relative
        original = target.read_text(encoding="utf-8")
        updated = original
        for old, new in replacements.items():
            # Include a path boundary and preserve JSON escaping on Windows.
            for source, destination in {
                (old, new), (json.dumps(old)[1:-1], json.dumps(new)[1:-1])
            }:
                updated = re.sub(re.escape(source) + r"""(?=[/\\"'\s]|$)""",
                                 lambda _: destination, updated)
        if updated != original:
            if relative.suffix == ".json":
                json.loads(updated)
            with target.open("w", encoding="utf-8", newline="") as stream:
                stream.write(updated)
            entry["method"] = "relocated-workspace"
            entry["sha256"] = digest(target)
            changed += 1
    return changed


def verify_deliverables(root, staged):
    database = staged / "user-data/chives.sqlite"
    if not database.is_file():
        return {"readable": 0, "missing_at_source": 0}
    counts = {"readable": 0, "missing_at_source": 0}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='deliverables'").fetchone():
            return counts
        for bot, path in db.execute("SELECT bot_id,path FROM deliverables"):
            relative = Path(path)
            if not re.fullmatch(r"[a-z0-9_-]+", bot) or relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Deliverable requires manual path review")
            source = root / "data" / "bots" / bot / "workspace" / relative
            target = staged / "workspace" / "bots" / bot / relative
            if source.is_file():
                if not target.is_file() or digest(source) != digest(target):
                    raise ValueError("A readable historical deliverable was not preserved")
                counts["readable"] += 1
            else:
                counts["missing_at_source"] += 1
    return counts


LIVE_DIRECTORIES = ("public-data", "workspace", "user-data")


def verified_batch(root, argument):
    batch = (root / argument).resolve(strict=True)
    if batch.parent != root / "runtime" or not batch.name.startswith("data-migration-"):
        raise ValueError("Expected a migration batch directly under runtime/")
    return batch


def move_batch(root, batch, activate):
    receipt = batch / "active"
    directories = LIVE_DIRECTORIES
    if activate:
        if receipt.exists():
            raise ValueError("Batch is already active")
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest:
            relative = Path(entry["target"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid migration manifest path")
            target = batch / relative
            if entry["sha256"] and digest(target) != entry["sha256"]:
                raise ValueError(f"Staged file no longer matches: {relative}")
        if not (batch / "user-data/chives.sqlite").is_file():
            raise ValueError("Missing staged user database")
        source_root, target_root = batch, root
    else:
        if not receipt.is_file():
            raise ValueError("Batch is not active")
        directories = tuple(json.loads(receipt.read_text(encoding="utf-8")))
        if any(name not in LIVE_DIRECTORIES for name in directories):
            raise ValueError("Invalid active migration receipt")
        directories = tuple(reversed(directories))
        source_root, target_root = root, batch
    for name in directories:
        source, target = source_root / name, target_root / name
        if not source.is_dir() or source.is_symlink() or target.exists() or target.is_symlink():
            raise ValueError(f"Cannot move {name}: missing source or destination already exists")
    moved = []
    try:
        for name in directories:
            (source_root / name).rename(target_root / name)
            moved.append(name)
        if activate:
            receipt.write_text(json.dumps(directories) + "\n", encoding="utf-8")
        else:
            receipt.unlink()
    except BaseException:
        for name in reversed(moved):
            (target_root / name).rename(source_root / name)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--stage", action="store_true", help="stage validated copies after stopping writers")
    action.add_argument("--activate", type=Path, metavar="BATCH", help="activate staged directories while stopped")
    action.add_argument("--rollback", type=Path, metavar="BATCH", help="move activated directories back while stopped")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.activate or args.rollback:
        batch = verified_batch(root, args.activate or args.rollback)
        move_batch(root, batch, activate=args.activate is not None)
        print("activated" if args.activate else "rolled back")
        return
    entries = list(plan(root))
    counts = {}
    for _, target, _ in entries:
        counts[target.parts[0]] = counts.get(target.parts[0], 0) + 1
    print(json.dumps(counts, sort_keys=True))
    if not args.stage:
        return
    runtime = root / "runtime"
    if runtime.is_symlink():
        parser.error("runtime/ must be inside the install")
    runtime.mkdir(exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix="data-migration-", dir=runtime))
    try:
        for category in ("user-data", "workspace", "public-data", "review"):
            (staged / category).mkdir(mode=0o700)
        manifest = []
        for source, target, method in entries:
            checksum = stage_entry(root, staged, source, target, method)
            manifest.append({"source": str(source.relative_to(root)), "target": str(target),
                             "method": method, "sha256": checksum})
        relocated = relocate_session_workspaces(root, staged, manifest)
        report = {"relocated_workspace_records": relocated, "deliverables": verify_deliverables(root, staged)}
        (staged / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(staged)
        raise
    print(os.fspath(staged.relative_to(root)))


if __name__ == "__main__":
    main()
