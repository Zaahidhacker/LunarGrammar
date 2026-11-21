"""Use the native clipboard in a private window station with no API requests."""

import argparse
import ctypes as c
import logging
import multiprocessing
import os
from pathlib import Path
from secrets import token_bytes
import struct
import sys
from threading import Thread
from unittest.mock import Mock, patch
from ctypes import wintypes as w

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clipboard_manager as cm
import win32 as win


NEWER_TEXT = "New clipboard item from the independent Luna test process"
COPIED_TEXT = "Selected Zoë 😀\r\nこんにちは"


def require(result):
    if not result:
        raise c.WinError(c.get_last_error())
    return result


def isolate_clipboard():
    create_station = win.bind(win.user, "CreateWindowStationW", w.HANDLE, w.LPCWSTR, w.DWORD,
                              w.DWORD, w.LPVOID)
    set_station = win.bind(win.user, "SetProcessWindowStation", w.BOOL, w.HANDLE)
    create_desktop = win.bind(win.user, "CreateDesktopW", w.HANDLE, w.LPCWSTR, w.LPCWSTR,
                              w.LPVOID, w.DWORD, w.DWORD, w.LPVOID)
    set_desktop = win.bind(win.user, "SetThreadDesktop", w.BOOL, w.HANDLE)
    station = require(create_station(f"LunaTest-{os.getpid()}", 0, 0x037F, None))
    require(set_station(station))
    desktop = require(create_desktop("LunaTest", None, None, 0, 0x01FF, None))
    require(set_desktop(desktop))


def unicode_data(text):
    return (text + "\0").encode("utf-16-le")


def read_bytes(fmt):
    handle = require(cm.get_data(fmt))
    address = require(cm.global_lock(handle))
    try:
        return c.string_at(address, cm.global_size(handle))
    finally:
        cm.global_unlock(handle)


def publish(payloads):
    require(cm.empty_clipboard())
    for fmt, data in payloads.items():
        item = cm.memory_item(fmt, data)
        try:
            item.publish()
        finally:
            item.free()


def external_writer(channel):
    """Publish only over an identified scratch item and keep the owner HWND alive."""
    window = None
    try:
        window = require(win.create_window(0, "Static", "Luna Clipboard Writer", 0,
                                           0, 0, 0, 0, None, None, win.get_module(None), None))
        channel.send(window)
        clipboard = cm.Clipboard(window)
        while (request := channel.recv()) is not None:
            mode, owner, marker, token = request
            with clipboard.locked():
                if (cm.clipboard_owner() != owner or not cm.has_format(marker)
                        or not read_bytes(marker).startswith(token)):
                    raise RuntimeError("The scratch clipboard item was already replaced.")
                text = COPIED_TEXT if mode == "copy" else NEWER_TEXT
                publish({cm.CF_UNICODETEXT: unicode_data(text)})
            channel.send(True)
    finally:
        if window:
            win.destroy_window(window)
        channel.close()


def receive(channel):
    if not channel.poll(10):
        raise TimeoutError("The independent clipboard writer did not respond.")
    return channel.recv()


def run(interactive=False):
    if not interactive:
        isolate_clipboard()
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    clipboard = None

    @win.WNDPROC
    def window_proc(hwnd, message, wparam, lparam):
        if message == win.WM_RENDERFORMAT:
            clipboard.render(wparam)
            return 0
        if message == win.WM_CLOSE:
            win.post_quit(0)
            return 0
        return win.default_proc(hwnd, message, wparam, lparam)

    module = win.get_module(None)
    name = "LunaClipboardTest"
    window_class = win.WindowClass(proc=window_proc, instance=module, name=name)
    require(win.register_class(c.byref(window_class)))
    owner, reader = (require(win.create_window(0, name, name, 0, 0, 0, 0, 0,
                                              None, None, module, None)) for _ in range(2))
    clipboard = cm.Clipboard(owner)
    target = win.Target(reader, reader, 0, os.getpid())
    unicode_fmt = cm.CF_UNICODETEXT
    fixture_format = cm.register_format("Luna.Scratch.ArbitraryFormat")
    fixture_token = token_bytes(16)
    payloads = {
        unicode_fmt: unicode_data("Original Zoë 😀\r\nこんにちは"),
        cm.register_format("HTML Format"): b"<html><b>Clipboard fixture</b></html>\0",
        cm.register_format("Rich Text Format"): b"{\\rtf1\\ansi Clipboard fixture}\0",
        8: struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0) + b"\0\xff\0\0",
        15: struct.pack("<IiiII", 20, 0, 0, 0, 1) + unicode_data("C:\\Luna-sample.txt\0"),
        fixture_format: fixture_token,
    }
    guard = Mock()
    guard.unchanged_input.return_value = True
    guard.input_matches.return_value = True
    writer = None
    channel = None
    # The spawned process shares the real clipboard. The isolated fixture
    # deliberately stays within its private window station.
    if interactive:
        process_context = multiprocessing.get_context("spawn")
        channel, child = process_context.Pipe()
        writer = process_context.Process(target=external_writer, args=(child,))
        writer.start()
        child.close()

    def verify_original():
        with clipboard.locked():
            for fmt, expected in payloads.items():
                assert read_bytes(fmt)[:len(expected)] == expected, cm.describe(fmt, cm.format_name(fmt))

    def shortcut(key, _timestamp):
        if key == "C":
            with cm.Clipboard(reader).locked():
                if not is_test_clipboard(cm.clipboard_owner()):
                    raise RuntimeError("The original scratch clipboard item was replaced.")
                publish({unicode_fmt: unicode_data(COPIED_TEXT),
                         fixture_format: fixture_token})
        elif key == "V":
            with cm.Clipboard(reader).locked():
                assert cm.selected_text(100) == "Corrected Zoë 😀\r\nこんにちは"

    def is_test_clipboard(current_owner):
        return (current_owner in (owner, reader)
                and cm.has_format(fixture_format)
                and read_bytes(fixture_format).startswith(fixture_token))

    errors = []

    def exercise():
        original = None
        writer_window = None
        try:
            if writer:
                writer_window = receive(channel)
            with cm.Clipboard(reader).locked():
                original = cm.snapshot()
                publish(payloads)
            with patch.object(win, "edit_shortcut", side_effect=shortcut):
                for _ in range(3):
                    assert clipboard.copy_keyboard(target, 100, guard) == COPIED_TEXT
                    verify_original()
                    clipboard.paste("Corrected Zoë 😀\nこんにちは", target, Mock(), guard)
                    verify_original()
            if writer_window:
                external_target = win.Target(writer_window, writer_window, 0, writer.pid)

                def copy_from_process(key, _timestamp):
                    assert key == "C"
                    with clipboard.locked():
                        current_owner = cm.clipboard_owner()
                        if not is_test_clipboard(current_owner):
                            raise RuntimeError("The scratch clipboard item was replaced.")
                    channel.send(("copy", current_owner, fixture_format, fixture_token))
                    assert receive(channel) is True

                with patch.object(win, "edit_shortcut", side_effect=copy_from_process):
                    assert clipboard.copy_keyboard(external_target, 100, guard) == COPIED_TEXT
                verify_original()

                def paste_then_copy(key, timestamp):
                    shortcut(key, timestamp)
                    channel.send(("newer", owner, clipboard.private_format, clipboard.offer.token))
                    assert receive(channel) is True

                with patch.object(win, "edit_shortcut", side_effect=paste_then_copy):
                    clipboard.paste("Corrected Zoë 😀\nこんにちは", target, Mock(), guard)
                with clipboard.locked():
                    assert cm.clipboard_owner() == writer_window
                    assert cm.selected_text(100) == NEWER_TEXT
        except BaseException as error:
            errors.append(error)
        finally:
            if original is not None:
                try:
                    with clipboard.restoration_lock():
                        current_owner = cm.clipboard_owner()
                        owns_test_data = is_test_clipboard(current_owner) or (
                            writer_window and current_owner == writer_window
                            and cm.selected_text(100) in (COPIED_TEXT, NEWER_TEXT)
                        )
                        if owns_test_data:
                            cm.restore(original)
                except BaseException as error:
                    errors.append(error)
                finally:
                    for item in original:
                        item.free()
            win.post_message(owner, win.WM_CLOSE, 0, 0)

    worker = Thread(target=exercise)
    worker.start()
    message = w.MSG()
    while win.get_message(c.byref(message), None, 0, 0) > 0:
        win.dispatch_message(c.byref(message))
    worker.join()
    if writer:
        try:
            channel.send(None)
        except (BrokenPipeError, EOFError, OSError):
            pass
        finally:
            channel.close()
        writer.join(timeout=5)
        if writer.is_alive():
            writer.terminate()
            writer.join()
            errors.append(RuntimeError("The scratch clipboard writer did not shut down."))
        if writer.exitcode:
            errors.append(RuntimeError(f"The scratch clipboard writer exited with {writer.exitcode}."))
    win.destroy_window(reader)
    win.destroy_window(owner)
    win.unregister_class(name, module)
    if errors:
        raise errors[0]
    scope = "guarded interactive clipboard" if interactive else "isolated window station"
    print(f"PASS: three copy/paste/restore cycles with real Win32 formats ({scope}).")
    if interactive:
        print("PASS: capture from a different process preserved and restored the scratch clipboard.")
        print("PASS: a newer clipboard write from another process survived Luna's paste cleanup.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive-clipboard", action="store_true",
                        help="temporarily use and restore the real clipboard if it can be backed up")
    run(parser.parse_args().interactive_clipboard)
