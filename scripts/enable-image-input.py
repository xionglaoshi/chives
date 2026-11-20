#!/usr/bin/env python3
"""Declare `input: [text, image]` for the models that were verified to really read images.

Edits only the model entries of the `huosan` provider in ~/.dsh/profiles/desktop/cordis.patch.yml (or the file given as argv[1]),
after copying it to ~/.dsh/backup-image-input-<time>/ (mode 600). Prints only which model ids were changed, never file content.
Run with the Desktop app QUIT. `--revert` removes the lines it added.
"""
import re
import shutil
import sys
import time
from pathlib import Path

VERIFIED = ["deepseek-v4.1-flash", "volcengine/deepseek-v4.1-flash", "doubao-seed-2.1-pro", "kimi-k3", "tencent/kimi-k3", "MiniMax-M3"]
MARK = "input: [text, image]"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
path = Path(args[0]) if args else Path.home() / ".dsh/profiles/desktop/cordis.patch.yml"
text = path.read_text(encoding="utf-8")
if "--revert" in sys.argv:
    new = re.sub(r"\n[ \t]+" + re.escape(MARK) + r"(?=\n)", "", text)
    path.write_text(new, encoding="utf-8")
    print("reverted" if new != text else "nothing to revert")
    sys.exit(0)
bk = Path.home() / f".dsh/backup-image-input-{time.strftime('%Y%m%d-%H%M%S')}"
bk.mkdir(mode=0o700)
shutil.copy2(path, bk / path.name)
(bk / path.name).chmod(0o600)
changed = []
for mid in VERIFIED:
    pat = re.compile(r"(?m)^([ \t]*)- id: " + re.escape(mid) + r"[ \t]*\n(\1[ \t]+name: [^\n]*\n)(?!\1[ \t]+input:)")
    m = pat.search(text)
    if m:
        indent = m.group(1) + "  "
        text = text[:m.end()] + indent + MARK + "\n" + text[m.end():]
        changed.append(mid)
path.write_text(text, encoding="utf-8")
print("backup:", bk)
print("declared image input for:", ", ".join(changed) or "(none; already present or ids not found)")
