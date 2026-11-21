"""Read OLE format/medium metadata without logging clipboard payloads."""

import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clipboard_manager as cm
import win32 as win


class FormatEtc(c.Structure):
    _fields_ = [("format", w.WORD), ("device", w.LPVOID), ("aspect", w.DWORD),
                ("index", w.LONG), ("medium", w.DWORD)]


def method(pointer, index, result, *arguments):
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(result, c.c_void_p, *arguments)(table[index])


def main():
    init = win.bind(win.ole, "OleInitialize", w.LONG, w.LPVOID)
    uninit = win.bind(win.ole, "OleUninitialize", None)
    get_clipboard = win.bind(win.ole, "OleGetClipboard", w.LONG, c.POINTER(c.c_void_p))
    free = win.bind(win.ole, "CoTaskMemFree", None, w.LPVOID)
    if init(None) < 0:
        raise OSError("Could not initialize the OLE apartment")
    data = c.c_void_p()
    enum = c.c_void_p()
    try:
        result = get_clipboard(c.byref(data))
        if result < 0:
            raise OSError(f"OleGetClipboard failed with 0x{result & 0xffffffff:08x}")
        result = method(data, 8, w.LONG, w.DWORD, c.POINTER(c.c_void_p))(data, 1, c.byref(enum))
        if result < 0:
            raise OSError(f"EnumFormatEtc failed with 0x{result & 0xffffffff:08x}")
        for _ in range(128):
            fmt = FormatEtc()
            count = w.ULONG()
            result = method(enum, 3, w.LONG, w.ULONG, c.POINTER(FormatEtc), c.POINTER(w.ULONG))(
                enum, 1, c.byref(fmt), c.byref(count))
            if not count.value:
                break
            print(f"OLE format={cm.describe(fmt.format, cm.format_name(fmt.format))} "
                  f"aspect={fmt.aspect} index={fmt.index} mediums=0x{fmt.medium:x} "
                  f"device={bool(fmt.device)}")
            if fmt.device:
                free(fmt.device)
        with cm.Clipboard(None).locked():
            print(f"Clipboard has an owner HWND: {bool(cm.clipboard_owner())}")
            for fmt in cm.formats():
                name = cm.format_name(fmt)
                if name.casefold() in cm.OLE_INTERNAL:
                    handle = cm.get_data(fmt)
                    size = cm.global_size(handle) if handle else 0
                    zero = None
                    if handle and 0 < size <= 32 and name.casefold() == "dataobject":
                        address = cm.global_lock(handle)
                        if address:
                            try:
                                zero = not any(c.string_at(address, size))
                            finally:
                                cm.global_unlock(handle)
                    print(f"Backing format={name!r} handle={bool(handle)} size={size} all_zero={zero}")
    finally:
        if enum:
            method(enum, 2, w.ULONG)(enum)
        if data:
            method(data, 2, w.ULONG)(data)
        uninit()


if __name__ == "__main__":
    main()
