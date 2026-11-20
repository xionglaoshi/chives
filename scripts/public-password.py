"""Set the public gateway password. Run on the server as root, then restart chives-entry.service."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile

directory = Path("/etc/chives-entry")
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
password = getpass.getpass("Public entry password: ")
if not password or password != getpass.getpass("Repeat password: "):
    raise SystemExit("Password is empty or does not match.")
salt = secrets.token_bytes(16)
digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
    json.dump({"salt": salt.hex(), "digest": digest.hex()}, stream)
os.replace(stream.name, directory / "entry.json")
