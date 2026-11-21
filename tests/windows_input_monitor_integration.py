"""Verify native input-hook registration and shutdown without injecting input."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from input_monitor import InputMonitor
import win32 as win


def main():
    for _ in range(3):
        with InputMonitor() as monitor:
            assert win.editing_input_stamp is not None
            assert win.shortcut_key_state is not None
            assert win.shortcut_key_state() in (None,True,False)
            assert isinstance(win.edit_input(), int)
            assert not monitor.stopped.is_set()
        assert monitor.stopped.is_set()
        assert not monitor.thread.is_alive()
        assert win.editing_input_stamp is None
        assert win.shortcut_key_state is None
    print("PASS: native editing-input hooks registered and stopped cleanly for three cycles.")


if __name__ == "__main__":
    main()
