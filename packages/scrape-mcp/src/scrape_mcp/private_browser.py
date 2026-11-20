"""Resolve the Playwright Python package, driver and browser from this Chives checkout."""
import importlib
import os
from pathlib import Path
import sys

RUNTIME = Path(__file__).resolve().parents[4] / "runtime/ms-playwright"


def _require(path: Path, directory: Path) -> Path:
    actual = path.resolve(strict=True)
    if not actual.is_relative_to(directory) or not actual.is_file():
        raise RuntimeError(f"Asset is outside the Chives browser runtime: {path.name}")
    return actual


def browser_api():
    python_dir = RUNTIME / "python"
    _require(python_dir / "playwright/__init__.py", python_dir)
    node = _require(python_dir / "playwright/driver/node", python_dir)
    _require(python_dir / "playwright/driver/package/cli.js", python_dir)
    for name, module in tuple(sys.modules.items()):
        if name == "playwright" or name.startswith("playwright."):
            _require(Path(module.__file__), python_dir)
    directory = str(python_dir)
    if sys.path[:1] != [directory]:
        sys.path.insert(0, directory)
    os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(node)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(RUNTIME / "browsers")
    api = importlib.import_module("playwright.sync_api")
    _require(Path(api.__file__), python_dir)
    return api


def chromium_binary(browser_type) -> str:
    path = _require(Path(browser_type.executable_path), RUNTIME / "browsers")
    if not os.access(path, os.X_OK):
        raise RuntimeError("Chives Chromium is not executable")
    return str(path)
