#!/bin/bash
# The browser, Python bindings and Node driver are private to this installation.
set -euo pipefail
cd "$(dirname "$0")/.."
runtime="$PWD/runtime/ms-playwright"
python="$PWD/.venv/bin/python"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}"
export PLAYWRIGHT_BROWSERS_PATH="$runtime/browsers"
export PLAYWRIGHT_NODEJS_PATH="$runtime/python/playwright/driver/node"
mkdir -p "$runtime/python" "$PLAYWRIGHT_BROWSERS_PATH"
uv pip install --python "$python" --link-mode=copy --target "$runtime/python" 'playwright==1.65.2'
# uv's --target console script otherwise searches the interpreter's normal site-packages.
mkdir -p "$runtime/bin"
cat > "$runtime/python/bin/playwright" <<'ENTRY'
#!/bin/bash
set -euo pipefail
runtime="$(cd "$(dirname "$0")/../.." && pwd -P)"
test -f "$runtime/python/playwright/__main__.py"
export PYTHONPATH="$runtime/python"
export PLAYWRIGHT_NODEJS_PATH="$runtime/python/playwright/driver/node"
export PLAYWRIGHT_BROWSERS_PATH="$runtime/browsers"
cd "$runtime"
exec "$runtime/../../.venv/bin/python" -s -P -m playwright "$@"
ENTRY
chmod +x "$runtime/python/bin/playwright"
cat > "$runtime/bin/playwright" <<'ENTRY'
#!/bin/bash
exec "$(dirname "$0")/../python/bin/playwright" "$@"
ENTRY
chmod +x "$runtime/bin/playwright"
export PYTHONPATH="$runtime/python"
"$python" -m playwright install chromium
"$python" - <<'PY'
from pathlib import Path
import os
import playwright
from playwright.sync_api import sync_playwright
root = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]).parent
assert Path(playwright.__file__).resolve().is_relative_to(root)
assert Path(os.environ["PLAYWRIGHT_NODEJS_PATH"]).resolve().is_relative_to(root)
with sync_playwright() as driver:
    binary = Path(driver.chromium.executable_path).resolve(strict=True)
    assert binary.is_relative_to(root / "browsers")
    browser = driver.chromium.launch(executable_path=str(binary), chromium_sandbox=True)
    print(f"Chives Chromium {browser.version} · {binary}")
    browser.close()
PY
