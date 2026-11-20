from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent


@pytest.fixture
def local_tmp() -> Path:
    """A temporary directory inside the package (never /tmp or another repo)."""
    path = Path(tempfile.mkdtemp(prefix="_tmp_", dir=TESTS_DIR))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
