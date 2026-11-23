"""Exercise bounded replacement and undo in a real hidden Win32 Edit control."""

import ctypes as c
import os
from pathlib import Path
import sys
from threading import Event
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import win32 as win
from config import Settings
from text_selection import Trigger, correct_selection


def contents(window):
    length = win.send_window_message(window, win.WM_GETTEXTLENGTH)
    buffer = c.create_unicode_buffer(length + 1)
    win.send_window_message(window, win.WM_GETTEXT, len(buffer), c.addressof(buffer))
    return buffer.value


def main():
    instance = win.get_module(None)
    root = win.create_window(0, "Static", "Luna native Edit fixture", 0,
                             0, 0, 680, 240, None, None, instance, None)
    if not root:
        raise c.WinError(c.get_last_error())
    editor = None
    try:
        editor = win.create_window(0, "Edit", "", 0x40000000 | 0x0004 | 0x0040 | 0x0080,
                                   0, 0, 640, 200, root, None, instance, None)
        if not editor:
            raise c.WinError(c.get_last_error())
        prefix, suffix = "Before 🐈 [", "] After"
        selected = "i met Zoë 😀\r\nshe has a luna test"
        corrected = "I met Zoë 😀.\r\nShe has a Luna test."
        original = prefix + selected + suffix
        target = win.Target(root, editor, win.current_thread_id(), os.getpid())
        win.set_focus(editor)
        clipboard = Mock()
        engine = Mock()
        engine.correct.return_value = corrected
        start = len(prefix.encode("utf-16-le")) // 2
        end = start + len(selected.encode("utf-16-le")) // 2
        with patch.object(win, "current_target", return_value=target):
            with patch.object(win, "last_input", return_value=1):
                with patch.object(win, "keys_down", return_value=False):
                    for _ in range(3):
                        value = c.create_unicode_buffer(original)
                        win.send_window_message(editor, 0x000C, 0, c.addressof(value))  # WM_SETTEXT
                        win.send_window_message(editor, 0x00B1, start, end)  # EM_SETSEL
                        result = correct_selection(Trigger(target, 0), lambda: 0, Event(),
                                                   Settings(), None, clipboard, engine)
                        assert result == "success"
                        assert contents(editor) == prefix + corrected + suffix
                        assert win.send_window_message(editor, 0x00C7)  # EM_UNDO
                        assert contents(editor) == original
        assert not clipboard.mock_calls
        assert engine.correct.call_count == 3
        print("PASS: three native Win32 Edit corrections preserved surrounding Unicode text and undo.")
    finally:
        if editor:
            win.destroy_window(editor)
        win.destroy_window(root)


if __name__ == "__main__":
    main()
