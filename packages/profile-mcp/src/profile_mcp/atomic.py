"""Atomic UTF-8 file writes (same-directory temp file + os.replace)."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

DEFAULT_FILE_MODE = 0o600


def atomic_write_text(
    path: Path,
    text: str,
    *,
    default_mode: int = DEFAULT_FILE_MODE,
    preserve_mode: bool = True,
) -> None:
    """Write text atomically; keep the existing mode unless preserve_mode is False."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    mode = default_mode
    if preserve_mode:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            pass
    fd, tmp_name = tempfile.mkstemp(prefix=".profile-tmp-", dir=parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
