"""Plan or stage a legacy Chives data migration. Staging never activates the result."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from contextlib import closing

USER_ENTRIES = {
    "audit", "bots", "chives.sqlite", "dsh", "harness", "library", "paper",
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
    if top == "hotspots" and rest and rest[0] in {"latest.json", "archive"}:
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
        if source.name in SKIP_NAMES or sqlite_sidecar:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--stage", action="store_true", help="stage validated copies after stopping writers")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
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
        for category in ("user-data", "workspace", "review"):
            (staged / category).mkdir(mode=0o700)
        manifest = []
        for source, target, method in entries:
            checksum = stage_entry(root, staged, source, target, method)
            manifest.append({"source": str(source.relative_to(root)), "target": str(target),
                             "method": method, "sha256": checksum})
        (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(staged)
        raise
    print(os.fspath(staged.relative_to(root)))


if __name__ == "__main__":
    main()
