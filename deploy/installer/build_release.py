"""Maintainer-side build. Publish only freshly staged, platform-specific release files."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WINDOWS = os.name == "nt"
SOURCE = ("apps", "bots", "config", "gateways", "overlays", "packages", "patches", "presets",
          "scripts", "skills", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml",
          "tsconfig.base.json", "LICENSE")


def run(*args, cwd=None, env=None):
    subprocess.run([str(x) for x in args], cwd=cwd, env=env, check=True)


def archive(path, entries):
    with tarfile.open(path, "w:gz", compresslevel=3) as out:
        for name, source in entries:
            out.add(source, arcname=name)


def archive_sources(app):
    # git archive never includes the build host's data, caches, tokens or working-tree changes.
    with tempfile.TemporaryFile() as file:
        rules = "docs/user-wiki-rules.md"
        exists = subprocess.run(["git", "-C", REPO, "cat-file", "-e", "HEAD:"+rules], stderr=subprocess.DEVNULL)
        paths = (*SOURCE, rules) if exists.returncode == 0 else SOURCE
        subprocess.run(["git", "-C", REPO, "archive", "HEAD", "--", *paths], stdout=file, check=True)
        file.seek(0)
        with tarfile.open(fileobj=file) as source:
            source.extractall(app, filter="data")


def collect_browser_libs(browsers, output):
    # Chromium on minimal Linux/WSL images often lacks NSS, ATK or GBM.
    output.mkdir()
    licences = output / "licenses"
    licences.mkdir()
    for exe in browsers.rglob("*"):
        if exe.name not in {"headless_shell", "chrome-headless-shell", "chrome", "ffmpeg-linux"} or not exe.is_file():
            continue
        linked = subprocess.run(["ldd", exe], text=True, capture_output=True)
        if linked.returncode:
            if any(msg in linked.stdout+linked.stderr for msg in ("not a dynamic executable", "statically linked")):
                continue
            linked.check_returncode()
        deps = linked.stdout
        if "not found" in deps:
            raise RuntimeError(f"构建机 Chromium 缺少系统库: {exe}")
        for name, path in re.findall(r"^\s*(\S+) => (/\S+)", deps, re.M):
            if re.match(r"^(?:lib(?:c|m|dl|pthread|rt|resolv|util|anl)\.so\.|ld-linux)", name):
                continue
            if (output / name).exists():
                continue
            shutil.copyfile(path, output / name)
            resolved = str(Path(path).resolve())
            for variant in (resolved, resolved.removeprefix("/usr"), path):
                pkg = subprocess.run(["dpkg-query", "-S", variant], text=True, capture_output=True)
                if pkg.returncode == 0:
                    owner = pkg.stdout.split(":", 1)[0]
                    license_file = Path("/usr/share/doc") / owner / "copyright"
                    if license_file.exists():
                        shutil.copyfile(license_file, licences / owner)
                        break
    if not any(output.glob("*.so*")):
        raise RuntimeError("未取得 Chromium 的 Linux 动态库")


def build(out, work, code):
    import pyzipper
    osname = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}[platform.system()]
    arch = {"aarch64":"arm64","arm64":"arm64","amd64":"x64","x86_64":"x64"}[platform.machine().lower()]
    target = f"{osname}-{arch}"
    app, boot = work / "app", work / "bootstrap"
    boot.mkdir()
    archive_sources(app)
    offline = app / "offline"
    offline.mkdir()
    browser = app / "runtime/ms-playwright"
    browser.mkdir(parents=True)
    env = os.environ.copy()
    env.pop("CHIVES_INSTALL_CODE", None)
    env.update(npm_config_cache=str(offline / "npm"), npm_config_fund="false", npm_config_audit="false",
               PLAYWRIGHT_BROWSERS_PATH=str(browser / "browsers"), PYTHONUTF8="1", CI="true")
    python = sys.executable
    pip = [python, "-m", "pip", "--disable-pip-version-check"]
    run(*pip, "install", "--target", boot / "vendor", "--no-compile", "pyzipper==0.3.6", env=env)
    shutil.copyfile(HERE / "install.py", boot / "install.py")
    archive(out / f"bootstrap-{target}.tar.gz", [(p.name, p) for p in boot.iterdir()])
    # This must be a relocatable, uv-managed python-build-standalone distribution.
    managed = Path(subprocess.check_output(["uv", "python", "find", "--managed-python", "3.12"], text=True).strip())
    prefix = Path(subprocess.check_output([managed, "-I", "-c", "import sys; print(sys.base_prefix)"], text=True).strip())
    archive(out / f"python-{target}.tar.gz", [("python", prefix)])
    node = Path(shutil.which("node")).resolve()
    npm = shutil.which("npm.cmd" if WINDOWS else "npm")
    npm_dir = (node.parent if WINDOWS else node.parent.parent / "lib") / "node_modules/npm"
    if not (npm_dir / "bin/npx-cli.js").is_file():
        npm_dir = Path(subprocess.check_output([npm, "root", "-g"], text=True).strip()) / "npm"
    from install import NODE_VERSION
    if subprocess.check_output([node, "-v"], text=True).strip() != "v"+NODE_VERSION:
        raise RuntimeError(f"构建机需要 Node.js {NODE_VERSION}")
    entries = [("tools/node/"+("node.exe" if WINDOWS else "node"), node), ("tools/npm", npm_dir)]
    node_license = node.parent / "LICENSE" if WINDOWS else node.parent.parent / "LICENSE"
    if not node_license.is_file():
        raise RuntimeError("Node.js 官方分发缺少 LICENSE")
    archive(out / f"node-{target}.tar.gz", [*entries, ("tools/node/LICENSE", node_license)])
    # Pristine npm cache contains just the pinned DSH tree. pnpm has its own offline store.
    npx = npm_dir / "bin/npx-cli.js"
    dsh = (app / "config/dsh-version").read_text().strip()
    run(node, npx, "-y", f"@deepseek-ai/dsh@{dsh}", "--version", cwd=app, env=env)
    manager = json.loads((app / "package.json").read_text())["packageManager"].split("+")[0]
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        run(npm, "pack", manager, "--pack-destination", tmp, cwd=tmp, env=dict(env,npm_config_cache=str(work/"builder-npm")))
        with tarfile.open(next(Path(tmp).glob("*.tgz"))) as bundle:
            bundle.extractall(tmp, filter="data")
        (Path(tmp) / "package").rename(offline / "pnpm")
    pnpm = [node, offline / "pnpm/bin/pnpm.cjs"]
    run(*pnpm, "install", "--frozen-lockfile", "--store-dir", offline / "store", cwd=app, env=env)
    run(*pnpm, "-r", "--filter", "./apps/*", "--filter", "./packages/acp-client", "--filter", "./packages/chives-mcp",
        "run", "build", cwd=app, env=env)
    for folder, dirs, _ in os.walk(app, topdown=True):
        if Path(folder).is_relative_to(offline):
            dirs.clear()
            continue
        if "node_modules" in dirs:
            dirs.remove("node_modules")
            shutil.rmtree(Path(folder) / "node_modules")
    # Keep only package responses. Generated launchers may contain absolute builder paths.
    for folder in (offline / "npm").iterdir():
        if folder.name != "_cacache":
            if folder.is_dir():
                shutil.rmtree(folder)
            else:
                folder.unlink()
    projects = [p.parent for p in sorted((app / "packages").glob("*/pyproject.toml"))]
    run(*pip, "wheel", "--wheel-dir", offline / "wheels", "hatchling", "editables", "setuptools", "wheel",
        "qrcode[pil]", "websockets>=15,<17", *projects, cwd=app, env=env)
    run(*pip, "install", "--no-compile", "--target", browser / "python", "playwright==1.65.2", env=env)
    pw = dict(env, PYTHONPATH=str(browser / "python"))
    run(python, "-m", "playwright", "install", *(["--with-deps"] if osname=="linux" else []), "chromium", env=pw)
    browser_files = [("browsers", browser / "browsers")]
    if osname=="linux":
        collect_browser_libs(browser / "browsers", work / "browser-libs")
        browser_files.append(("browser-libs", work / "browser-libs"))
    archive(out / f"browser-{target}.tar.gz", browser_files)
    shutil.rmtree(browser / "browsers")
    plain = work / "chives.tar.gz"
    archive(plain, [(p.name, p) for p in app.iterdir()])
    with pyzipper.AESZipFile(out / f"chives-{target}.zip", "w", compression=pyzipper.ZIP_STORED,
                             encryption=pyzipper.WZ_AES, allowZip64=True) as sealed:
        sealed.setpassword(code.encode())
        sealed.write(plain, "chives.tar.gz")
    for asset in sorted(out.glob(f"*-{target}.*")):
        if asset.suffix == ".sha256":
            continue
        size = asset.stat().st_size
        if size >= 2**31:
            raise RuntimeError(f"{asset.name} 超过 GitHub Release 单文件上限")
        with asset.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        asset.with_name(asset.name + ".sha256").write_text(f"{digest} {size}\n", encoding="ascii")


if __name__ == "__main__":
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    code = os.environ.pop("CHIVES_INSTALL_CODE", "")
    if not code:
        sys.exit("构建发行包需要 CHIVES_INSTALL_CODE")
    with tempfile.TemporaryDirectory() as tmp:
        build(out, Path(tmp), code)
