"""Register and run the user-level command for a source or packaged installation."""
from contextlib import redirect_stdout
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tempfile

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[1]
USAGE = """chives      启动终端工作台，也可从管道接收问题
chives web  在浏览器打开工作台"""


def add_windows_path(directory):
    import ctypes
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            old, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            old, kind = "", winreg.REG_EXPAND_SZ
        paths = [Path(os.path.expandvars(item.strip('"'))) for item in old.split(";") if item]
        if directory in paths:
            return
        winreg.SetValueEx(key, "Path", 0, kind, str(directory) + (";" + old if old else ""))
    ctypes.windll.user32.SendMessageTimeoutW(0xffff, 0x001a, 0, "Environment", 2, 1000, None)


def add_unix_path(directory):
    if str(directory) in os.get_exec_path():
        return
    home = Path.home()
    shell = Path(os.environ.get("SHELL", "/bin/sh")).name
    line = 'export PATH="$HOME/.local/bin:$PATH"'
    if shell == "zsh":
        profiles = [Path(os.environ.get("ZDOTDIR") or home) / ".zshrc"]
    elif shell == "bash":
        login = next((home / name for name in (".bash_profile", ".bash_login", ".profile")
                      if (home / name).exists()), home / ".profile")
        profiles = [login, home / ".bashrc"]
    elif shell == "fish":
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
        profiles = [config / "fish/conf.d/chives.fish"]
        line = 'fish_add_path "$HOME/.local/bin"'
    else:
        profiles = [home / ".profile"]
    for profile in profiles:
        if profile.exists() and line in profile.read_text().splitlines():
            continue
        profile.parent.mkdir(parents=True, exist_ok=True)
        with profile.open("a") as out:
            out.write("\n# Chives CLI\n" + line + "\n")


def register(mode):
    if os.name == "nt":
        directory = PROJECT.parent.parent / "bin"
        # Relative paths keep the batch file ASCII even under a Unicode user profile.
        release = r"%~dp0..\releases" + "\\" + PROJECT.name
        body = (f'@rem Chives CLI\n@echo off\n"{release}\\.venv\\Scripts\\python.exe" '
                f'"{release}\\scripts\\chives_cli.py" release %*\n')
        launcher = directory / "chives.cmd"
    else:
        directory = Path.home() / ".local/bin"
        body = "#!/bin/sh\n# Chives CLI\nexec " + shlex.join([sys.executable, str(SCRIPT), mode]) + ' "$@"\n'
        launcher = directory / "chives"
    directory.mkdir(parents=True, exist_ok=True)
    if launcher.exists() or launcher.is_symlink():
        expected = b"@rem Chives CLI" if os.name == "nt" else b"# Chives CLI"
        if launcher.is_symlink() or expected not in launcher.read_bytes().splitlines()[:2]:
            raise RuntimeError(f"已有其他程序占用 {launcher}")
    with tempfile.NamedTemporaryFile(dir=directory, delete=False, mode="w", encoding="utf-8") as tmp:
        tmp.write(body)
    pending = Path(tmp.name)
    try:
        pending.chmod(0o755)
        pending.replace(launcher)
    finally:
        pending.unlink(missing_ok=True)
    if os.name == "nt":
        add_windows_path(directory)
    else:
        add_unix_path(directory)
    print(f"已注册 {launcher}。请在新终端输入 chives。")


def control(mode, stop=False):
    if mode == "source":
        subprocess.run([PROJECT / "start", "stop" if stop else "start"], stdout=sys.stderr, check=True)
    else:
        service = runpy.run_path(str(PROJECT / "install.py"))
        with redirect_stdout(sys.stderr):
            service["control"](PROJECT.parent.parent, PROJECT, "stop" if stop else "open")


def main(mode, args):
    if args == ["--register"]:
        register(mode)
        return
    if args in (["--help"], ["-h"]):
        print(USAGE)
        return
    if not args:
        from chives_chat import run
        command = "cli" if sys.stdin.isatty() else "ask"
        run([command], lambda: control(mode), stop_service=lambda: control(mode, stop=True))
        return
    if args == ["web"]:
        control(mode)
        from chives_terminal.actions import open_page
        open_page()
        return
    sys.exit(USAGE)


if __name__ == "__main__":
    try:
        main(sys.argv[1], sys.argv[2:])
    except EOFError:
        pass
    except KeyboardInterrupt:
        print("\n已退出终端，已提交的任务可在工作台查看。", file=sys.stderr)
        sys.exit(130)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
