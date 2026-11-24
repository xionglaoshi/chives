"""Install a clean source archive and verify the resulting backend on a separate port."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing

import install as installer

REPO = Path(__file__).resolve().parents[2]


def check(work, target):
    archive = work / "source.tar.gz"
    root = work / ".chives"
    root.mkdir()
    with archive.open("wb") as stream:
        subprocess.run(["git", "archive", "--format=tar.gz", "--prefix=chives-main/", "HEAD"],
                       cwd=REPO, stdout=stream, check=True)
    subprocess.run([sys.executable, "-I", "-u", str(REPO / "deploy/installer/source.py"),
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

    log = work / "server.log"
    with log.open("w", encoding="utf-8") as output:
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
            state = read("/api/settings/desk/initialization")
            for key in ("model", "portrait", "profile", "holdings", "watchlist", "weixin", "watch", "briefing"):
                assert state[key] is False, key
            assert read("/api/settings/desk/holdings")["positions"] == []
            assert read("/api/settings/desk/watchlist") == []
            with closing(sqlite3.connect(root / "user-data/chives.sqlite")) as db:
                assert db.execute("SELECT count(*) FROM messages").fetchone() == (0,)
            assert not (root / "data").exists()
            print("Installed backend is healthy; all eight onboarding steps and personal records are empty.")
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


if __name__ == "__main__":
    runtime = REPO / "runtime"
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime, prefix="check-source-") as temporary:
        check(Path(temporary), sys.argv[1])
