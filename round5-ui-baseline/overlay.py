"""A per-monitor, nonactivating Win32 layered window for the Luna capsule."""

import ctypes as c
import time
from ctypes import wintypes as w

import win32 as win
from pill_art import Motion, pill_position, render

HDC = w.HDC
P = c.POINTER
NAME = "LunaGrammar.StatusPill.v2"
WM_TIMER = 0x0113
WM_DPICHANGED = 0x02E0
WM_MOUSEACTIVATE = 0x0021
WM_NCHITTEST = 0x0084
WM_LBUTTONUP = 0x0202
SWP_NOACTIVATE = 0x0010


class MonitorInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]


class BitmapInfo(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("width", w.LONG), ("height", w.LONG), ("planes", w.WORD),
        ("bits", w.WORD), ("compression", w.DWORD), ("image_bytes", w.DWORD),
        ("x_ppm", w.LONG), ("y_ppm", w.LONG), ("colors", w.DWORD), ("important", w.DWORD),
    ]


class Blend(c.Structure):
    _fields_ = [("operation", w.BYTE), ("flags", w.BYTE), ("alpha", w.BYTE), ("format", w.BYTE)]


set_dpi_context = win.bind(win.user, "SetProcessDpiAwarenessContext", w.BOOL, w.HANDLE)
window_dpi = win.bind(win.user, "GetDpiForWindow", w.UINT, w.HWND)
monitor_from_window = win.bind(win.user, "MonitorFromWindow", w.HANDLE, w.HWND, w.DWORD)
get_monitor = win.bind(win.user, "GetMonitorInfoW", w.BOOL, w.HANDLE, P(MonitorInfo))
get_window_rect = win.bind(win.user, "GetWindowRect", w.BOOL, w.HWND, P(w.RECT))
system_parameters = win.bind(win.user, "SystemParametersInfoW", w.BOOL, w.UINT, w.UINT, w.LPVOID, w.UINT)
set_position = win.bind(
    win.user, "SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT,
)
show_window = win.bind(win.user, "ShowWindow", w.BOOL, w.HWND, c.c_int)
set_timer = win.bind(win.user, "SetTimer", win.UINT_PTR, w.HWND, win.UINT_PTR, w.UINT, w.LPVOID)
kill_timer = win.bind(win.user, "KillTimer", w.BOOL, w.HWND, win.UINT_PTR)
update_layer = win.bind(
    win.user, "UpdateLayeredWindow", w.BOOL, w.HWND, HDC, P(w.POINT), P(w.SIZE),
    HDC, P(w.POINT), w.DWORD, P(Blend), w.DWORD,
)
create_dc = win.bind(win.gdi, "CreateCompatibleDC", HDC, HDC)
delete_dc = win.bind(win.gdi, "DeleteDC", w.BOOL, HDC)
create_dib = win.bind(win.gdi, "CreateDIBSection", w.HANDLE, HDC, P(BitmapInfo), w.UINT, P(w.LPVOID), w.HANDLE, w.DWORD)
select_object = win.bind(win.gdi, "SelectObject", w.HANDLE, HDC, w.HANDLE)
delete_object = win.bind(win.gdi, "DeleteObject", w.BOOL, w.HANDLE)


def reduced_motion(setting):
    animations = w.BOOL(True)
    if setting == "reduced":
        return True
    # SPI_GETCLIENTAREAANIMATION reads Windows Accessibility > Visual effects.
    return bool(system_parameters(0x1042, 0, c.byref(animations), 0) and not animations.value)


def work_area(target):
    handle = monitor_from_window(target, 2)  # MONITOR_DEFAULTTONEAREST
    info = MonitorInfo(size=c.sizeof(MonitorInfo))
    if not handle or not get_monitor(handle, c.byref(info)):
        raise OSError("Could not locate the editing monitor.")
    r = info.work
    return r.left, r.top, r.right, r.bottom


class Surface:
    def __init__(self):
        self.dc = create_dc(None)
        if not self.dc:
            raise OSError("Could not create the overlay surface.")
        self.bitmap = self.old = None
        self.pixels = w.LPVOID()
        self.size = (0, 0)

    def write(self, image):
        width, height = image.size
        if self.size != image.size:
            info = BitmapInfo(size=c.sizeof(BitmapInfo), width=width, height=-height, planes=1, bits=32)
            pixels = w.LPVOID()
            bitmap = create_dib(self.dc, c.byref(info), 0, c.byref(pixels), None, 0)
            if not bitmap or not pixels:
                raise OSError("Could not allocate overlay pixels.")
            previous = select_object(self.dc, bitmap)
            if self.bitmap:
                delete_object(self.bitmap)
            else:
                self.old = previous
            self.bitmap, self.pixels, self.size = bitmap, pixels, image.size
        # Layered windows require premultiplied alpha in BGRA byte order.
        pixels = image.convert("RGBa").tobytes("raw", "BGRa")
        c.memmove(self.pixels, pixels, len(pixels))

    def close(self):
        if self.bitmap:
            select_object(self.dc, self.old)
            delete_object(self.bitmap)
        delete_dc(self.dc)


class Overlay:
    def __init__(self):
        self.motion = Motion()
        self.proc = win.WNDPROC(self.handle_message)
        self.instance = win.get_module(None)
        self.area = (0, 0, 0, 0)
        self.target = None
        self.dpi = 96
        self.appearance = "dark"
        self.reduce = False
        self.visible = False
        self.surface = None
        self.window = None
        definition = win.WindowClass(proc=self.proc, instance=self.instance, name=NAME)
        if not win.register_class(c.byref(definition)):
            raise OSError("Could not register the status overlay.")
        try:
            # Layered, no activate, topmost, and tool window.
            self.window = win.create_window(
                0x08080088, NAME, "Luna Grammar status", 0x80000000, 0, 0, 0, 0,
                None, None, self.instance, None,
            )
            if not self.window:
                raise OSError("Could not create the status overlay.")
        except BaseException:
            self.close()
            raise

    def configure(self, target, settings):
        if not settings.feedback:
            self.motion.dismiss()
            self.hide()
            return False
        area = work_area(target)
        if self.area != area:
            self.hide()
            self.area = area
            # Place the hidden window on the target monitor before querying its own DPI.
            set_position(self.window, None, area[0] + 8, area[1] + 8, 1, 1, SWP_NOACTIVATE | 0x0004)
        self.target = target
        self.dpi = window_dpi(self.window) or 96
        self.appearance = settings.appearance
        self.reduce = reduced_motion(settings.motion)
        return True

    def show_state(self, state, label, target, settings):
        if not self.configure(target, settings):
            return
        now = time.monotonic()
        if state == "working":
            self.motion.begin(now, label or "Refining…")
        elif not self.motion.dismissed:
            self.motion.finish(state, label, now)
        kill_timer(self.window, 1)
        self.tick(now)
        if self.motion.state != "hidden":
            if not self.reduce:
                set_timer(self.window, 1, 16, None)
            elif state != "working":
                set_timer(self.window, 1, 2250 if state == "error" else 1100, None)

    def reset(self):
        self.motion = Motion()
        self.hide()

    def tick(self, now):
        frame = self.motion.sample(now, self.reduce)
        if frame is None:
            self.hide()
            return
        image = render(frame, self.dpi, self.appearance)
        if self.surface is None:
            self.surface = Surface()
        self.surface.write(image)
        x, y = pill_position(self.area, image.width, image.height, self.dpi, frame.offset)
        at, size, source = w.POINT(x, y), w.SIZE(*image.size), w.POINT(0, 0)
        blend = Blend(0, 0, round(frame.opacity * 255), 1)
        if not update_layer(self.window, None, c.byref(at), c.byref(size), self.surface.dc,
                            c.byref(source), 0, c.byref(blend), 2):
            raise OSError("Windows could not compose the status overlay.")
        if not self.visible:
            show_window(self.window, 4)  # SW_SHOWNOACTIVATE
            self.visible = True

    def hide(self):
        kill_timer(self.window, 1)
        if self.visible:
            show_window(self.window, 0)
            self.visible = False

    def handle_message(self, window, message, wparam, lparam):
        if message == WM_MOUSEACTIVATE:
            return 3  # MA_NOACTIVATE
        if message == WM_NCHITTEST:
            rect = w.RECT()
            if get_window_rect(window, c.byref(rect)):
                x = c.c_short(lparam & 0xFFFF).value
                y = c.c_short((lparam >> 16) & 0xFFFF).value
                s = self.dpi / 96
                if rect.right - 37*s <= x <= rect.right - 9*s and rect.top + 9*s <= y <= rect.bottom - 12*s:
                    return 1  # HTCLIENT
            return -1  # HTTRANSPARENT
        if message == WM_LBUTTONUP:
            self.motion.dismiss()
            self.hide()
            return 0
        if message in (WM_TIMER, WM_DPICHANGED):
            try:
                if message == WM_DPICHANGED:
                    self.dpi = wparam & 0xFFFF
                if self.visible or message == WM_TIMER:
                    self.tick(time.monotonic())
            except Exception:
                self.motion.dismiss()
                self.hide()
            return 0
        return win.default_proc(window, message, wparam, lparam)

    def close(self):
        if self.window:
            self.hide()
            win.destroy_window(self.window)
        if self.surface:
            self.surface.close()
        win.unregister_class(NAME, self.instance)
