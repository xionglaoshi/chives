"""Install a GitHub source snapshot using the upstream projects' distributions."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
import zipfile

# The entrance runs with -I: import only the helper from the very same archive.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import install as core

NPM_REGISTRY = "https://registry.npmjs.org"
PYPI = "https://pypi.org/simple"
NPM_SHA256 = "9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0"  # npm 11.19.1
NODE_HASHES = {  # nodejs.org/dist/v26.9.0/SHASUMS256.txt
    "macos-arm64": "6f3de7ed853ee283b4bf24b6e426618f1d357401ce5815db1866eb85eb4b05d9",
    "macos-x64": "06b2e742ed9025dc84adc830243b3f731956eac9c321bccd0ede384209af02a8",
    "linux-arm64": "686d07ed3bc5d68d9f7bd4939b7e8849a87d0664ac19c8c5474474f44cc956db",
    "linux-x64": "c6ecd8efc1c1d395265891675319da7a7b3785c6be174bd78933cf4f057624d1",
    "windows-x64": "c8af870b5b3e9789a6cbdb30270e7c212e12d76a7afa7fc7f21b6b21cc22a71b",
}


def download(url, path, digest):
    proxy = os.environ.get("CHIVES_SETUP_PROXY")
    route = ["--noproxy", "localhost,127.0.0.1", "--proxy", proxy] if proxy else ["--noproxy", "*"]
    print(f"    下载 {path.name}", flush=True)
    command = ["curl.exe" if core.WINDOWS else "curl", "-q", *route, "--proto", "=https",
               "--proto-redir", "=https", "-fL", "--connect-timeout", "10", "--retry", "2",
               "--speed-limit", "1", "--speed-time", "90", "-o", str(path),
               "-w", "\\n    %{size_download} bytes · %{speed_download} B/s\\n", url]
    if subprocess.run(command).returncode:
        raise RuntimeError(f"{path.name} 下载失败")
    if core.file_hash(path) != digest:
        raise RuntimeError(f"{path.name} 与官方 SHA-256 不匹配")


@contextmanager
def package_proxy(work):
    """Offer a loopback HTTP CONNECT endpoint to tools that only accept HTTP(S) proxies."""
    proxy = os.environ.get("CHIVES_SETUP_PROXY", "")
    uri = urlsplit(proxy)
    if not uri.scheme.startswith("socks"):
        yield proxy
        return
    wheel = work / "PySocks-1.7.1-py3-none-any.whl"
    download("https://files.pythonhosted.org/packages/8d/59/b4572118e098ac8e46e399a1dd0f2d85403ce8bbaad9ec79373ed6badaf9/" + wheel.name,
             wheel, "2725bd0a9925919b9b51739eea5f9e2bae91e83288108a9ad338b2e3a4435ee5")
    sys.path.insert(0, str(wheel))
    import socks

    class Tunnel(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_CONNECT(self):
            peer = urlsplit("//" + self.path)
            if not peer.hostname or peer.port != 443:
                self.send_error(403)
                return
            try:
                upstream = socks.create_connection(
                    (peer.hostname, peer.port), timeout=25,
                    proxy_type=socks.SOCKS4 if uri.scheme.startswith("socks4") else socks.SOCKS5,
                    proxy_addr=uri.hostname, proxy_port=uri.port or 1080,
                    proxy_rdns=uri.scheme in {"socks4a", "socks5h"},
                    proxy_username=unquote(uri.username or "") or None, proxy_password=unquote(uri.password or "") or None)
            except OSError:
                self.send_error(502)
                return
            with upstream:
                upstream.settimeout(None)
                self.send_response_only(200)
                self.end_headers()
                while True:
                    readable, _, _ = select.select([self.connection, upstream], [], [], 120)
                    if not readable:
                        return
                    for source in readable:
                        block = source.recv(65536)
                        if not block:
                            return
                        (upstream if source is self.connection else self.connection).sendall(block)

    with ThreadingHTTPServer(("127.0.0.1", 0), Tunnel) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


def package_env(env, proxy):
    env = dict(env)
    bypass = ",".join(filter(None, [env.get("no_proxy") or env.get("NO_PROXY"), "localhost", "127.0.0.1", "::1"]))
    for key in ("http_proxy", "https_proxy", "all_proxy", "npm_config_https_proxy", "npm_config_proxy"):
        for spelling in (key, key.upper()):
            env.pop(spelling, None)
        if proxy:
            env[key] = proxy
            if not key.startswith("npm_"):
                env[key.upper()] = proxy
    env.update(no_proxy=bypass if proxy else "*", NO_PROXY=bypass if proxy else "*",
               npm_config_registry=NPM_REGISTRY, npm_config_audit="false", npm_config_fund="false",
               npm_config_offline="false", COREPACK_ENABLE_NETWORK="0", CI="true",
               PIP_CONFIG_FILE=os.devnull, PIP_INDEX_URL=PYPI, PIP_DISABLE_PIP_VERSION_CHECK="1",
               PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="120000")
    for key in ("PIP_NO_INDEX", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PLAYWRIGHT_DOWNLOAD_HOST",
                "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"):
        env.pop(key, None)
    return env


def run(args, cwd, env, label, *, interactive=False):
    print("    "+label, flush=True)
    # Let pip, pnpm and Playwright report their own progress without console buffering.
    if interactive:
        with open("/dev/tty", "rb") as tty:
            subprocess.run(args, cwd=cwd, env=env, stdin=tty, check=True)
    else:
        with core.LOG.open("ab") as log:
            log.write(("\n"+label+"\n").encode())
            with subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as child:
                while block := child.stdout.read1(8192):
                    log.write(block)
                    sys.stdout.buffer.write(block)
                    sys.stdout.buffer.flush()
                if child.wait():
                    raise RuntimeError(f"{label}失败，详见 {core.LOG}")
    print("    ✓ "+label, flush=True)


def npm_pair(node):
    base = node.parent if core.WINDOWS else node.parent.parent / "lib"
    dirs = [base / "node_modules/npm"]
    npm = shutil.which("npm.cmd" if core.WINDOWS else "npm")
    if npm:
        prefix = core.check_output(npm, "root", "-g")
        if prefix:
            dirs.append(Path(prefix) / "npm")
    for folder in dirs:
        entry = folder / "bin/npm-cli.js"
        npx = entry.with_name("npx-cli.js")
        if entry.is_file() and npx.is_file() and core.check_output(node, entry, "--version") and core.check_output(node, npx, "--version"):
            return entry, npx
    return None


def get_node(root, work, platform):
    system, arch = platform.split("-")
    name = f"node-v{core.NODE_VERSION}-" + {"macos":"darwin","linux":"linux","windows":"win"}[system] + "-" + arch
    dest = root / "tools" / name
    private = dest / ("node.exe" if core.WINDOWS else "bin/node")
    for candidate in (shutil.which("node"), private):
        if not candidate or not Path(candidate).is_file():
            continue
        node = Path(candidate).resolve()
        version = core.check_output(node, "-p", "process.versions.node+' '+process.arch")
        if re.fullmatch(r"26\.\d+\.\d+ "+arch, version):
            pair = npm_pair(node)
            if pair:
                print(f"    ✓ 复用 Node.js {version} 和 npm/npx", flush=True)
                return node, *pair
            # Repair a Node-only installation without replacing the host executable.
            print(f"    ✓ 复用 Node.js {version}，单独补齐 npm", flush=True)
            npm_dir = root / "tools/npm-11.19.1"
            if not npm_dir.exists():
                tar = work / "npm-11.19.1.tgz"
                download(NPM_REGISTRY+"/npm/-/"+tar.name, tar, NPM_SHA256)
                core.extract_tar(tar, work)
                (work / "package").rename(npm_dir)
            return node, npm_dir / "bin/npm-cli.js", npm_dir / "bin/npx-cli.js"
    archive = name + (".zip" if core.WINDOWS else ".tar.gz" if system=="macos" else ".tar.xz")
    file = work / archive
    download(f"https://nodejs.org/dist/v{core.NODE_VERSION}/{archive}", file, NODE_HASHES[platform])
    if core.WINDOWS:
        with zipfile.ZipFile(file) as bundle:
            bundle.extractall(work)
    else:
        core.extract_tar(file, work)
    (work / name).rename(dest)
    pair = npm_pair(private)
    if not pair:
        raise RuntimeError(f"Node.js 已解包，但 npm/npx 无法运行，请检查 {dest}")
    npm, npx = pair
    return private, npm, npx


def npm_install(node, npm, root, package, version, env):
    prefix = root / "tools" / (package.split("/")[-1].lstrip("@")+"-"+version)
    manifest = prefix / "node_modules" / package / "package.json"
    if manifest.is_file() and json.loads(manifest.read_text(encoding="utf-8"))["version"] == version:
        return manifest
    # Install into a new prefix, so a failed npm run cannot leave a reusable partial tree.
    (root / "tools").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root / "tools") as tmp:
        staging = Path(tmp) / "prefix"
        run([node, npm, "install", "--prefix", staging, "--no-save", "--no-package-lock",
             f"{package}@{version}"], root, env, "从 npm 安装 "+package+" "+version)
        if prefix.exists():
            raise RuntimeError(f"工具目录已存在，请检查 {prefix}")
        staging.rename(prefix)
    return manifest


def bin_entry(manifest, version, name):
    if not manifest.is_file():
        return None
    info = json.loads(manifest.read_text(encoding="utf-8"))
    if info.get("version") != version:
        return None
    entry = info.get("bin", {})
    relative = entry if isinstance(entry, str) else entry.get(name)
    if relative:
        path = manifest.parent / relative
        if path.is_file():
            return path.resolve()
    return None


def configure(root, release, node, npm, npx, proxy):
    config = {"node":str(node), "npx":str(npx), "npm_cache":str(root / "cache/npm")}
    paths = release / "runtime-paths.json"
    paths.write_text(json.dumps(config), encoding="utf-8")
    _, python, env = core.runtime(root, release)
    env = package_env(env, proxy)
    projects = sorted(p.parent for p in (release / "packages").glob("*/pyproject.toml"))
    run([sys.executable, "-I", "-m", "venv", release/".venv"], release, env, "创建专用 Python 环境")
    pip = [python, "-I", "-m", "pip", "install", "--index-url", PYPI]
    run([*pip, "qrcode[pil]", "websockets>=15,<17", *(x for p in projects for x in ("-e", p))],
        release, env, "从 PyPI 配置 Python 依赖")
    core.link_projects(projects, release, env)
    manager = json.loads((release / "package.json").read_text())["packageManager"].split("@")[1].split("+")[0]
    pnpm = shutil.which("pnpm.cmd" if core.WINDOWS else "pnpm")
    if pnpm and core.check_output(pnpm, "--version", env=env) == manager:
        command = [pnpm]
        print(f"    ✓ 复用 pnpm {manager}", flush=True)
    else:
        manifest = npm_install(node, npm, root, "pnpm", manager, env)
        entry = bin_entry(manifest, manager, "pnpm")
        if not entry:
            raise RuntimeError("pnpm 包缺少启动文件")
        command = [node, entry]
    run([*command, "install", "--frozen-lockfile", "--store-dir", root/"cache/pnpm"], release, env, "按锁文件安装工作台依赖")
    run([*command, "-r", "--filter", "./apps/*", "--filter", "./packages/acp-client", "--filter", "./packages/chives-mcp",
         "run", "build"], release, env, "构建工作台和服务")
    version = (release / "config/dsh-version").read_text().strip()
    prefix = core.check_output(node, npm, "root", "-g", env=env)
    dsh = bin_entry(Path(prefix)/"@deepseek-ai/dsh/package.json", version, "dsh") if prefix else None
    if not dsh:
        dsh = bin_entry(npm_install(node, npm, root, "@deepseek-ai/dsh", version, env), version, "dsh")
    if not dsh:
        raise RuntimeError("DSH 包缺少启动文件")
    config["dsh_js"] = str(dsh)
    paths.write_text(json.dumps(config), encoding="utf-8")
    # Local source files receive the paths for this machine only.
    core.portable_paths(release, python, direct_dsh=True)
    runtime_dir = release/"runtime/ms-playwright"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    run([*pip, "--target", runtime_dir/"python", "playwright==1.65.2"], release, env, "从 PyPI 配置 Playwright")
    browser_env = {**env, "PYTHONPATH":str(runtime_dir/"python")}
    previous = root / "ready"
    earlier = []
    if previous.is_file():
        old = previous.read_text().strip()
        if old and Path(old).name == old:
            earlier.append(root/"releases"/old/"runtime/ms-playwright/browsers")
    if not core.reuse_browser(release, earlier):
        run([python, "-m", "playwright", "install", "chromium"], release, browser_env, "从 Playwright 官方下载 Chromium")
    probe = subprocess.run([python, "-s", "-c", core.BROWSER_CHECK], env=browser_env, capture_output=True)
    if probe.returncode:
        details = probe.stderr.decode(errors="replace")
        if not sys.platform.startswith("linux") or not any(msg in details for msg in ("Missing libraries", "install-deps", "shared libraries")):
            raise RuntimeError("Chromium 启动失败："+details[-3000:])
        run([python, "-m", "playwright", "install-deps", "chromium"], release, browser_env, "通过系统包管理器补齐 Chromium 动态库",
            interactive=os.geteuid() != 0)
        run([python, "-s", "-c", core.BROWSER_CHECK], release, browser_env, "检查 Chromium 运行环境")
    if (release / "scripts/user_archive.py").is_file():
        run([python, "scripts/user_archive.py", "--data", env["CHIVES_DATA_DIR"], "init"], release, env, "初始化共享用户档案")


def install(root, archive, platform):
    if platform not in NODE_HASHES or (root/".git").exists() or (root/"package.json").exists():
        raise RuntimeError("平台或安装目录不适用")
    (root/"logs").mkdir(exist_ok=True)
    core.LOG = root/"logs/install.log"
    releases = root/"releases"
    releases.mkdir(exist_ok=True)
    work = archive.parent
    with tarfile.open(archive) as bundle:
        commit = bundle.pax_headers.get("comment", "")
        ident = commit if re.fullmatch("[a-f0-9]{40}", commit) else core.file_hash(archive)
        release = releases / ("main-"+ident[:16]+"-"+platform)
        existing = (release/".installed").is_file()
        if not existing:
            dest = work / "source"
            core.assert_blank_application_archive(bundle, prefix="chives-main")
            bundle.extractall(dest, filter="data")
            app = dest / "chives-main"
            for required in ("pnpm-lock.yaml", "package.json", "scripts/chives_cli.py"):
                if not (app / required).is_file():
                    raise RuntimeError("仓库快照缺少 "+required)
            node, npm, npx = get_node(root, work, platform)
            if release.exists():
                raise RuntimeError(f"上次安装未完成，请先移走 {release}")
            app.rename(release)
            try:
                print("    ✓ 源码及运行环境已就绪", flush=True)
                core.stage(5, "安装项目依赖并构建")
                with package_proxy(work) as proxy:
                    configure(root, release, node, npm, npx, proxy)
                shutil.copyfile(core.__file__, release/"install.py")
                (release/".installed").touch()
            except BaseException:
                shutil.rmtree(release)
                raise
        else:
            node, python, _ = core.runtime(root, release)
            if not core.check_output(node, "--version") or not core.check_output(python, "-V"):
                raise RuntimeError(f"原版运行环境已失效，请检查 {release}")
            print("    ✓ 复用本机运行环境", flush=True)
            core.stage(5, "复用同一仓库快照的已安装依赖和工作台")
            print("    ✓ 已构建", flush=True)
    if os.environ.get("CHIVES_INSTALL_BUILD_ONLY") == "1":
        print("    ✓ 源码安装环境检查通过（5/6）；本次仅验收安装。")
        return
    core.activate(root, release)


if __name__ == "__main__":
    try:
        install(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
        sys.exit(f"安装未完成 · {core.CURRENT}\n{exc}")
