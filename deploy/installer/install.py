"""GitHub release installer and local Chives service supervisor (CPython 3.12)."""
from __future__ import annotations

from contextlib import contextmanager
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

NODE_VERSION = "26.9.0"
WINDOWS = os.name == "nt"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PORTS = {"gateway": 8868, "strategy": 8869, "server": 8880, "web": 8888,
         "watch": 8865, "market": 8866, "hub": 8867}


LOG = None
CURRENT = "检查依赖"


def stage(n, label):
    global CURRENT
    CURRENT = label
    print(f"\n  [{n}/6] [{'#'*(n-1)}{'-'*(7-n)}] {(n-1)*100//6}%  {label}", flush=True)


def run(*args, cwd, env, label=None):
    label = label or CURRENT
    start_time = time.monotonic()
    with LOG.open('ab') as out:
        out.write(('\n--- '+label+' ---\n').encode())
        out.flush()
        print(f"    {label}…",flush=True)
        with subprocess.Popen([str(arg) for arg in args],cwd=cwd,env=env,stdout=out,stderr=out) as child:
            while True:
                try:
                    result = child.wait(timeout=8)
                    break
                except subprocess.TimeoutExpired:
                    print(f'    {label} · 已用 {int(time.monotonic()-start_time)} 秒',flush=True)
            if result:
                with LOG.open('rb') as details:
                    details.seek(max(0,details.seek(0,2)-4096))
                    lines = [ln.strip() for ln in details.read().decode('utf-8','replace').splitlines() if ln.strip()]
                    if lines:
                        print('    '+lines[-1][:240],file=sys.stderr)
                raise RuntimeError(f'{label}失败（退出码 {result}）。详细日志 {LOG}')
    print(f'    ✓ {label}',flush=True)

def runtime(root, release):
    config = json.loads((release / "runtime-paths.json").read_text(encoding="utf-8"))
    node, npx = Path(config["node"]), Path(config["npx"])
    python = release / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")
    env = os.environ.copy()
    for key in ("CHIVES_INSTALL_CODE", "CHIVES_SETUP_PROXY"):
        env.pop(key, None)
    env.setdefault("HOME", str(Path.home()))
    env.update({
        "PYTHONUTF8": "1", "CALENDAR_PYTHON": str(python),
        "PATH": os.pathsep.join([str(node.parent), str(python.parent), env.get("PATH", "")]),
        "CHIVES_DATA_DIR": str(root / "data"), "DSH_HOME": str(root / "data/dsh"),
        "DSH_FINANCE_HOME": str(root / "data/dsh"), "DSH_FINANCE_OVERLAY": "",
        "CHIVES_HARNESS": "dsh", "CHIVES_PAPER_STATE_DIR": str(root / "data/paper"),
        "CN_DAILY_STORE_DB": str(root / "data/marketdata/daily.sqlite"),
        "PLAYWRIGHT_BROWSERS_PATH": str(release / "runtime/ms-playwright/browsers"),
        "npm_config_cache": config.get("npm_cache", str(release / "offline/npm")), "CHIVES_NPX_JS": str(npx),
    })
    if config.get("dsh_js"):
        env["CHIVES_DSH_JS"] = config["dsh_js"]
    if (release / "runtime/ms-playwright/use-private-libs").is_file():
        libs = str(release / "runtime/ms-playwright/browser-libs")
        env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, [libs, env.get("LD_LIBRARY_PATH")]))
    return node, python, env


def patch_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"最新版的跨平台适配需要更新: {path.name}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def portable_paths(release, python, *, direct_dsh=False):
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
    if direct_dsh:
        pinned = json.dumps((release / "config/dsh-version").read_text().strip())
        patch_once(dsh, "    command: 'npx',\n    args: [\n      '-y',\n      '@deepseek-ai/dsh@'+selectedVersion(options.dataDir),",
                   "    command: process.execPath,\n    args: [\n      ...(selectedVersion(options.dataDir) === "+pinned+
                   " ? [process.env.CHIVES_DSH_JS!] : [process.env.CHIVES_NPX_JS!, '-y', '@deepseek-ai/dsh@'+selectedVersion(options.dataDir)]),")
    else:
        patch_once(dsh, "    command: 'npx',\n    args: [\n      '-y',",
                   "    command: process.execPath,\n    args: [\n      process.env.CHIVES_NPX_JS!,\n      '-y',")
        version = (release / "config/dsh-version").read_text().strip()
        patch_once(dsh, "      process.env.CHIVES_NPX_JS!,\n      '-y',",
                   "      process.env.CHIVES_NPX_JS!,\n      ...(selectedVersion(options.dataDir) === " +
                   json.dumps(version) + " ? ['--offline'] : []),\n      '-y',")
    for name in ("app.ts", "settings/channels.ts", "settings/profile-excerpt.ts", "dashboard/hotspots.ts"):
        file = release / "apps/server/src" / name
        text = file.read_text(encoding="utf-8")
        text, changed = re.subn(
            r"(join(?:Path)?\((?:userHome|homedir)\(\),\s*'\.agents/venvs/chives/bin/python'\))",
            r"(process.env.CALENDAR_PYTHON ?? \1)",
            text,
        )
        if not changed and "CALENDAR_PYTHON" not in text:
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
    node, python, env = runtime(root, release)
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


@contextmanager
def command_lock(root):
    # The OS releases this lock even when a terminal or installer is interrupted.
    with (root / "service.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if WINDOWS:
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("另一个 Chives 启停命令正在执行，请稍后重试") from exc
        yield


def stop_service(root):
    running = root / "running"
    if not running.exists():
        return
    (root / "stop").touch()
    for _ in range(120):
        if not running.exists():
            return
        time.sleep(0.5)
    # A power loss can leave a marker with no supervisor or services left.
    for port in PORTS.values():
        with socket.socket() as stream:
            if stream.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"服务仍在退出，请查看 {root / 'logs/supervisor.log'}")
    running.unlink(missing_ok=True)
    (root / "ready").unlink(missing_ok=True)


def control(root, release, action):
    with command_lock(root):
        if action == "open" and (root / "running").exists() and (root / "ready").exists():
            if healthy("server") and healthy("web"):
                return
        stop_service(root)
        if action != "stop":
            start(root, release)


def start(root, release):
    running = root / "running"
    stop = root / "stop"
    stop.unlink(missing_ok=True)
    for port in PORTS.values():
        with socket.socket() as stream:
            if stream.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"本机端口 {port} 已被占用")
    running.touch(exist_ok=False)
    runner = release / "install.py"
    _, python, _ = runtime(root, release)
    options = {"creationflags": 0x00000008 | 0x00000200} if WINDOWS else {"start_new_session": True}
    log = root / "logs/supervisor.log"
    try:
        with log.open("wb") as handle:
            launch_env = {k:v for k,v in os.environ.items() if k not in ("CHIVES_INSTALL_CODE", "CHIVES_SETUP_PROXY")}
            child = subprocess.Popen([str(python), str(runner), str(root), str(release)], cwd=release, env=launch_env,
                                     stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, **options)
    except BaseException:
        running.unlink(missing_ok=True)
        raise
    for elapsed in range(240):
        if elapsed % 8 == 0:
            print(f"    等待本地服务就绪 · {elapsed} 秒",flush=True)
        if child.poll() is not None:
            raise RuntimeError(f"启动失败，请检查 {log} 及同目录组件日志")
        if (root / "ready").exists() and all(healthy(name) for name in PORTS):
            return
        time.sleep(1)
    stop.touch()
    raise RuntimeError(f"启动超时，请检查 {log}")



def check_output(*args, env=None):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=10, env=env).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def find_node(platform_id):
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if WINDOWS else "npm")
    if node and npm:
        actual = check_output(node, "-p", "process.versions.node+' '+process.arch")
        # npm can be managed independently of node, especially with nvm and Volta.
        prefix = check_output(npm, "root", "-g")
        if prefix:
            npx = Path(prefix) / "npm/bin/npx-cli.js"
            npm_cli = npx.with_name("npm-cli.js")
            if (re.fullmatch(r"26\.\d+\.\d+ " + platform_id.split("-")[1], actual)
                    and npx.is_file() and check_output(node, npm_cli, "--version")
                    and check_output(node, npx, "--version")):
                print(f"    ✓ 复用 Node.js {actual} 和 npm {check_output(node, npm_cli, '--version')}", flush=True)
                return Path(node).resolve(), npx.resolve()
    print(f"    将补装 Node.js {NODE_VERSION} 和配套 npm/npx（当前 Node 或 npm 缺失或版本不兼容）", flush=True)
    return None


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def get_asset(root, tag, name):
    base = f"https://github.com/xionglaoshi/chives/releases/download/{tag}/{name}"
    proxy = os.environ.get("CHIVES_SETUP_PROXY", "")
    curl = ["curl.exe" if WINDOWS else "curl", "-q", "--proto", "=https", "--proto-redir", "=https",
            "--noproxy", "localhost,127.0.0.1" if proxy else "*", "--connect-timeout", "8",
            "-fsSL", "--retry", "2", "--speed-time", "60", "--speed-limit", "1"]
    if proxy:
        curl += ["--proxy", proxy]
    checksum = subprocess.run([*curl, "--max-time", "45", base + ".sha256"], capture_output=True, text=True)
    match = re.fullmatch(r"([a-f0-9]{64}) ([1-9]\d*)\s*", checksum.stdout)
    if checksum.returncode or not match:
        raise RuntimeError(f"GitHub 缺少 {tag} 的 {name} 或完整校验信息")
    digest, size = match[1], int(match[2])
    folder = root / "cache/installer"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{digest}-{name}"
    if dest.is_file() and dest.stat().st_size == size and file_hash(dest) == digest:
        print(f"    ✓ 复用已校验的 {name}", flush=True)
        return dest
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        pending = Path(tmp) / name
        print(f"    {name} · {size/1048576:.1f} MiB", flush=True)
        with subprocess.Popen([*curl, "-o", str(pending), base]) as process:
            previous, tick = 0, time.monotonic()
            while process.poll() is None:
                try:
                    process.wait(timeout=0.5 if sys.stdout.isatty() else 5)
                except subprocess.TimeoutExpired:
                    pass
                count = pending.stat().st_size if pending.exists() else 0
                now = time.monotonic()
                fraction = min(20, 20*count//size)
                rate = max(0, count-previous) / max(now-tick, 0.001) / 1048576
                progress = f"    [{'#'*fraction}{'-'*(20-fraction)}] {min(100,count*100//size):3}% · {count/1048576:.1f} MiB · {rate:.2f} MiB/s"
                print(progress, end="\r" if sys.stdout.isatty() and process.poll() is None else "\n", flush=True)
                previous, tick = count, now
            if process.returncode:
                raise RuntimeError(f"{name} 下载中断，可重新运行向导")
        if pending.stat().st_size != size or file_hash(pending) != digest:
            raise RuntimeError(f"{name} 校验不匹配，已丢弃本次下载")
        pending.replace(dest)
    return dest


def extract_tar(path, target):
    with tarfile.open(path) as archive:
        archive.extractall(target, filter="data")


def unlock(payload, work, release):
    # These two modules come from the verified GitHub bootstrap for this architecture.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
    import pyzipper
    code = os.environ.pop("CHIVES_INSTALL_CODE", None) or getpass.getpass("    Chives 安装码（输入时隐藏）: ")
    plain = work / "chives.tar.gz"
    try:
        with pyzipper.AESZipFile(payload) as sealed, sealed.open("chives.tar.gz", pwd=code.encode()) as src, plain.open("wb") as out:
            shutil.copyfileobj(src, out, 1024*1024)
    except (RuntimeError, ValueError, pyzipper.BadZipFile) as exc:
        raise RuntimeError("安装码不正确，或发行包损坏") from exc
    print("    ✓ 安装码验证通过，正在展开程序、浏览器和离线依赖…", flush=True)
    extract_tar(plain, release)


BROWSER_CHECK = ("from playwright.sync_api import sync_playwright\n"
                 "from pathlib import Path\n"
                 "with sync_playwright() as p:\n"
                 " path=Path(p.chromium.executable_path); assert path.is_file(), path\n"
                 " b=p.chromium.launch(); print(b.version); b.close()")


def reuse_browser(release, candidates=()):
    runtime_dir = release / "runtime/ms-playwright"
    home = Path.home()
    default = (Path(os.environ.get("LOCALAPPDATA", home)) / "ms-playwright" if WINDOWS else
               home / "Library/Caches/ms-playwright" if sys.platform == "darwin" else
               Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "ms-playwright")
    candidates = [*candidates, default]
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        candidates.insert(0, Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    cache = runtime_dir / "browsers"
    descriptors = json.loads((runtime_dir/"python/playwright/driver/package/browsers.json").read_text())
    for folder in candidates:
        if not folder.is_dir():
            continue
        env = dict(os.environ, PYTHONPATH=str(runtime_dir/"python"), PLAYWRIGHT_BROWSERS_PATH=str(folder))
        probe = subprocess.run([sys.executable, "-s", "-c", BROWSER_CHECK], env=env, capture_output=True)
        if probe.returncode:
            continue
        cache.mkdir()
        for item in descriptors["browsers"]:
            if item["name"] not in ("chromium", "chromium-headless-shell", "ffmpeg"):
                continue
            for rev in {item["revision"], *item.get("revisionOverrides", {}).values()}:
                part = folder / (item["name"].replace("-", "_")+"-"+rev)
                if part.is_dir():
                    shutil.copytree(part, cache / part.name, symlinks=not WINDOWS)
        # Recheck from the private path before trusting the copy (platform overrides may differ).
        probe = subprocess.run([sys.executable, "-s", "-c", BROWSER_CHECK],
                               env={**env, "PLAYWRIGHT_BROWSERS_PATH":str(cache)}, capture_output=True)
        if not probe.returncode:
            print("    ✓ 复用本机匹配且可启动的 Chromium", flush=True)
            return True
        shutil.rmtree(cache)
    return False


def prepare_browser(root, release, tag, platform_id):
    if reuse_browser(release):
        return
    runtime_dir = release / "runtime/ms-playwright"
    archive = get_asset(root, tag, f"browser-{platform_id}.tar.gz")
    extract_tar(archive, runtime_dir)


def link_projects(projects, release, env):
    for project in projects:
        link = project / ".venv"
        if WINDOWS:
            run("cmd.exe", "/d", "/c", "mklink", "/J", link, release / ".venv", cwd=release, env=env, label="链接 "+project.name)
        else:
            link.symlink_to(release / ".venv", target_is_directory=True)


def configure(root, release, base_python, node_pair):
    node, npx = node_pair
    (release / "runtime-paths.json").write_text(json.dumps({"node": str(node), "npx": str(npx)}), encoding="utf-8")
    _, python, env = runtime(root, release)
    offline = release / "offline"
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
               npm_config_offline="true", npm_config_audit="false", npm_config_fund="false",
               npm_config_manage_package_manager_versions="false", COREPACK_ENABLE_NETWORK="0", CI="true")
    run(base_python, "-I", "-m", "venv", release / ".venv", cwd=release, env=env, label="准备项目 Python 环境")
    pip = [python, "-I", "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
           "--no-index", "--find-links", offline / "wheels"]
    projects = sorted(p.parent for p in (release / "packages").glob("*/pyproject.toml"))
    run(*pip, "hatchling", "editables", "setuptools", "wheel", cwd=release, env=env, label="安装离线构建工具")
    run(*pip, "--no-build-isolation", "qrcode[pil]", "websockets>=15,<17",
        *(arg for p in projects for arg in ("-e", p)), cwd=release, env=env, label="安装并链接 Python 组件")
    run(python, "-I", "-m", "pip", "check", cwd=release, env=env, label="核对 Python 依赖")
    link_projects(projects, release, env)
    portable_paths(release, python)
    manager = json.loads((release / "package.json").read_text())["packageManager"].split("@")[1].split("+")[0]
    pnpm = shutil.which("pnpm.cmd" if WINDOWS else "pnpm")
    if pnpm and check_output(pnpm, "--version", env=env) == manager:
        command = [pnpm]
        print(f"    ✓ 复用本机 pnpm {manager}", flush=True)
    else:
        command = [node, offline / "pnpm/bin/pnpm.cjs"]
        print(f"    ✓ 使用随包 pnpm {manager}", flush=True)
    run(*command, "install", "--offline", "--ignore-scripts", "--frozen-lockfile", "--store-dir", offline / "store",
        cwd=release, env=env, label="从本地依赖库配置工作台")
    dsh = (release / "config/dsh-version").read_text().strip()
    run(node, npx, "--offline", "-y", f"@deepseek-ai/dsh@{dsh}", "--version", cwd=release, env=env, label="检查 DSH")
    browser_env = {**env, "PYTHONPATH": str(release / "runtime/ms-playwright/python")}
    try:
        run(python, "-s", "-c", BROWSER_CHECK, cwd=release, env=browser_env, label="启动 Chromium 自检")
    except RuntimeError:
        libs = release / "runtime/ms-playwright/browser-libs"
        if not sys.platform.startswith("linux") or not libs.is_dir():
            raise
        browser_env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, [str(libs), env.get("LD_LIBRARY_PATH")]))
        run(python, "-s", "-c", BROWSER_CHECK, cwd=release, env=browser_env, label="使用随包 Linux 浏览器动态库复查")
        (libs.parent / "use-private-libs").touch()
    if (release / "scripts/user_archive.py").is_file():
        run(python, "scripts/user_archive.py", "--data", root / "data", "init", cwd=release, env=env, label="初始化共享用户档案")


def activate(root, release):
    stage(6, "启动服务，检查工作台并注册 chives")
    ready = root / "ready"
    previous = ready.read_text().strip() if ready.is_file() else ""
    try:
        (root / "data/dsh").mkdir(parents=True, exist_ok=True)
        control(root, release, "restart")
        _, python, _ = runtime(root, release)
        subprocess.run([python, release / "scripts/chives_cli.py", "release", "--register"], check=True)
    except BaseException:
        # An upgrade may have stopped a working version. Use its own supervisor to restore it.
        if previous and Path(previous).name == previous and previous != release.name:
            old = root / "releases" / previous
            old_py = old / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")
            if old_py.is_file():
                stop_code = "import runpy,sys,pathlib; r,p=map(pathlib.Path,sys.argv[1:]); runpy.run_path(str(p/'install.py'))['control'](r,p,'restart')"
                subprocess.run([old_py, "-c", stop_code, root, old], check=True)
        raise
    print("    ✓ [######] 100%  Chives 已启动 · http://127.0.0.1:8888/\n    新终端输入 chives 选择 Bot，chives web 打开网页，chives stop 关闭服务。", flush=True)


def install(root, tag, platform_id):
    if (not re.fullmatch(r"installer-\d+(?:\.\d+)+", tag) or
            not re.fullmatch(r"(?:linux|windows|macos)-(?:x64|arm64)", platform_id)):
        raise RuntimeError("发行版或平台名称无效")
    global LOG
    (root / "logs").mkdir(parents=True, exist_ok=True)
    LOG = root / "logs/install.log"
    (root / "releases").mkdir(exist_ok=True)
    release = root / "releases" / f"{tag}-{platform_id}"
    if (root / ".git").exists() or (root / "package.json").exists():
        raise RuntimeError("安装目录已有源码检出")
    lock = root / ".installing"
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError(f"已有安装正在运行。如上次被强制终止，请确认进程已退出再移走 {lock}") from None
    try:
        if (release / ".installed").is_file():
            _, python, _ = runtime(root, release)
            if not python.is_file() or not check_output(python, "-V"):
                raise RuntimeError(f"现有版本的 Python 无法启动，请检查 {release}")
            print("    ✓ 复用已验证的发行版")
            stage(4, "已复用本机解包结果")
            print("    ✓ 本版本已经安装")
            stage(5, "检查已有环境")
            node, _, _ = runtime(root, release)
            if not check_output(node, "-v"):
                raise RuntimeError(f"现有版本的 Node.js 无法启动，请检查 {node}")
            print("    ✓ 复用已配置的运行环境")
        else:
            with tempfile.TemporaryDirectory(dir=root) as tmp:
                work = Path(tmp)
                node_pair = find_node(platform_id)
                node_archive = None if node_pair else get_asset(root, tag, f"node-{platform_id}.tar.gz")
                payload = get_asset(root, tag, f"chives-{platform_id}.zip")
                print("    ✓ 平台文件已校验", flush=True)
                stage(4, "验证安装码并解开 Chives")
                staging = work / "app"
                staging.mkdir()
                unlock(payload, work, staging)
                if release.exists():
                    raise RuntimeError(f"已有未完成的同名目录，请先移走 {release} 再重试")
                staging.rename(release)
                try:
                    if node_archive:
                        extract_tar(node_archive, release)
                        node_pair = (release / "tools/node" / ("node.exe" if WINDOWS else "node"),
                                     release / "tools/npm/bin/npx-cli.js")
                    base_python = Path(sys.executable)
                    bundled = Path(__file__).resolve().parent / "python"
                    if bundled.is_dir() and base_python.resolve().is_relative_to(bundled.resolve()):
                        shutil.copytree(bundled, release / "python", symlinks=not WINDOWS)
                        base_python = release / "python" / ("python.exe" if WINDOWS else "bin/python3")
                    shutil.copyfile(__file__, release / "install.py")
                    print("    ✓ 发行包已展开", flush=True)
                    stage(5, "配置依赖并检查浏览器")
                    prepare_browser(root, release, tag, platform_id)
                    configure(root, release, base_python, node_pair)
                    (release / ".installed").touch()
                except BaseException:
                    shutil.rmtree(release)
                    raise
        if os.environ.get("CHIVES_INSTALL_BUILD_ONLY") == "1":
            print("    ✓ 环境检查通过（5/6）；本次仅验收安装包。")
            return
        activate(root, release)
    finally:
        lock.rmdir()


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3:
            supervise(Path(sys.argv[1]), Path(sys.argv[2]))
        elif len(sys.argv) == 5 and sys.argv[1] == "install":
            install(Path(sys.argv[2]).resolve(), sys.argv[3], sys.argv[4])
        else:
            sys.exit("请使用 GitHub 安装入口。")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
        sys.exit(f"安装未完成 · {CURRENT}\n{exc}" + (f"\n日志 {LOG}" if LOG else ""))
