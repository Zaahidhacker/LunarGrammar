"""Verify the packaged startup shortcut using a temporary link outside Startup."""

from pathlib import Path
import sys
from tempfile import mkdtemp
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comtypes.client import CreateObject
import settings_window


def main():
    root = Path(__file__).resolve().parents[1]
    executable = root / "dist" / "LunaGrammar.exe"
    if not executable.is_file():
        raise FileNotFoundError("Build the Windows executable before running this fixture.")
    scratch = Path(mkdtemp(prefix="startup-fixture-", dir=root / "tests")).resolve()
    if scratch.parent != (root / "tests").resolve():
        raise RuntimeError("Unexpected shortcut fixture directory.")
    link = scratch / "Luna Grammar.lnk"
    try:
        with patch.object(settings_window, "startup_link", return_value=link):
            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(executable)):
                    settings_window.save_startup(True)
                    shortcut = CreateObject("WScript.Shell", dynamic=True).CreateShortcut(str(link))
                    assert Path(shortcut.TargetPath).resolve() == executable.resolve()
                    assert shortcut.Arguments == ""
                    assert Path(shortcut.WorkingDirectory).resolve() == executable.parent.resolve()
                    shortcut = None
                    settings_window.save_startup(False)
                    assert not link.exists()
        print("PASS: packaged startup target, arguments, working directory, and shortcut removal.")
    finally:
        link.unlink(missing_ok=True)
        scratch.rmdir()


if __name__ == "__main__":
    main()
