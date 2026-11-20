"""Immutable public research inputs and dated results, separate from personal Bot state."""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile


def library():
    return Path(
        os.environ.get(
            "CHIVES_RESEARCH_LIBRARY",
            Path(__file__).resolve().parents[4] / "data/equity-research",
        )
    )


def stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def save_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as out:
        out.write(content)
    Path(out.name).replace(path)


def save(path, value):
    save_bytes(
        path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode()
    )


def snapshot(value):
    blob = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True
    ).encode()
    key = hashlib.sha256(blob).hexdigest()
    save_bytes(library() / "snapshots" / f"{key}.json", blob)
    return key


def digest_id(key):
    if not re.fullmatch("[a-f0-9]{64}", key):
        raise ValueError("请输入完整的 SHA-256 证据编号")
    return key
