"""Prepare the installation-local Bot workspace without changing the live service."""

import argparse
from pathlib import Path
import re
import shutil
import tempfile


def workspace_sources(root: Path):
    bots = root / "data" / "bots"
    if not bots.is_dir():
        return []
    sources = []
    for bot in sorted(bots.iterdir()):
        if not re.fullmatch(r"[a-z0-9_-]+", bot.name):
            continue
        source = bot / "workspace"
        if source.is_symlink() or (source.is_dir() and not source.resolve().is_relative_to(root)):
            raise ValueError(f"External workspace needs review: {source}")
        if source.is_dir():
            if any(path.is_symlink() for path in source.rglob("*")):
                raise ValueError(f"Workspace links need review: {source}")
            sources.append(source)
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--apply", action="store_true", help="copy while workspace writers are stopped")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    sources = workspace_sources(root)
    target = root / "workspace" / "bots"
    for source in sources:
        print(f"{source.relative_to(root)} -> {(target / source.parent.name).relative_to(root)}")
    if not args.apply or not sources:
        return
    if target.parent.is_symlink() or target.exists() or target.is_symlink():
        parser.error("workspace/bots already exists or workspace is a symlink")
    target.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".migration-", dir=target.parent) as temporary:
        staged = Path(temporary) / "bots"
        staged.mkdir()
        for source in sources:
            shutil.copytree(source, staged / source.parent.name)
        if target.exists() or target.is_symlink():
            parser.error("workspace/bots appeared during migration")
        staged.rename(target)


if __name__ == "__main__":
    main()
