"""Install a clean source archive and verify the resulting backend on a separate port."""
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing, contextmanager

import install as installer

REPO = Path(__file__).resolve().parents[2]


def check(work, target):
    archive = work / "source.tar.gz"
    root = work / ".chives"
    root.mkdir()
    with archive.open("wb") as stream:
        subprocess.run(["git", "archive", "--format=tar.gz", "--prefix=chives-main/", "HEAD"],
                       cwd=REPO, stdout=stream, check=True)
    subprocess.run([sys.executable, "-X", "utf8", "-I", "-u", str(REPO / "deploy/installer/source.py"),
                    str(root), str(archive), target],
                   env={**os.environ, "CHIVES_INSTALL_BUILD_ONLY": "1"}, check=True)
    release, = (root / "releases").iterdir()
    assert (release / ".installed").is_file()
    node, _, env = installer.runtime(root, release)
    assert Path(env["CHIVES_DATA_DIR"]) == root / "user-data"
    assert Path(env["CHIVES_WORKSPACE_DIR"]) == root / "workspace"
    assert Path(env["CN_DAILY_STORE_DB"]).is_relative_to(root / "public-data/mechanical-cache")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env["CHIVES_PORT"] = str(port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def read(path):
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         headers={"X-Chives-Kernel-Manager": "local"})
        with opener.open(request, timeout=15) as response:
            return json.load(response)

    def check_browser():
        web = release / "apps/web"
        # Keep the app's normal Vite configuration and route to the isolated backend.
        config = (web / "vite.config.ts").read_text(encoding="utf-8")
        old = "const CHIVES_SERVER_PORT = 8880;"
        assert old in config
        isolated = web / "vite.install-check.config.ts"
        isolated.write_text(config.replace(old, f"const CHIVES_SERVER_PORT = {port};"), encoding="utf-8")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            web_port = listener.getsockname()[1]
        web_url = f"http://127.0.0.1:{web_port}/"
        web_log = work / "web.log"
        with web_log.open("w", encoding="utf-8") as output:
            vite = subprocess.Popen(
                [str(node), "node_modules/vite/bin/vite.js", "--config", isolated.name,
                 "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
                cwd=web, env=env, stdout=output, stderr=output,
            )
            try:
                for _ in range(80):
                    if vite.poll() is not None:
                        raise RuntimeError("Installed frontend exited prematurely")
                    try:
                        with opener.open(web_url, timeout=2):
                            break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError("Installed frontend did not become healthy")
                browser_env = {**env, "PYTHONPATH": str(release / "runtime/ms-playwright/python")}
                subprocess.run(
                    [env["CALENDAR_PYTHON"], "-s", str(Path(__file__).with_name("check_initialization_browser.py")), web_url],
                    env=browser_env, check=True, timeout=90,
                )
            except BaseException:
                print(web_log.read_text(encoding="utf-8", errors="replace")[-3000:], file=sys.stderr)
                raise
            finally:
                if vite.poll() is None:
                    vite.kill()
                vite.wait()

    log = work / "server.log"
    @contextmanager
    def running_server():
        with log.open("a", encoding="utf-8") as output:
            process = subprocess.Popen([str(node), "dist/main.js"], cwd=release / "apps/server",
                                       env=env, stdout=output, stderr=output)
            try:
                for _ in range(40):
                    if process.poll() is not None:
                        raise RuntimeError("Installed server exited prematurely")
                    try:
                        read("/api/health")
                        break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError("Installed server did not become healthy")
                yield
            except BaseException:
                print(log.read_text(encoding="utf-8", errors="replace")[-3000:], file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    with running_server():
        initial_generation = read("/api/health")["browserState"]["generation"]
        state = read("/api/settings/desk/initialization")
        for key in ("model", "portrait", "profile", "holdings", "watchlist", "weixin", "watch", "briefing"):
            assert state[key] is False, key
        try:
            assert read("/api/settings/desk/holdings")["positions"] == []
        except OSError:
            portfolio_env = {key: env[key] for key in ("DSH_HOME", "DSH_FINANCE_PROFILE_DIR", "HOME", "PATH",
                                                       "SystemRoot", "PYTHONUTF8") if key in env}
            adapter = subprocess.run(
                [env["CALENDAR_PYTHON"], "-m", "portfolio_mcp.workbench"],
                cwd=release / "packages/portfolio-mcp", env=portfolio_env,
                input='{"action":"get"}', text=True, encoding="utf-8", capture_output=True, timeout=20,
            )
            print(f"Portfolio adapter exit {adapter.returncode}: {adapter.stderr}", file=sys.stderr)
            raise
        assert read("/api/settings/desk/watchlist") == []
        channels = read("/api/settings/desk/channels")
        weixin, = (channel for channel in channels if channel["id"] == "weixin")
        assert weixin["qr"] and not weixin["configured"] and not weixin["enabled"]
        with closing(sqlite3.connect(root / "user-data/chives.sqlite")) as db:
            assert db.execute("SELECT count(*) FROM messages").fetchone() == (0,)
        assert not (root / "data").exists()
        check_browser()
        print("Installed backend is healthy; all eight onboarding steps and personal records are empty.")

    workspace = root / "workspace" / "bots" / "operator"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "prior-report.md").write_text("prior user deliverable", encoding="utf-8")
    cache = root / "public-data" / "mechanical-cache" / "reset-check"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("public data", encoding="utf-8")
    shutil.rmtree(root / "user-data")
    with running_server():
        browser_state = read("/api/health")["browserState"]
        assert browser_state["generation"] != initial_generation
        assert browser_state["adoptLegacy"] is False
        state = read("/api/settings/desk/initialization")
        for key in ("model", "portrait", "profile", "holdings", "watchlist", "weixin", "watch", "briefing"):
            assert state[key] is False, key
        assert not (workspace / "prior-report.md").exists()
        recovered, = (root / "runtime").glob("user-reset-*/workspace/bots/operator/prior-report.md")
        assert recovered.read_text(encoding="utf-8") == "prior user deliverable"
        assert cache.read_text(encoding="utf-8") == "public data"
        print("Factory reset starts a new browser generation and empty workspace while preserving public cache.")


if __name__ == "__main__":
    # Vite denies paths under directories named runtime. Use the runner's own
    # temporary directory for the isolated installation; its state remains in .chives.
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP"), prefix="chives-check-") as temporary:
        check(Path(temporary), sys.argv[1])
