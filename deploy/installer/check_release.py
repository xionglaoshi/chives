"""Exercise the archived client and bundled runtimes on their native runner, before upload."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def checked_asset(folder, name):
    path = folder / name
    digest, size = (folder / (name + ".sha256")).read_text(encoding="ascii").split()
    with path.open("rb") as stream:
        if path.stat().st_size != int(size) or hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError(f"invalid release asset: {name}")
    return path


def smoke(folder, target):
    tag = (Path(__file__).with_name("channel")).read_text().strip()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for component in ("bootstrap", "python"):
            with tarfile.open(checked_asset(folder, f"{component}-{target}.tar.gz")) as archive:
                archive.extractall(work, filter="data")
        python = work / "python" / ("python.exe" if os.name == "nt" else "bin/python3")
        env = {**os.environ, "HOME": str(work), "USERPROFILE": str(work), "PYTHONUTF8": "1",
               "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
               "ALL_PROXY":"http://127.0.0.1:9", "NO_PROXY": "localhost,127.0.0.1"}
        # The staged directory stands in for the unpublished release. The rest is the archived installer.
        command = [python, "-I", "-u", __file__, "--client", work, folder, tag, target]
        subprocess.run(command, env=env, check=True)


def client(work, folder, tag, target):
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("bundle_client", work / "install.py")
    client = module_from_spec(spec)
    spec.loader.exec_module(client)
    client.get_asset = lambda root, tag, name: checked_asset(folder, name)
    client.find_node = lambda platform_id: None
    root = work / ".chives"
    client.install(root, tag, target)
    release = root / "releases" / f"{tag}-{target}"
    # Reentry must reuse the configured version and must not alter personal data.
    sentinel = root / "data" / "smoke-marker"
    sentinel.parent.mkdir(exist_ok=True)
    sentinel.write_text("preserve")
    if os.environ.get("CHIVES_INSTALL_BUILD_ONLY") != "1":
        try:
            assert all(client.healthy(name) for name in client.PORTS)
        finally:
            client.control(root, release, "stop")
    os.environ["CHIVES_INSTALL_BUILD_ONLY"] = "1"
    client.install(root, tag, target)
    assert sentinel.read_text() == "preserve"


if __name__ == "__main__":
    if sys.argv[1] == "--client":
        client(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5])
    else:
        smoke(Path(sys.argv[1]).resolve(), sys.argv[2])
