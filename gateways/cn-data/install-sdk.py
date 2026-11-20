"""Materialize a pinned Python data-provider snapshot without installing an application."""
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

REV = 'cb99dca528695ffe78429483a90399a89f61d614'
root = Path(__file__).resolve().parents[2]
target = root / 'runtime/cn-data-sdk' / REV
if target.is_dir():
    print(target)
    sys.exit(0)
source = Path(sys.argv[1]).resolve(strict=True)
archive = subprocess.check_output(['git', '-C', str(source), 'archive', REV, 'LICENSE','NOTICE',
                                   'agent/backtest','agent/src','agent/cli/_version.py'])
target.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=target.parent) as temp:
    stage = Path(temp) / 'sdk'
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for item in bundle:
            rel = Path(item.name.removeprefix('agent/'))
            if not item.isfile() or '..' in rel.parts or rel.is_absolute():
                continue
            if rel.parts[0] in ('LICENSE','NOTICE') or (rel.suffix == '.py' and 'skills' not in rel.parts[:-1]):
                path = stage / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(bundle.extractfile(item).read())
    stage.rename(target)
print(target)
