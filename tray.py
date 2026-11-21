"""Native Windows notification-area icon and menu."""

import ctypes as c
import logging
from ctypes import wintypes as w
from pathlib import Path

import win32 as win

WM_TRAY = 0x8010
ICON = Path(__file__).with_name("assets") / "luna.ico"
ID = 1


class NotifyIconData(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("window", w.HWND), ("id", w.UINT), ("flags", w.UINT),
        ("callback", w.UINT), ("icon", w.HICON), ("tip", w.WCHAR * 128),
        ("state", w.DWORD), ("state_mask", w.DWORD), ("info", w.WCHAR * 256),
        ("version", w.UINT), ("info_title", w.WCHAR * 64), ("info_flags", w.DWORD),
        ("guid", c.c_byte * 16), ("balloon_icon", w.HICON),
    ]


shell = c.WinDLL("shell32", use_last_error=True)
notify = win.bind(shell, "Shell_NotifyIconW", w.BOOL, w.DWORD, c.POINTER(NotifyIconData))
load_image = win.bind(
    win.user, "LoadImageW", w.HANDLE, w.HINSTANCE, w.LPCWSTR, w.UINT, c.c_int, c.c_int, w.UINT,
)
destroy_icon = win.bind(win.user, "DestroyIcon", w.BOOL, w.HICON)
register_message = win.bind(win.user, "RegisterWindowMessageW", w.UINT, w.LPCWSTR)
create_menu = win.bind(win.user, "CreatePopupMenu", w.HMENU)
append_menu = win.bind(win.user, "AppendMenuW", w.BOOL, w.HMENU, w.UINT, win.UINT_PTR, w.LPCWSTR)
destroy_menu = win.bind(win.user, "DestroyMenu", w.BOOL, w.HMENU)
track_menu = win.bind(
    win.user, "TrackPopupMenu", w.UINT, w.HMENU, w.UINT, c.c_int, c.c_int, c.c_int,
    w.HWND, c.POINTER(w.RECT),
)
get_cursor = win.bind(win.user, "GetCursorPos", w.BOOL, c.POINTER(w.POINT))
foreground = win.bind(win.user, "SetForegroundWindow", w.BOOL, w.HWND)


class Tray:
    def __init__(self, window, enabled):
        self.window = window
        self.created_message = register_message("TaskbarCreated")
        self.icon = load_image(None, str(ICON), 1, 0, 0, 0x0050)  # icon, default size, from file
        if not self.icon:
            raise OSError("Could not load the Luna tray icon.")
        self.data = NotifyIconData(size=c.sizeof(NotifyIconData), window=window, id=ID,
                                   flags=0x0087, callback=WM_TRAY, icon=self.icon)
        self.enabled = enabled
        self.add()

    def add(self):
        self.data.tip = "Luna Grammar · Ctrl + Win + Z" if self.enabled else "Luna Grammar · Paused"
        if notify(0, c.byref(self.data)):  # NIM_ADD
            self.data.version = 4
            notify(4, c.byref(self.data))  # NIM_SETVERSION
            logging.debug("event=tray.icon_added")
        else:
            logging.debug("The Windows notification area is not available.")

    def update(self, enabled):
        self.enabled = enabled
        self.data.tip = "Luna Grammar · Ctrl + Win + Z" if enabled else "Luna Grammar · Paused"
        notify(1, c.byref(self.data))

    def menu(self, point=None):
        menu = create_menu()
        if not menu:
            return 0
        try:
            append_menu(menu, 0, 1, "Pause Luna" if self.enabled else "Resume Luna")
            append_menu(menu, 0, 2, "Settings…")
            append_menu(menu, 0x0800, 0, None)
            append_menu(menu, 0, 3, "Quit Luna Grammar")
            if point is None:
                p = w.POINT()
                if not get_cursor(c.byref(p)):
                    return 0
                point = p.x, p.y
            foreground(self.window)
            return track_menu(menu, 0x0182, *point, 0, self.window, None)
        finally:
            # The notification-area menu needs a harmless follow-up after dismissal.
            win.post_message(self.window, 0, 0, 0)
            destroy_menu(menu)

    def close(self):
        notify(2, c.byref(self.data))
        destroy_icon(self.icon)
