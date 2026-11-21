"""Verify an ownerless cached OLE item through Win32 backup and OLE reads."""

import ctypes as c
from ctypes import wintypes as w
import hashlib
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clipboard_manager as cm
import win32 as win
from inspect_ole_clipboard import FormatEtc, method


class Medium(c.Structure):
    _fields_ = [("kind", w.DWORD), ("value", w.LPVOID), ("releaser", w.LPVOID)]


def require_hr(result):
    if result < 0:
        raise OSError(f"OLE operation failed with 0x{result & 0xffffffff:08x}")


def clipboard_call(function, *arguments):
    deadline = time.monotonic() + 1
    while True:
        status = function(*arguments)
        if status >= 0 or (status & 0xffffffff) != 0x800401D0 or time.monotonic() >= deadline:
            require_hr(status)
            return
        time.sleep(0.01)


def stream_digest(stream):
    seek = method(stream, 5, w.LONG, c.c_longlong, w.DWORD, c.POINTER(c.c_ulonglong))
    require_hr(seek(stream, 0, 0, None))
    read = method(stream, 3, w.LONG, w.LPVOID, w.ULONG, c.POINTER(w.ULONG))
    block = c.create_string_buffer(65536)
    digest = hashlib.sha256()
    total = 0
    while True:
        received = w.ULONG()
        require_hr(read(stream, block, len(block), c.byref(received)))
        if not received.value:
            return digest.digest()
        total += received.value
        if total > cm.BYTE_LIMIT:
            raise RuntimeError("The test stream exceeds the clipboard backup limit.")
        digest.update(block.raw[:received.value])


def fingerprint():
    get = win.bind(win.ole, "OleGetClipboard", w.LONG, c.POINTER(c.c_void_p))
    release = win.bind(win.ole, "ReleaseStgMedium", None, c.POINTER(Medium))
    free = win.bind(win.ole, "CoTaskMemFree", None, w.LPVOID)
    data, enum = c.c_void_p(), c.c_void_p()
    result = []
    try:
        clipboard_call(get, c.byref(data))
        clipboard_call(method(data, 8, w.LONG, w.DWORD, c.POINTER(c.c_void_p)),
                       data, 1, c.byref(enum))
        for _ in range(128):
            fmt, count = FormatEtc(), w.ULONG()
            clipboard_call(method(enum, 3, w.LONG, w.ULONG, c.POINTER(FormatEtc), c.POINTER(w.ULONG)),
                           enum, 1, c.byref(fmt), c.byref(count))
            if not count.value:
                return result
            try:
                if fmt.device:
                    raise RuntimeError("This fixture requires device-independent cached formats.")
                medium = Medium()
                clipboard_call(method(data, 3, w.LONG, c.POINTER(FormatEtc), c.POINTER(Medium)),
                               data, c.byref(fmt), c.byref(medium))
                try:
                    digest = None
                    if medium.kind == 1:  # TYMED_HGLOBAL
                        size = cm.global_size(medium.value)
                        if size > cm.BYTE_LIMIT:
                            raise RuntimeError("The test block exceeds the clipboard backup limit.")
                        address = cm.global_lock(medium.value)
                        if not address:
                            raise OSError("Could not read the cached memory medium.")
                        try:
                            digest = hashlib.sha256(c.string_at(address, size)).digest()
                        finally:
                            cm.global_unlock(medium.value)
                    elif medium.kind == 4:  # TYMED_ISTREAM
                        digest = stream_digest(medium.value)
                    elif medium.kind != 16:  # TYMED_GDI is also checked through the Win32 DIB.
                        raise RuntimeError("The fixture encountered an unverified OLE storage medium.")
                    result.append((fmt.format, fmt.aspect, fmt.index, fmt.medium, medium.kind, digest))
                finally:
                    release(c.byref(medium))
            finally:
                if fmt.device:
                    free(fmt.device)
        raise RuntimeError("OLE enumeration exceeded the test limit.")
    finally:
        if enum:
            method(enum, 2, w.ULONG)(enum)
        if data:
            method(data, 2, w.ULONG)(data)


def native_memory():
    result = {}
    for fmt in cm.formats():
        if fmt in cm.OBJECT_FORMATS:
            continue
        handle = cm.get_data(fmt)
        size = cm.global_size(handle) if handle else 0
        if not size or size > cm.BYTE_LIMIT:
            raise RuntimeError("A cached format is not a bounded memory block.")
        address = cm.global_lock(handle)
        if not address:
            raise OSError("Could not inspect a cached block.")
        try:
            result[fmt] = hashlib.sha256(c.string_at(address, size)).digest()
        finally:
            cm.global_unlock(handle)
    return result


def main():
    init = win.bind(win.ole, "OleInitialize", w.LONG, w.LPVOID)
    uninit = win.bind(win.ole, "OleUninitialize", None)
    require_hr(init(None))
    window = win.create_window(0, "Static", "Luna cached OLE fixture", 0,
                               0, 0, 0, 0, None, None, win.get_module(None), None)
    if not window:
        uninit()
        raise c.WinError(c.get_last_error())
    clipboard = cm.Clipboard(window)
    primary, rollback = [], []
    succeeded = False
    try:
        before = fingerprint()
        with clipboard.locked():
            available = {fmt: cm.format_name(fmt) for fmt in cm.formats()}
            if not cm.cached_ole_item(available):
                raise RuntimeError("The clipboard does not contain an eligible ownerless OLE cache.")
            original_memory = native_memory()
            primary = cm.snapshot()
            rollback = cm.snapshot()
            cm.restore(primary)
        after = fingerprint()
        with clipboard.locked():
            if cm.clipboard_owner() != window:
                raise RuntimeError("Another app changed the clipboard during the fixture.")
            assert native_memory() == original_memory, "Cached Win32 backing blocks changed."
            assert after == before, "OLE formats or rendered storage media changed."
        for _ in range(2):
            # Repeated operations see Luna's HWND owning the materialized cache.
            with clipboard.locked():
                if cm.clipboard_owner() != window:
                    raise RuntimeError("Another app changed the clipboard during the fixture.")
                second = cm.snapshot(window)
                try:
                    cm.restore(second)
                finally:
                    for item in second:
                        item.free()
            assert fingerprint() == before, "An OLE medium changed on repeated restoration."
            with clipboard.locked():
                if cm.clipboard_owner() != window:
                    raise RuntimeError("Another app changed the clipboard during the fixture.")
                assert native_memory() == original_memory, "A cached backing block changed on repeat."
        succeeded = True
        print("PASS: three cached OLE restore cycles preserved native image backing and IStream/HGLOBAL data.")
    finally:
        try:
            if not succeeded and rollback:
                with clipboard.restoration_lock():
                    if cm.clipboard_owner() == window:
                        cm.restore(rollback)
        finally:
            for item in [*primary, *rollback]:
                item.free()
            win.destroy_window(window)
            uninit()


if __name__ == "__main__":
    main()
