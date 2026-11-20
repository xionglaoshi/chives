"""Install a version of Chives into an isolated, user-owned directory."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import tomllib
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


MIRROR = None
BATCH_DIR = None
LAST_ASSET = ""
CURRENT = "准备安装"
LOG = None

def show_progress(message, final=False):
    if sys.stdout.isatty():
        width = min(100, max(1,shutil.get_terminal_size().columns-1))
        print("\r" + message[:width].ljust(width),end="\n" if final else "",flush=True)
    else:
        print(message,flush=True)


def download(url, destination, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        opener = HTTP.open if url.startswith("http://127.0.0.1:") else urllib.request.urlopen
        print(f"    正在取得 {destination.name}…",flush=True)
        with opener(request, timeout=540) as response, destination.open("wb") as handle:
            total = int(response.headers.get("Content-Length", 0))
            done = 0
            last = 0
            while chunk := response.read(256*1024):
                handle.write(chunk)
                done += len(chunk)
                if time.monotonic()-last >= 2 or done == total:
                    progress = f" · {100*done//total}%" if total else ""
                    filled = min(16,16*done//total) if total else 0
                    bar = "[" + "#"*filled + "-"*(16-filled) + "] " if total else ""
                    show_progress(f"    {bar}{done/1048576:.1f} MiB{progress}",done==total)
                    last = time.monotonic()
            if total and done != total:
                raise RuntimeError(f"{destination.name} 下载不完整")
            return response.headers
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and headers and "If-None-Match" in headers:
            return None
        raise RuntimeError(exc.read(2048).decode("utf-8", errors="replace")) from None


class RegistryServer(ThreadingHTTPServer):
    request_queue_size = 128


class AssetBridge(BaseHTTPRequestHandler):
    """Package managers use an ephemeral loopback registry; only this process holds the code."""
    def log_message(self, *unused):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if (self.headers.get('Host') != self.server.address or self.headers.get('Origin')
                or not self.path.startswith(('/npm/', '/pypi/', '/browser/', '/node/', '/apt/'))):
            return self.send_error(403)
        global LAST_ASSET
        try:
            LAST_ASSET = "正在取得 · " + urllib.parse.unquote(self.path).rstrip("/").rsplit("/",1)[-1][:70]
            if BATCH_DIR and self.path.startswith('/npm/') and '/-/' in self.path:
                name = urllib.parse.unquote(self.path.lstrip('/'))
                file = BATCH_DIR/hashlib.sha256(name.encode()).hexdigest()
                if file.exists():
                    self.send_response(200)
                    self.send_header('Content-Length',str(file.stat().st_size))
                    self.end_headers()
                    if self.command == 'GET':
                        with file.open('rb') as handle:
                            shutil.copyfileobj(handle,self.wfile)
                    return
            req = urllib.request.Request(BASE+'/assets'+self.path, method=self.command,
                                         headers={'Authorization': self.server.authorization})
            if self.path.startswith('/pypi/packages/') and self.headers.get('Range'):
                req.add_header("Range",self.headers['Range'])
            with urllib.request.urlopen(req, timeout=540) as res:
                LAST_ASSET = ("缓存命中" if res.headers.get("X-Chives-Cache")=="hit" else "服务器已缓存") + " · " + urllib.parse.unquote(self.path).rstrip("/").rsplit("/",1)[-1][:70]
                data = None
                if self.command == 'GET' and self.path.startswith('/npm/') and '/-/' not in self.path:
                    doc = json.load(res)
                    for v in doc.get('versions', {}).values():
                        dist = v.get('dist', {})
                        if 'tarball' in dist:
                            path = urllib.parse.urlsplit(dist['tarball']).path
                            dist['tarball'] = 'http://'+self.server.address+'/npm'+path
                    data = json.dumps(doc, separators=(',', ':')).encode()
                self.send_response(res.status)
                for key in ('Accept-Ranges','Content-Range'):
                    if key in res.headers:
                        self.send_header(key,res.headers[key])
                self.send_header('Content-Type', res.headers['Content-Type'])
                self.send_header('Content-Length', str(len(data)) if data is not None else res.headers['Content-Length'])
                self.end_headers()
                if self.command != 'HEAD':
                    if data is None:
                        shutil.copyfileobj(res,self.wfile,256*1024)
                    else:
                        self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            self.send_error(exc.code)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError):
            self.send_error(502)

@contextmanager
def asset_session(code, root):
    global MIRROR
    # Stable registry URLs let uv and npm reuse their per-origin caches across installs.
    port = 49152 + int(hashlib.sha256(str(root).encode()).hexdigest()[:4],16) % 16000
    try:
        listener = RegistryServer(('127.0.0.1',port),AssetBridge)
    except OSError:
        listener = RegistryServer(('127.0.0.1',0),AssetBridge)
    with listener as svc:
        svc.address = '127.0.0.1:'+str(svc.server_port)
        svc.authorization = 'Bearer '+code.strip()
        MIRROR = 'http://'+svc.address
        worker = threading.Thread(target=svc.serve_forever,daemon=True)
        worker.start()
        try:
            yield
        finally:
            svc.shutdown()
            worker.join()
            MIRROR = None

def step(number, label):
    global CURRENT
    CURRENT = label
    prefix = f'[{number}/6]'
    if sys.stdout.isatty() and os.name != 'nt' and 'NO_COLOR' not in os.environ:
        prefix = '\033[36;1m'+prefix+'\033[0m'
    print(f'\n  {prefix} {label}',flush=True)

def run(*args, cwd, env, label=None):
    global LAST_ASSET
    LAST_ASSET = ''
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
                    print(f'    {label} · 已用 {int(time.monotonic()-start_time)} 秒  {LAST_ASSET}',flush=True)
            if result:
                with LOG.open('rb') as details:
                    details.seek(max(0,details.seek(0,2)-4096))
                    lines = [ln.strip() for ln in details.read().decode('utf-8','replace').splitlines() if ln.strip()]
                    if lines:
                        print('    '+lines[-1][:240],file=sys.stderr)
                raise RuntimeError(f'{label}失败（退出码 {result}）。详细日志 {LOG}')
    print(f'    ✓ {label}',flush=True)

def system_deps(python, release, env):
    info = platform.freedesktop_os_release()
    distro, suite = info.get('ID',''), info.get('VERSION_CODENAME','')
    if distro not in ('ubuntu','debian') or not re.fullmatch('[a-z]+',suite):
        raise RuntimeError('Chromium 缺少系统库。此系统未配置受支持的 APT 缓存源。')
    arch = platform.machine().lower()
    repo = 'ubuntu-ports' if distro == 'ubuntu' and arch in ('arm64','aarch64') else distro
    key = f'/usr/share/keyrings/{distro}-archive-keyring.gpg'
    components = 'main universe' if distro == 'ubuntu' else 'main'
    print('    安装 Chromium 缺少的系统库，可能需要输入 sudo 密码。', flush=True)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        for name in ('lists/partial','archives/partial','empty'):
            (tmp/name).mkdir(parents=True)
        lines = []
        for pocket in ('','-updates','-security'):
            source = 'debian-security' if distro == 'debian' and pocket == '-security' else repo
            lines.append(f'deb [signed-by={key}] {MIRROR}/apt/{source} {suite}{pocket} {components}')
        (tmp/'sources.list').write_text('\n'.join(lines)+'\n')
        conf = tmp/'apt.conf'
        conf.write_text(f'Dir::Etc::sourcelist "{tmp}/sources.list";\nDir::Etc::sourceparts "{tmp}/empty";\n'
                        f'Dir::State::lists "{tmp}/lists";\nDir::Cache::archives "{tmp}/archives";\n')
        apt = ["/usr/bin/apt-get", "-o",f"Dir::Etc::sourcelist={tmp}/sources.list",
               "-o",f"Dir::Etc::sourceparts={tmp}/empty","-o",f"Dir::State::lists={tmp}/lists",
               "-o",f"Dir::Cache::archives={tmp}/archives"]
        if os.geteuid() != 0:
            apt = ["sudo", *apt]
        subprocess.run([*apt,"update"], check=True)
        probe = subprocess.run([str(python),"-m","playwright","install-deps","--dry-run","chromium"],
                               cwd=release,env=dict(env,APT_CONFIG=str(conf)),text=True,capture_output=True)
        packages = re.findall(r"^  ([a-z0-9][a-z0-9+.-]+)$",probe.stdout,re.M)
        if not packages:
            raise RuntimeError(f"无法确定 Chromium 缺少的系统库，请检查浏览器日志 {LOG}")
        subprocess.run([*apt,"install","-y","--no-install-recommends",*packages],check=True)


def runtime(root, release):
    tools = root / "tools"
    uv = Path(os.environ.get("CHIVES_UV", tools / ("uv.exe" if WINDOWS else "uv")))
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
    env.pop("CHIVES_INSTALL_CODE", None)
    if MIRROR:
        env.update({"UV_DEFAULT_INDEX":MIRROR+"/pypi/simple/", "UV_INDEX_URL":MIRROR+"/pypi/simple/",
                    "npm_config_registry":MIRROR+"/npm/", "PLAYWRIGHT_DOWNLOAD_HOST":MIRROR+"/browser",
                    "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST":MIRROR+"/browser", "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT":"540000",
                    "UV_HTTP_TIMEOUT":"540","UV_NO_CONFIG":"1","npm_config_audit":"false","npm_config_fund":"false",
                    "NO_PROXY":"127.0.0.1,localhost","no_proxy":"127.0.0.1,localhost"})
        for key in ("UV_EXTRA_INDEX_URL","UV_INDEX","PIP_EXTRA_INDEX_URL"):
            env.pop(key,None)
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
        prefix = f"{MIRROR}/node/v{NODE_VERSION}"
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


def fetch_batches(ref, auth, folder):
    global BATCH_DIR
    BATCH_DIR = folder/"npm-batches"
    BATCH_DIR.mkdir()
    system = {"Windows":"win32","Linux":"linux","Darwin":"darwin"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in ("aarch64","arm64") else "x64"
    index,count = 0,1
    while index < count:
        archive = folder/f"依赖批次-{index+1}.tar"
        headers = download(f"{BASE}/batch/{ref}/{system}/{arch}/{index}",archive,auth)
        count = int(headers["X-Chives-Batches"])
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if not member.isfile() or not re.fullmatch("[0-9a-f]{64}",member.name):
                    raise RuntimeError("无效的依赖分批包")
                with (BATCH_DIR/member.name).open("wb") as out:
                    shutil.copyfileobj(bundle.extractfile(member),out)
        archive.unlink()
        index += 1
        print(f"    前端依赖批次 {index}/{count} 已就绪",flush=True)


def prepare(root, release, ref, auth, temp):
    uv, node, npm, npx, python, node_name, env = runtime(root, release)
    step(3, "准备 Node.js、DSH 和 Python 依赖")
    if node.is_file():
        print(f"    已复用 {node_name}",flush=True)
    prepare_node(node, node_name)
    version = (release / "config/dsh-version").read_text().strip()
    run(node, npx, "-y", f"@deepseek-ai/dsh@{version}", "--version", cwd=release, env=env, label="安装并检查 DSH")
    run(uv, "venv", "--python", sys.executable, release / ".venv", cwd=release, env=env, label="创建 Python 环境")
    editable = [arg for p in sorted((release / "packages").glob("*/pyproject.toml")) for arg in ("-e", p.parent)]
    run(uv, "pip", "install", "--python", python, "--constraint",release/"chives-constraints.txt","qrcode[pil]", "websockets>=15,<17", *editable, cwd=release, env=env, label="安装 Python 依赖")
    run(uv, "pip", "check", "--python", python, cwd=release, env=env, label="检查 Python 依赖")
    for manifest in (release / "packages").glob("*/pyproject.toml"):
        link = manifest.parent / ".venv"
        if WINDOWS:
            run(os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", link, release / ".venv", cwd=release, env=env, label="创建 Python 环境")
        else:
            link.symlink_to(release / ".venv", target_is_directory=True)
    portable_paths(release, python)
    step(4, "安装并检查 Chromium 浏览器")
    pw_env = {**env, "PYTHONPATH": str(release / "runtime/ms-playwright/python")}
    run(uv, "pip", "install", "--python", python, "--target", pw_env["PYTHONPATH"],
        "playwright==1.65.2", cwd=release, env=env, label="安装 Playwright")
    run(python, "-m", "playwright", "install", "chromium", cwd=release, env=pw_env, label="下载 Chromium")
    browser_check = [python, "-c", "from playwright.sync_api import sync_playwright\nwith sync_playwright() as p:\n b=p.chromium.launch(); print(b.version); b.close()"]
    if sys.platform.startswith("linux"):
        try:
            run(*browser_check, cwd=release, env=pw_env)
        except RuntimeError:
            system_deps(python, release, pw_env)
            run(*browser_check, cwd=release, env=pw_env)
    else:
        run(*browser_check, cwd=release, env=pw_env)
    step(5, "安装前端依赖并构建 Chives")
    fetch_batches(ref,auth,temp)
    manager = json.loads((release/"package.json").read_text())["packageManager"]
    if not re.fullmatch(r"pnpm@\d+\.\d+\.\d+(?:\+sha(?:256|512)\.[a-f0-9]+)?", manager):
        raise RuntimeError("package.json 中缺少可验证的 pnpm 版本")
    pnpm = [node, npx, "-y", manager.split("+")[0]]
    run(*pnpm, "install", "--frozen-lockfile", "--store-dir", root / "cache/pnpm", cwd=release, env=env, label="安装前端依赖")
    run(*pnpm, "build", cwd=release, env=env, label="构建 Chives")


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
    global LOG
    LOG = root / "logs/install.log"
    step(2, "验证安装码，检查最新版 Chives 和依赖")
    try:
        code = os.environ.get("CHIVES_INSTALL_CODE") or getpass.getpass("Chives 安装码: ")
        with asset_session(code, root), tempfile.TemporaryDirectory(dir=root) as temp:
            archives = root / "cache/source"
            archives.mkdir(parents=True,exist_ok=True)
            marker = archives/"current"
            previous = marker.read_text().strip() if marker.exists() else ""
            auth = {"Authorization":"Bearer "+code.strip()}
            if re.fullmatch(r"[a-f0-9]{40}",previous) and (archives/(previous+".tar.gz")).is_file():
                auth["If-None-Match"] = '"'+previous+'"'
            incoming = Path(temp)/"chives.tar.gz"
            headers = download(BASE+"/package", incoming, auth)
            sha = previous if headers is None else headers.get("X-Chives-Commit", "")
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise RuntimeError("安装源缺少有效的 Git 提交编号")
            archive = archives/(sha+".tar.gz")
            if headers is None:
                print(f"    已复用 Chives {sha[:12]} 源码",flush=True)
            else:
                incoming.replace(archive)
                pending = archives/"current.new"
                pending.write_text(sha)
                pending.replace(marker)
            source = Path(temp) / "source"
            source.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(source, filter="data")
            # Resolve unpinned runtime requirements before deciding to reuse an installed release.
            requirements = set(["qrcode[pil]", "websockets>=15,<17"])
            local_names = set()
            for manifest in (source / "packages").glob("*/pyproject.toml"):
                project = tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]
                local_names.add(re.sub(r"[-_.]+","-",project["name"].lower()))
                requirements.update(project.get("dependencies", []))
            requirements = {r for r in requirements if re.sub(r"[-_.]+","-",re.match(r"[a-zA-Z0-9_.-]+",r)[0].lower()) not in local_names}
            inputs = Path(temp)/"requirements.in"
            inputs.write_text("\n".join(sorted(requirements))+"\n",encoding="utf-8")
            lockfile = source/"chives-constraints.txt"
            uv, *_, env = runtime(root,source)
            run(uv,"pip","compile","--python",sys.executable,"--refresh","--only-binary",":all:","--no-header","--no-annotate",
                "--output-file",lockfile,inputs,cwd=source,env=env,label="检查 Python 依赖版本")
            revision = hashlib.sha256(Path(__file__).read_bytes() + lockfile.read_bytes() +
                                      sys.version.encode()+uv.name.encode()).hexdigest()[:12]
            release = releases / f"{sha[:12]}-{revision}"
            if not (release / ".installed").exists():
                if release.exists():
                    raise RuntimeError(f"上次安装尚未完成，请先移走 {release}")
                source.rename(release)
                try:
                    prepare(root, release, sha, {"Authorization":auth["Authorization"]}, Path(temp))
                except BaseException:
                    failed = releases / f"failed-{sha[:12]}-{time.time_ns()}"
                    release.rename(failed)
                    print(f"失败现场保存在 {failed}", file=sys.stderr)
                    raise
                (release / ".installed").touch()
            else:
                print("  [3-5/6] 已复用本机相同版本的运行环境、浏览器和构建产物",flush=True)
            shutil.copyfile(__file__, release / "install.py")
        if os.environ.get("CHIVES_INSTALL_BUILD_ONLY") == "1":
            print(f"Chives {sha[:12]} 依赖、浏览器及构建检查通过，未启动服务。")
            return
        step(6, "启动并检查本地服务")
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
        sys.exit(f"安装失败 · {CURRENT}\n{exc}" + (f"\n日志 {LOG}" if LOG else ""))
