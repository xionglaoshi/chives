"""Install a version of Chives into an isolated, user-owned directory."""
from __future__ import annotations

import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

BASE = "https://150.158.11.154/chives-install"
NODE_VERSION = "26.9.0"
WINDOWS = os.name == "nt"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PORTS = {"gateway": 8868, "strategy": 8869, "server": 8880, "web": 8888,
         "watch": 8865, "market": 8866, "hub": 8867}


def download(url, destination, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=150) as response, destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)
            return response.headers
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read(2048).decode("utf-8", errors="replace")) from None


def run(*args, cwd, env):
    subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def runtime(root, release):
    tools = root / "tools"
    uv = tools / ("uv.exe" if WINDOWS else "uv")
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "win"}[platform.system()]
    cpu = {"aarch64": "arm64", "arm64": "arm64", "amd64": "x64", "x86_64": "x64"}[platform.machine().lower()]
    node_name = f"node-v{NODE_VERSION}-{system}-{cpu}"
    node_dir = tools / node_name
    node = node_dir / ("node.exe" if WINDOWS else "bin/node")
    npm = node_dir / ("node_modules/npm/bin/npm-cli.js" if WINDOWS else "lib/node_modules/npm/bin/npm-cli.js")
    npx = npm.with_name("npx-cli.js")
    env = os.environ.copy()
    env.setdefault("HOME", str(Path.home()))
    env.setdefault("PYTHONUTF8", "1")
    env.update({
        "PATH": os.pathsep.join([str(node.parent), str(tools), env.get("PATH", "")]),
        "CHIVES_DATA_DIR": str(root / "data"),
        "DSH_FINANCE_HOME": str(root / "data/dsh"),
        "DSH_HOME": str(root / "data/dsh"),
        "DSH_FINANCE_OVERLAY": "",
        "CHIVES_HARNESS": "dsh",
        "CHIVES_PAPER_STATE_DIR": str(root / "data/paper"),
        "CN_DAILY_STORE_DB": str(root / "data/marketdata/daily.sqlite"),
        "PLAYWRIGHT_BROWSERS_PATH": str(release / "runtime/ms-playwright/browsers"),
        "npm_config_cache": str(root / "cache/npm"),
        "CHIVES_NPX_JS": str(npx),
    })
    python = release / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")
    env["CALENDAR_PYTHON"] = str(python)
    return uv, node, npm, npx, python, node_name, env


def prepare_node(node, node_name):
    if node.is_file():
        return
    tools = node.parents[1 if WINDOWS else 2]
    with tempfile.TemporaryDirectory(dir=tools) as folder:
        work = Path(folder)
        name = node_name + (".zip" if WINDOWS else ".tar.gz")
        prefix = f"https://nodejs.org/dist/v{NODE_VERSION}"
        archive, checksums = work / name, work / "SHASUMS256.txt"
        download(f"{prefix}/{name}", archive)
        download(f"{prefix}/SHASUMS256.txt", checksums)
        expected = dict(line.split()[::-1] for line in checksums.read_text().splitlines())[name]
        with archive.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError("Node.js SHA-256 校验失败")
        if WINDOWS:
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(work)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(work, filter="data")
        (work / node_name).rename(tools / node_name)


def patch_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"最新版的跨平台适配需要更新: {path.name}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def portable_paths(release, python):
    wrapper = release / "mcp-cwd.py"
    wrapper.write_text(
        "import os,subprocess,sys\nos.chdir(sys.argv[1])\nraise SystemExit(subprocess.call(sys.argv[2:]))\n",
        encoding="utf-8",
    )
    for overlay in (release / "overlays").glob("*.cordis.yml"):
        text = overlay.read_text(encoding="utf-8")
        def replace(match):
            field, relative = match.groups()
            if field == "command: ":
                leaf = relative.rsplit("/", 1)[-1]
                path = python if leaf == "python" else python.with_name(leaf + (".exe" if WINDOWS else ""))
            else:
                path = release / (relative or "")
            return field + json.dumps(str(path), ensure_ascii=False)
        text = re.sub(r"(command: |cwd: |name: |- )/Users/xiong/\.chives(?:/([^\r\n]+))?", replace, text)
        overlay.write_text(text, encoding="utf-8")
    for gateway in (release / "gateways").glob("*/config.yaml"):
        text = gateway.read_text(encoding="utf-8")
        text = re.sub(r"command: /Users/xiong/\.agents/venvs/chives/bin/python",
                      lambda _: "command: " + json.dumps(str(python), ensure_ascii=False), text)
        text = re.sub(r"command: /Users/xiong/\.chives/[^\r\n]*/\.venv/bin/([^\r\n]+)",
                      lambda m: "command: " + json.dumps(str(python.with_name(m[1] + (".exe" if WINDOWS else ""))), ensure_ascii=False), text)
        text = re.sub(r"(cwd: |\[)/Users/xiong/\.chives/([^\r\n\]]+)",
                      lambda m: m[1] + json.dumps(str(release / m[2]), ensure_ascii=False), text)
        gateway.write_text(text, encoding="utf-8")
    dsh = release / "apps/server/src/harness/dsh.ts"
    patch_once(dsh, "command: '/bin/sh',\n        args: ['-c', 'cd \"$0\" && exec \"$@\"', overlay.cwd, overlay.command, ...args],",
               "command: process.env.CALENDAR_PYTHON!,\n        args: [join(repoRoot, 'mcp-cwd.py'), overlay.cwd, overlay.command, ...args],")
    patch_once(dsh, "    command: 'npx',\n    args: [\n      '-y',",
               "    command: process.execPath,\n    args: [\n      process.env.CHIVES_NPX_JS!,\n      '-y',")
    for name in ("app.ts", "settings/channels.ts", "settings/profile-excerpt.ts", "dashboard/hotspots.ts"):
        file = release / "apps/server/src" / name
        text = file.read_text(encoding="utf-8")
        text, changed = re.subn(
            r"(join(?:Path)?\((?:userHome|homedir)\(\),\s*'\.agents/venvs/chives/bin/python'\))",
            r"(process.env.CALENDAR_PYTHON ?? \1)",
            text,
        )
        if not changed:
            raise RuntimeError(f"最新版的 Python 路径适配需要更新: {name}")
        file.write_text(text, encoding="utf-8")
    if WINDOWS:
        site_packages = release / ".venv/Lib/site-packages"
        (site_packages / "fcntl.py").write_text(
            """import errno
import msvcrt
import os
import time

LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8

def flock(file, operation):
    fd = file if isinstance(file, int) else file.fileno()
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        if operation == LOCK_UN:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if operation & LOCK_NB:
                    raise BlockingIOError(errno.EAGAIN, "file lock busy") from exc
                time.sleep(0.1)
    finally:
        os.lseek(fd, position, os.SEEK_SET)
""",
            encoding="utf-8",
        )
        for name in ("holdings.ts", "portfolio.ts"):
            path = release / "apps/server/src/dashboard" / name
            path.write_text(re.sub(r"'\.venv',\s*'bin',\s*'python'", "'.venv', 'Scripts', 'python.exe'",
                                   path.read_text(encoding="utf-8")), encoding="utf-8")
        browser = release / "packages/scrape-mcp/src/scrape_mcp/private_browser.py"
        patch_once(browser, 'python_dir / "playwright/driver/node"', 'python_dir / "playwright/driver/node.exe"')


def prepare(root, release):
    uv, node, npm, npx, python, node_name, env = runtime(root, release)
    prepare_node(node, node_name)
    version = (release / "config/dsh-version").read_text().strip()
    run(node, npx, "-y", f"@deepseek-ai/dsh@{version}", "--version", cwd=release, env=env)
    run(uv, "venv", "--python", "3.12", release / ".venv", cwd=release, env=env)
    editable = [arg for p in sorted((release / "packages").glob("*/pyproject.toml")) for arg in ("-e", p.parent)]
    run(uv, "pip", "install", "--python", python, "qrcode[pil]", "websockets>=15,<17", *editable, cwd=release, env=env)
    run(uv, "pip", "check", "--python", python, cwd=release, env=env)
    for manifest in (release / "packages").glob("*/pyproject.toml"):
        link = manifest.parent / ".venv"
        if WINDOWS:
            run(os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", link, release / ".venv", cwd=release, env=env)
        else:
            link.symlink_to(release / ".venv", target_is_directory=True)
    portable_paths(release, python)
    pw_env = {**env, "PYTHONPATH": str(release / "runtime/ms-playwright/python")}
    run(uv, "pip", "install", "--python", python, "--target", pw_env["PYTHONPATH"],
        "playwright==1.65.2", cwd=release, env=env)
    run(python, "-m", "playwright", "install", "chromium", cwd=release, env=pw_env)
    browser_check = [python, "-c", "from playwright.sync_api import sync_playwright\nwith sync_playwright() as p:\n b=p.chromium.launch(); print(b.version); b.close()"]
    if sys.platform.startswith("linux"):
        try:
            run(*browser_check, cwd=release, env=pw_env)
        except subprocess.CalledProcessError:
            dep_args = [python, "-m", "playwright", "install-deps", "chromium"]
            if os.geteuid() != 0:
                dep_args = ["sudo", "env", f"PYTHONPATH={pw_env['PYTHONPATH']}", *dep_args]
            run(*dep_args, cwd=release, env=pw_env)
            run(*browser_check, cwd=release, env=pw_env)
    else:
        run(*browser_check, cwd=release, env=pw_env)
    pnpm = [node, npx, "-y", "pnpm@10.33.0"]
    run(*pnpm, "install", "--frozen-lockfile", "--store-dir", root / "cache/pnpm", cwd=release, env=env)
    run(*pnpm, "build", cwd=release, env=env)


def healthy(name):
    path = {"web": "/", "server": "/api/health"}.get(name, "/health")
    try:
        with HTTP.open(f"http://127.0.0.1:{PORTS[name]}{path}", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def service_specs(release, node, python):
    packages = release / "packages"
    apps = release / "apps"
    specs = {
        "gateway": (packages / "cn-market-gateway", [python, "-m", "cn_market_gateway", "serve", "--host", "127.0.0.1", "--port", "8868"]),
        "strategy": (packages / "strategy-hub", [python, "-m", "strategy_hub", "--host", "127.0.0.1", "--port", "8869"]),
        "server": (apps / "server", [node, apps / "server/node_modules/tsx/dist/cli.mjs", "src/main.ts"]),
        "web": (apps / "web", [node, apps / "web/node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "8888", "--strictPort"]),
    }
    for name, package, module, config in (
        ("watch", "cn-watch", "cn_watch", release / "config/watch.yaml"),
        ("market", "market-watch", "market_watch", packages / "market-watch/config.example.yaml"),
        ("hub", "chives-hub", "chives_hub", packages / "chives-hub/config.example.yaml"),
    ):
        specs[name] = (packages / package, [python, "-m", module, "--config", config,
                                          "--out-dir", release / "runtime" / name])
    return specs


def supervise(root, release):
    _, node, _, _, python, _, env = runtime(root, release)
    logs = root / "logs"
    shutdown = root / "stop"
    children = []
    try:
        for name, (cwd, args) in service_specs(release, node, python).items():
            with (logs / f"{name}.log").open("wb") as stream:
                child = subprocess.Popen([str(arg) for arg in args], cwd=cwd, env=env,
                                         stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                         start_new_session=not WINDOWS)
                children.append(child)
            for _ in range(120):
                if child.poll() is not None or shutdown.exists():
                    raise RuntimeError(f"{name} 启动失败，请检查 {logs / (name + '.log')}")
                if healthy(name):
                    break
                time.sleep(1)
            else:
                raise RuntimeError(f"{name} 健康检查超时")
        (root / "ready").write_text(release.name)
        while not shutdown.exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Chives 有组件意外退出")
            time.sleep(1)
    finally:
        (root / "ready").unlink(missing_ok=True)
        for child in reversed(children):
            if WINDOWS:
                subprocess.run(["taskkill", "/pid", str(child.pid), "/t", "/f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        (root / "running").unlink(missing_ok=True)


def start(root, release):
    running = root / "running"
    stop = root / "stop"
    if running.exists():
        stop.touch()
        for _ in range(100):
            if not running.exists():
                break
            time.sleep(0.3)
        else:
            raise RuntimeError("旧实例尚未退出，请检查 Chives 日志")
    stop.unlink(missing_ok=True)
    for port in PORTS.values():
        with socket.socket() as stream:
            if stream.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"本机端口 {port} 已被占用")
    running.touch(exist_ok=False)
    runner = release / "install.py"
    _, _, _, _, python, _, _ = runtime(root, release)
    options = {"creationflags": 0x00000008 | 0x00000200} if WINDOWS else {"start_new_session": True}
    log = root / "logs/supervisor.log"
    try:
        with log.open("wb") as handle:
            child = subprocess.Popen([str(python), str(runner), str(root), str(release)], cwd=release,
                                     stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, **options)
    except BaseException:
        running.unlink(missing_ok=True)
        raise
    for _ in range(240):
        if child.poll() is not None:
            raise RuntimeError(f"启动失败，请检查 {log} 及同目录组件日志")
        if (root / "ready").exists() and all(healthy(name) for name in PORTS):
            return
        time.sleep(1)
    stop.touch()
    raise RuntimeError(f"启动超时，请检查 {log}")


def install(root):
    releases = root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    (root / "data/dsh").mkdir(parents=True, exist_ok=True)
    lock = root / "installing"
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError(f"已有安装任务，若已退出请移除空目录 {lock}") from None
    try:
        code = os.environ.get("CHIVES_INSTALL_CODE") or getpass.getpass("Chives 安装码: ")
        with tempfile.TemporaryDirectory(dir=root) as temp:
            archive = Path(temp) / "chives.tar.gz"
            headers = download(f"{BASE}/package", archive, {"Authorization": "Bearer " + code.strip()})
            sha = headers.get("X-Chives-Commit", "")
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise RuntimeError("安装源缺少有效的 Git 提交编号")
            revision = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:8]
            release = releases / f"{sha[:12]}-{revision}"
            if not (release / ".installed").exists():
                if release.exists():
                    raise RuntimeError(f"上次安装尚未完成，请先移走 {release}")
                release.mkdir()
                with tarfile.open(archive) as bundle:
                    bundle.extractall(release, filter="data")
                try:
                    prepare(root, release)
                except BaseException:
                    failed = releases / f"failed-{sha[:12]}-{time.time_ns()}"
                    release.rename(failed)
                    print(f"失败现场保存在 {failed}", file=sys.stderr)
                    raise
                (release / ".installed").touch()
            shutil.copyfile(__file__, release / "install.py")
        if os.environ.get("CHIVES_INSTALL_BUILD_ONLY") == "1":
            print(f"Chives {sha[:12]} 依赖、浏览器及构建检查通过，未启动服务。")
            return
        start(root, release)
        print(f"Chives {sha[:12]} 已启动: http://127.0.0.1:8888/ 。请在设置中添加模型。")
    finally:
        lock.rmdir()


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3:
            supervise(Path(sys.argv[1]), Path(sys.argv[2]))
        else:
            install(Path(sys.argv[1]).expanduser().resolve())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
