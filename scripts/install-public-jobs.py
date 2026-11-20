"""Install the Mac workbench and public entry LaunchAgents."""
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
directory = Path.home() / "Library/LaunchAgents"
domain = f"gui/{os.getuid()}"
python = str(Path.home() / ".agents/venvs/chives/bin/python")
node = "/opt/homebrew/bin/node"
jobs = {
    "local.chives.workbench": (["/bin/bash", str(root / "scripts/serve-chives.sh")], dict(KeepAlive=True)),
    "local.chives.public-entry": ([node, str(root / "scripts/public-gateway.mjs")], dict(KeepAlive=True)),
    "local.chives.workbench-watchdog": ([python, str(root / "scripts/watch-public-workbench.py")], dict(StartInterval=30)),
    "local.chives.public-build": ([python, str(root / "scripts/refresh-public-build.py")], dict(StartInterval=30)),
    "local.chives.market-news": ([python, str(root / "scripts/update-market-news.py")], dict(StartInterval=1800)),
    "local.chives.public-market": ([python, str(root / "scripts/update-csi300.py")], dict(
        StartCalendarInterval=[dict(Hour=16, Minute=30), dict(Hour=20, Minute=30)])),
}
for label, (command, schedule) in jobs.items():
    file = directory / (label + ".plist")
    log = str(root / "runtime" / (label + ".log"))
    content = plistlib.dumps(dict(Label=label, ProgramArguments=command,
        WorkingDirectory=str(root), RunAtLoad=True, **schedule,
        ThrottleInterval=15, StandardOutPath=log, StandardErrorPath=log))
    if file.exists() and file.read_bytes() != content:
        raise SystemExit(f"Review existing job before replacing {file}")
    if not file.exists():
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temp:
            temp.write(content)
        os.replace(temp.name, file)
    if subprocess.run(["launchctl", "print", domain + "/" + label], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        subprocess.run(["launchctl", "bootstrap", domain, str(file)], check=True)
