"""Refresh the Mac-served production UI when frontend inputs change."""
from pathlib import Path
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"
STAMP = ROOT / "runtime/public-build.inputs"
roots = [WEB / "src", WEB / "public", WEB / "index.html", WEB / "vite.config.ts",
         WEB / "package.json", ROOT / "pnpm-lock.yaml", ROOT / "packages/chives-ui/src",
         ROOT / "apps/server/src/bots/pixel-icons.ts", ROOT / "INSTALL.md",
         ROOT / "docs/设置中心.md", ROOT / "docs/专家内核与配置.md", ROOT / "docs/投研工具.md",
         ROOT / "packages/chives-terminal/chives_terminal/command-reference.json"]


def fingerprint():
    digest = hashlib.sha256()
    for root in roots:
        paths = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in paths:
            if path.is_file() and path.name != ".DS_Store":
                digest.update(str(path.relative_to(ROOT)).encode())
                digest.update(b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


current = fingerprint()
if not STAMP.exists() or STAMP.read_text() != current or not (ROOT / "runtime/public-dist/index.html").exists():
    subprocess.run(["/bin/bash", str(ROOT / "scripts/build-public.sh")], check=True)
    STAMP.write_text(current)
