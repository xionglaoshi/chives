"""Loopback distribution service. Only authenticated requests can fetch Git."""
import re
import mirror
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import urllib.parse
import sys
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
        return archive.open("rb"), sha


def npm_batch(ref, osname, arch, index):
    """Pack the common lockfile v9 registry entries. pnpm resolves any other entries normally."""
    import base64
    import concurrent.futures
    import tarfile
    if not any(STATE.glob(ref+"*.tar.gz")):
        raise FileNotFoundError(ref)
    lock = git(STATE/"upstream.git","show",ref+":pnpm-lock.yaml",capture_output=True,text=True).stdout
    entries = []
    section = lock.partition("\npackages:\n")[2].partition("\nsnapshots:\n")[0]
    for key, body in re.findall(r"^  (\S+):\n((?:    [^\n]*\n)*)",section,re.M):
        key = key.strip("'")
        name, _, version = key.rpartition('@')
        sri = re.search(r"resolution: \{integrity: sha512-([A-Za-z0-9+/=]+)\}",body)
        if not sri or not re.fullmatch(r"(?:@[\w.-]+/)?[\w.-]+",name) or not re.fullmatch(r"[\w.+-]+",version):
            continue
        for key, value in (("cpu",arch),("os",osname)):
            values = re.search(r"^    "+key+r": \[([^\]]+)\]",body,re.M)
            if values and value not in [v.strip() for v in values[1].split(',')]:
                break
        else:
            path = f"npm/{name}/-/{name.split('/')[-1]}-{version}.tgz"
            entries.append((path,sri[1]))
    count = (len(entries)+31)//32
    if index >= max(1,count):
        raise FileNotFoundError(index)
    folder = STATE/'batches'
    folder.mkdir(exist_ok=True)
    archive = folder/f"v1-{ref}-{osname}-{arch}-{index}.tar"
    with archive.with_suffix('.lock').open('a') as gate:
        fcntl.flock(gate,fcntl.LOCK_EX)
        if not archive.exists():
            def checked(item):
                path, expected = item
                file,_ = mirror.cached(path)
                with file.open('rb') as handle:
                    actual = base64.b64encode(hashlib.file_digest(handle,'sha512').digest()).decode()
                if actual != expected:
                    raise OSError("锁文件校验失败")
                return file, hashlib.sha256(path.encode()).hexdigest()
            with tempfile.NamedTemporaryFile(dir=folder) as tmp:
                with concurrent.futures.ThreadPoolExecutor(6) as pool, tarfile.open(fileobj=tmp,mode='w') as out:
                    for file, name in pool.map(checked,entries[index*32:index*32+32]):
                        out.add(file,arcname=name,recursive=False)
                tmp.flush()
                os.link(tmp.name,archive)
    return archive,count


class Handler(BaseHTTPRequestHandler):
    def enabled(self):
        return (STATE / "enabled").exists()

    def reply(self, status, body, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        name = urllib.parse.urlsplit(self.path).path.removeprefix("/")
        if name in SCRIPTS:
            return self.reply(200, (FILES / name).read_bytes())
        asset = name.removeprefix("assets/") if name.startswith("assets/") else None
        batch = re.fullmatch(r"batch/([a-f0-9]{40})/(win32|darwin|linux)/(x64|arm64)/([0-9]{1,3})",name)
        if not batch and asset is None and name not in {"status", "package"}:
            return self.reply(404, b"Not found")
        if not self.enabled():
            return self.reply(503, STOPPED.encode())
        if name == "status":
            return self.reply(200, b"enabled")
        if asset is not None and (asset == "uv-version" or asset.startswith(("uv/", "python/"))):
            return mirror.serve(self, asset, self.command == "HEAD")
        supplied = self.headers.get("Authorization", "")
        digest = hashlib.sha256(supplied.encode()).hexdigest()
        if not hmac.compare_digest(digest, (STATE / "code.sha256").read_text().strip()):
            return self.reply(403, "安装码无效，请与熊翔本人联系".encode())
        if batch:
            try:
                file,count = npm_batch(*batch.groups()[:3],int(batch[4]))
            except FileNotFoundError:
                return self.reply(404,b"Batch not found")
            except (OSError,subprocess.SubprocessError):
                return self.reply(502,b"Dependency batch could not be prepared")
            with file.open("rb") as handle:
                if not self.enabled():
                    return self.reply(503,STOPPED.encode())
                self.send_response(200)
                self.send_header("Content-Length",str(file.stat().st_size))
                self.send_header("X-Chives-Batches",str(count))
                self.end_headers()
                if self.command != "HEAD":
                    shutil.copyfileobj(handle,self.wfile)
            return
        if asset is not None:
            return mirror.serve(self, asset, self.command == "HEAD")
        try:
            archive, sha = package()
        except (subprocess.SubprocessError, OSError):
            self.log_error("GitHub fetch or archive failed")
            return self.reply(502, "暂时无法从 GitHub 获取最新版 Chives".encode())
        with archive:
            if not self.enabled():
                return self.reply(503, STOPPED.encode())
            tag = '"'+sha+'"'
            if self.headers.get("If-None-Match") == tag:
                self.send_response(304)
                self.send_header("ETag", tag)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("ETag", tag)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Chives-Commit", sha)
            self.send_header("Content-Length", str(os.fstat(archive.fileno()).st_size))
            self.end_headers()
            if self.command != "HEAD":
                shutil.copyfileobj(archive, self.wfile)


class DistributionServer(ThreadingHTTPServer):
    request_queue_size = 128

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1],(BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


if __name__ == "__main__":
    DistributionServer(("127.0.0.1", 18765), Handler).serve_forever()
