"""Install only the Python dependencies of the registered read-only data tools."""
import argparse
import ast
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile

from sdk_spec import REVISION, TOOL_MODULES

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "runtime/cn-data-sdk" / REVISION
STAMP = ".chives-gateway-v1"


def read_snapshot(source):
    bundle = subprocess.check_output([
        "git", "-C", str(source), "archive", REVISION, "LICENSE", "NOTICE",
        "agent/backtest", "agent/src", "agent/cli/_version.py",
    ])
    files = {}
    with tarfile.open(fileobj=io.BytesIO(bundle)) as archive:
        for item in archive:
            path = Path(item.name.removeprefix("agent/"))
            if not item.isfile() or path.is_absolute() or ".." in path.parts:
                continue
            if path.suffix == ".py" or path.name.upper().startswith(("LICENSE", "NOTICE", "COPYING")):
                files[path] = archive.extractfile(item).read()
    return files


def referenced_modules(tree, package):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = package[:len(package) + 1 - node.level] if node.level else []
            name = ".".join([*prefix, node.module] if node.module else prefix)
            yield name
            yield from (f"{name}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # The pinned SDK also registers loader and connector modules by dotted name.
            if node.value.startswith(("src.", "backtest.", "cli.")):
                yield node.value


def gateway_files(files):
    index = {
        ".".join(path.with_suffix("").parts).removesuffix(".__init__"): path
        for path in files if path.suffix == ".py"
    }
    roots = {f"src.tools.{name}_tool" for name in TOOL_MODULES}
    # Providers select market loaders and broker connectors at request time.
    roots.update(name for name in index if name.startswith(("backtest.loaders.", "src.trading.connectors.")))
    pending = list(roots)
    needed = set()
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        needed.add(name)
        path = index[name]
        package = name.split(".") if path.name == "__init__.py" else name.split(".")[:-1]
        dependencies = referenced_modules(ast.parse(files[path], filename=str(path)), package)
        for dependency in (name.rpartition(".")[0], *dependencies):
            while dependency:
                if dependency in index and dependency not in needed:
                    pending.append(dependency)
                dependency = dependency.rpartition(".")[0]
    paths = {index[name] for name in needed}
    parents = {parent for path in paths for parent in path.parents}
    return paths | {p for p in files if p.suffix != ".py" and p.parent in parents}


def install(source):
    if (TARGET / STAMP).is_file():
        return
    files = read_snapshot(source)
    keep = gateway_files(files)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TARGET.parent) as directory:
        stage = Path(directory) / "package"
        for path in sorted(keep):
            output = stage / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(files[path])
        if not TARGET.exists():
            (stage / STAMP).touch()
            try:
                stage.rename(TARGET)
                return
            except OSError:
                if not TARGET.is_dir():
                    raise

        # Upgrade an existing full snapshot. Leave locally changed or unknown files alone.
        for path in sorted(keep):
            installed = TARGET / path
            if not installed.exists():
                installed.parent.mkdir(parents=True, exist_ok=True)
                (stage / path).replace(installed)
        for path in sorted(files.keys() - keep):
            installed = TARGET / path
            if path.suffix == ".py" and installed.is_file() and installed.read_bytes() == files[path]:
                installed.unlink(missing_ok=True)
                for cache in (installed.parent / "__pycache__").glob(f"{installed.stem}.*.pyc"):
                    cache.unlink(missing_ok=True)
        for folder in sorted(TARGET.rglob("*"), reverse=True):
            if folder.is_dir() and not folder.is_symlink() and not any(folder.iterdir()):
                folder.rmdir()
        (TARGET / STAMP).touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Git checkout containing the pinned data SDK revision")
    install(parser.parse_args().source)
    print(TARGET)
