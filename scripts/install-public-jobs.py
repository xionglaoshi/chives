"""Install the Mac workbench LaunchAgent for the user running this script."""
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
directory = Path.home() / "Library/LaunchAgents"
domain = f"gui/{os.getuid()}"
jobs = {
    "local.chives.workbench": ["/bin/bash", str(root / "scripts/serve-chives.sh")],
}
for label, command in jobs.items():
    file = directory / (label + ".plist")
    log = str(root / "runtime" / (label + ".log"))
    content = plistlib.dumps(dict(Label=label, ProgramArguments=command,
        WorkingDirectory=str(root), RunAtLoad=True, KeepAlive=True,
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
