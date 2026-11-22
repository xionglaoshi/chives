"""Interactive removal of the installation that owns the current CLI."""
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import unicodedata
import uuid


WINDOWS = os.name == "nt"
WINDOWS_HANDOFF = 78
PROFILE_BLOCK = re.compile(
    rb'(?m)^# Chives CLI\r?\n(?:export PATH="\$HOME/\.local/bin:\$PATH"|fish_add_path "\$HOME/\.local/bin")\r?\n'
)


def installation(mode, project):
    home = Path.home().resolve()
    if json.loads((project / "package.json").read_text(encoding="utf-8"))["name"] != "chives":
        raise ValueError("当前目录缺少 Chives 安装标识。")
    if mode == "source":
        if project != home / ".chives" or not (project / "start").is_file():
            raise ValueError("源码卸载仅支持专用检出 ~/.chives。")
        return project
    if (mode != "release" or project.parent.name != "releases"
            or not (project / ".installed").is_file() or not (project / "install.py").is_file()):
        raise ValueError("无法确认安装目录。")
    root = project.parent.parent
    if root == home or root in home.parents or root.parent == root or root == Path(sys.prefix):
        raise ValueError(f"拒绝删除共享目录 {root}")
    if root not in (home / ".chives", home / ".chives-install", home / "AppData/Local/Chives"):
        known = {"releases", "tools", "cache", "data", "logs", "bin", "running", "ready", "stop",
                 "service.lock", ".source-install.lock", ".installing", ".uninstall-pending"}
        if any(p.name not in known and not p.name.startswith(".setup.") for p in root.iterdir()):
            raise ValueError(f"自定义安装位置含有来源不明的项目，请先移出或核对：{root}")
    return root


def launcher_for(project, mode, root):
    if WINDOWS:
        launcher = root / "bin/chives.cmd"
        if Path(os.environ.get("CHIVES_UNINSTALL_LAUNCHER", "")) != launcher:
            raise ValueError("请在终端用当前安装的 chives uninstall 执行。")
        return launcher
    launcher = Path.home() / ".local/bin/chives"
    if launcher.is_symlink() or not launcher.is_file():
        raise ValueError(f"无法确认命令入口 {launcher}")
    lines = launcher.read_text().splitlines()
    if len(lines) < 3 or lines[1] != "# Chives CLI" or shlex.split(lines[2])[2:] != [
            str(project / "scripts/chives_cli.py"), mode, "$@"]:
        raise ValueError("终端命令已属于另一套安装，请从正在使用的 Chives 执行卸载。")
    return launcher


def remove_path(path):
    if path.is_symlink() or (WINDOWS and os.path.isjunction(path)):
        if WINDOWS and path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def clean_profiles():
    home = Path.home()
    fish = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "fish/conf.d/chives.fish"
    profiles = {home / name for name in (".profile", ".bash_profile", ".bash_login", ".bashrc", ".zshrc")}
    profiles.update({Path(os.environ.get("ZDOTDIR") or home) / ".zshrc", fish})
    for path in profiles:
        if not path.is_file():
            continue
        original = path.read_bytes()
        result = PROFILE_BLOCK.sub(b"", original)
        if original == result:
            continue
        if path == fish and not result.strip():
            path.unlink()
        else:
            path.write_bytes(result)


def remove_windows_path(directory):
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            old, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return
        parts = old.split(";")
        kept = [p for p in parts if Path(os.path.expandvars(p.strip().strip('"'))) != directory]
        if kept != parts:
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(kept))
    ctypes.windll.user32.SendMessageTimeoutW(0xffff, 0x001a, 0, "Environment", 2, 1000, None)


def mac_jobs(root):
    jobs = []
    if sys.platform != "darwin":
        return jobs
    for file in (Path.home() / "Library/LaunchAgents").glob("local.chives.*.plist"):
        spec = plistlib.loads(file.read_bytes())
        if spec.get("Label") == file.stem and (spec.get("WorkingDirectory") == str(root) or
               any(isinstance(a, str) and a.startswith(str(root) + "/") for a in spec.get("ProgramArguments", []))):
            jobs.append(file)
    # Remove the watchdog before taking down the services it supervises.
    return sorted(jobs, key=lambda p: ("watchdog" not in p.stem, p.name))


@contextmanager
def install_guard(root):
    # The Unix installers reserve .installing, PowerShell exclusively opens the file.
    lock = root / ".installing"
    try:
        lock.mkdir()
        identity = lock.stat()
    except FileExistsError:
        raise RuntimeError("安装或卸载正在进行，请稍后重试。") from None
    try:
        with ExitStack() as stack:
            if WINDOWS:
                stack.enter_context((root / ".source-install.lock").open("a+b"))
            yield
    finally:
        if lock.is_dir() and os.path.samestat(identity, lock.stat()):
            lock.rmdir()


def check_mounts(root):
    if root.is_mount():
        raise ValueError(f"请先移出挂载点上的安装：{root}")
    if sys.platform.startswith("linux"):
        entries = Path("/proc/self/mountinfo").read_text().splitlines()
        points = [re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]) for line in entries]
    elif sys.platform == "darwin":
        table = subprocess.check_output(["/sbin/mount"], text=True)
        points = [line.partition(" on ")[2].rpartition(" (")[0] for line in table.splitlines()]
    else:
        return
    for point in points:
        if point and root in Path(point).parents:
            raise ValueError(f"请先卸载安装目录内的挂载点：{point}")


def confirm(root, paths):
    width = max(12, min(68, shutil.get_terminal_size().columns - 4))
    lines = ["Chives · 永久卸载", "", "将停止本机服务并永久删除以下安装目录：", str(root),
             "", "用户档案、持仓、记忆、Bot、会话、模型密钥及安装目录内的备份都会删除。",
             "终端命令和本安装的启动项也会移除。此操作不可逆，请先自行备份。"]
    lines.extend(str(p) for p in paths if p.exists() or p.is_symlink())
    print("╭" + "─" * (width + 2) + "╮")
    for line in lines:
        row, cells = "", 0
        for ch in line:
            if unicodedata.category(ch).startswith("C"):
                ch = "?"
            size = 0 if unicodedata.combining(ch) else (2 if unicodedata.east_asian_width(ch) in "WF" else 1)
            if cells + size > width:
                print("│ " + row + " " * (width - cells) + " │")
                row, cells = "", 0
            row += ch
            cells += size
        print("│ " + row + " " * (width - cells) + " │")
    print("╰" + "─" * (width + 2) + "╯")
    try:
        return input("请输入小写 yes 确认卸载，其他输入取消 > ") == "yes"
    except (EOFError, KeyboardInterrupt):
        return False


def uninstall(project, mode):
    if not sys.stdin.isatty():
        raise ValueError("卸载需要在交互终端手动输入 yes。")
    root = installation(mode, project)
    launcher = launcher_for(project, mode, root)
    if WINDOWS and Path.cwd().is_relative_to(root):
        raise ValueError("请先切换到安装目录以外的位置，再执行 chives uninstall。")
    check_mounts(root)
    home = Path.home()
    prefs = home / ".config/chives"
    jobs = mac_jobs(root)
    extras = []
    if mode == "source":
        venv = home / ".agents/venvs/chives"
        if Path(sys.prefix) == venv:
            extras.append(venv)
        if any(p.stem == "local.chives.public-entry" for p in jobs):
            extras.append(home / ".agents/credentials/chives-public-entry.json")
    if not confirm(root, [prefs, *jobs, *extras]):
        print("\n已取消卸载。")
        return
    print("正在停止服务并清理本机安装……", flush=True)
    with install_guard(root), ExitStack() as stack:
        if mode == "release":
            service = runpy.run_path(str(project / "install.py"))
            stack.enter_context(service["command_lock"](root))
            service["stop_service"](root)
        for path in jobs:
            job = f"gui/{os.getuid()}/{path.stem}"
            if subprocess.run(["launchctl", "print", job], capture_output=True).returncode == 0:
                subprocess.run(["launchctl", "bootout", job], check=True)
            path.unlink()
        if mode == "source":
            if sys.platform == "darwin":
                job = f"gui/{os.getuid()}/local.chives.workbench"
                current = subprocess.run(["launchctl", "print", job], capture_output=True, text=True)
                command = str(root / "scripts/serve-chives.sh")
                if current.returncode == 0 and command in (line.strip() for line in current.stdout.splitlines()):
                    subprocess.run(["launchctl", "bootout", job], check=True)
            subprocess.run(["/bin/bash", str(root / "scripts/chives.sh"), "stop", "--engines"], check=True)
        for path in [prefs, *extras]:
            remove_path(path)
        if WINDOWS:
            # The batch launcher waits until the private Python executable is unlocked.
            (root / ".uninstall-pending").touch()
            remove_windows_path(launcher.parent)
            raise SystemExit(WINDOWS_HANDOFF)
        clean_profiles()
        pending = root.with_name(f".{root.name.lstrip('.')}-uninstall-{uuid.uuid4().hex}")
        root.rename(pending)
        launcher.unlink()
    try:
        shutil.rmtree(pending)
    except OSError as exc:
        raise RuntimeError(f"卸载尚未完成，待清理目录为 {pending}：{exc}") from exc
    print("已卸载 Chives，本机用户数据已删除。")
