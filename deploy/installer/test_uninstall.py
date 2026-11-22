"""Regression coverage for destructive CLI confirmation and ownership boundaries."""
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import chives_cli
import chives_uninstall as remove


class UninstallTests(unittest.TestCase):
    def test_only_exact_yes_or_cancel(self):
        with redirect_stdout(StringIO()):
            for answer in ("", "y", "YES", " yes", "yes ", "yes"):
                with self.subTest(answer=answer), patch("builtins.input", return_value=answer):
                    self.assertEqual(remove.confirm(Path("Chives"), []), answer == "yes")
            for signal in (KeyboardInterrupt, EOFError):
                with patch("builtins.input", side_effect=signal):
                    self.assertFalse(remove.confirm(Path("Chives"), []))

    def test_pipe_cannot_confirm(self):
        with patch("sys.stdin", StringIO("yes\n")), self.assertRaisesRegex(ValueError, "交互终端"):
            remove.uninstall(Path("unread"), "release")

    def test_custom_root_with_other_files_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "shared"
            release = root / "releases/v1"
            release.mkdir(parents=True)
            (release / "package.json").write_text('{"name":"chives"}')
            (release / "install.py").touch()
            (release / ".installed").touch()
            (root / "family-photos").mkdir()
            with patch.object(Path, "home", return_value=parent), self.assertRaisesRegex(ValueError, "自定义安装位置"):
                remove.installation("release", release)

    @unittest.skipUnless(os.name == "nt", "Native Windows batch behavior")
    def test_windows_launcher_reports_clean_self_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "program with spaces"
            app = root / "releases/test"
            (app / "scripts").mkdir(parents=True)
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", app / ".venv"], check=True)
            # Exercise only the native handoff after the interactive Python stage has approved it.
            (app / "scripts/chives_cli.py").write_text("raise SystemExit(78)\n")
            (root / ".uninstall-pending").touch()
            with patch.object(chives_cli, "PROJECT", app), patch.object(chives_cli, "add_windows_path"), redirect_stdout(StringIO()):
                chives_cli.register("release")
            result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", str(root / "bin/chives.cmd"),
                                     "uninstall"], capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b"Chives uninstalled.", result.stdout)
            self.assertEqual(result.stderr.strip(), b"")
            self.assertFalse(root.exists())

    def test_only_installer_owned_shell_block_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            profile = home / ".zshrc"
            own = b'# Chives CLI\r\nexport PATH="$HOME/.local/bin:$PATH"\r\n'
            other = b'# User settings\r\nexport PATH="$HOME/.local/bin:$PATH"\r\n'
            profile.write_bytes(own + other)
            with patch.object(Path, "home", return_value=home), patch.dict(
                os.environ, {"ZDOTDIR": tmp, "XDG_CONFIG_HOME": str(home / ".config")}
            ):
                remove.clean_profiles()
            self.assertEqual(profile.read_bytes(), other)


if __name__ == "__main__":
    unittest.main()
