"""Probe Windows OLE clipboard locking using only a recoverable scratch item."""

import argparse
import os
from ctypes import wintypes as w

from windows_clipboard_integration import cm, isolate_clipboard, publish, require, unicode_data, win


def run(interactive):
    if not interactive:
        isolate_clipboard()
    init = win.bind(win.ole, "OleInitialize", w.LONG, w.LPVOID)
    uninit = win.bind(win.ole, "OleUninitialize", None)
    set_clip = win.bind(win.ole, "OleSetClipboard", w.LONG, w.LPVOID)
    if init(None) < 0:
        raise OSError("Could not initialize the OLE apartment")
    instance = win.get_module(None)
    window = require(win.create_window(0, "Static", "Luna OLE probe", 0,
                                       0, 0, 0, 0, None, None, instance, None))
    clipboard = cm.Clipboard(window)
    try:
        with clipboard.locked():
            backup = cm.snapshot()
            try:
                try:
                    publish({cm.CF_UNICODETEXT: unicode_data("Luna scratch clipboard test")})
                    result = set_clip(None)
                    print(f"OleSetClipboard(NULL) with a Win32 lock: 0x{result & 0xffffffff:08x}")
                    print("Outer HWND still holds the lock:", cm.clipboard_reader() == window)
                finally:
                    if cm.clipboard_reader() != window:
                        require(cm.open_clipboard(window))
                    owner = cm.clipboard_owner()
                    if not owner or win.window_pid(owner) == os.getpid():
                        cm.restore(backup)
                    else:
                        print("New external clipboard item kept.")
            finally:
                for item in backup:
                    item.free()
    finally:
        win.destroy_window(window)
        uninit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive-clipboard", action="store_true")
    run(parser.parse_args().interactive_clipboard)
