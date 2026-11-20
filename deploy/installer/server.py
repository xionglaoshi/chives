"""Loopback distribution service. Only authenticated requests can fetch Git."""
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import urllib.parse
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FILES = Path(__file__).resolve().parent
STATE = Path("/var/lib/chives-install")
REMOTE = "ssh://git@ssh.github.com:443/xionglaoshi/chives.git"
STOPPED = "熊翔已停用便捷安装Chives的功能，请与熊翔本人联系"
SCRIPTS = {"macos.sh", "linux.sh", "windows.ps1", "install.py"}
PATHS = (
    "apps", "bots", "config", "gateways", "overlays", "packages", "patches", "presets", "scripts", "skills",
    "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "tsconfig.base.json",
    "eslint.config.js", "THIRD_PARTY_NOTICES.md",
)


def git(repo, *args, **options):
    return subprocess.run(["git", "--git-dir", str(repo), *args], check=True, timeout=120, **options)


def package():
    repo = STATE / "upstream.git"
    with (STATE / "fetch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (repo / "HEAD").exists():
            git(repo, "init", "--bare")
        git(repo, "fetch", "--no-tags", "--depth=1", REMOTE, "refs/heads/main")
        sha = git(repo, "rev-parse", "FETCH_HEAD", capture_output=True, text=True).stdout.strip()
        layout = hashlib.sha256("\0".join(PATHS).encode()).hexdigest()[:8]
        archive = STATE / f"{sha}-{layout}.tar.gz"
        if not archive.exists():
            with tempfile.NamedTemporaryFile(dir=STATE) as output:
                git(repo, "archive", "--format=tar.gz", sha, "--", *PATHS, stdout=output)
                shutil.copyfile(output.name, archive.with_suffix(".new"))
                archive.with_suffix(".new").replace(archive)
            for old in STATE.glob("*.tar.gz"):
                if old != archive:
                    old.unlink()
        return archive.open("rb"), sha


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        name = urllib.parse.urlsplit(self.path).path.removeprefix("/")
        if name in SCRIPTS:
            return self.reply(200, (FILES / name).read_bytes())
        if name not in {"status", "package"}:
            return self.reply(404, b"Not found")
        if not (STATE / "enabled").exists():
            return self.reply(503, STOPPED.encode())
        if name == "status":
            return self.reply(200, b"enabled")
        supplied = self.headers.get("Authorization", "")
        digest = hashlib.sha256(supplied.encode()).hexdigest()
        if not hmac.compare_digest(digest, (STATE / "code.sha256").read_text().strip()):
            return self.reply(403, "安装码无效，请与熊翔本人联系".encode())
        try:
            archive, sha = package()
        except (subprocess.SubprocessError, OSError):
            self.log_error("GitHub fetch or archive failed")
            return self.reply(502, "暂时无法从 GitHub 获取最新版 Chives".encode())
        with archive:
            if not (STATE / "enabled").exists():
                return self.reply(503, STOPPED.encode())
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Chives-Commit", sha)
            self.send_header("Content-Length", str(os.fstat(archive.fileno()).st_size))
            self.end_headers()
            shutil.copyfileobj(archive, self.wfile)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18765), Handler).serve_forever()
