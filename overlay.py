"""A per-monitor, nonactivating Win32 layered window for the Luna capsule."""

import ctypes as c
import logging
import time
from ctypes import wintypes as w
from threading import Timer

import win32 as win
from diagnostics import error_frames
from pill_art import Motion, pill_position, render

HDC = w.HDC
P = c.POINTER
NAME = "LunaGrammar.StatusPill.v2"
WM_TIMER = 0x0113
WM_DPICHANGED = 0x02E0
WM_MOUSEACTIVATE = 0x0021
WM_NCHITTEST = 0x0084
WM_LBUTTONUP = 0x0202
WM_DISMISS = 0x8015
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1


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
client_to_screen = win.bind(win.user, "ClientToScreen", w.BOOL, w.HWND, P(w.POINT))


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


def active_caret_position(target):
    """Retrieve the screen position of the active text caret if accessible."""
    if not target:
        return None
    try:
        pid = w.DWORD()
        tid = win.get_window_thread(target, c.byref(pid))
        if not tid:
            return None
        gui = win.GuiThreadInfo(size=c.sizeof(win.GuiThreadInfo))
        if not win.get_gui_info(tid, c.byref(gui)):
            return None
        caret_wnd = gui.caret or gui.focus
        r = gui.caret_rect
        if caret_wnd and (r.right > r.left or r.bottom > r.top):
            pt = w.POINT(r.left, r.bottom)
            if client_to_screen(caret_wnd, c.byref(pt)):
                if pt.x != 0 or pt.y != 0:
                    return pt.x, pt.y
    except Exception:
        pass
    return None


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
        self.animation_failed = False
        self.dismiss_timer = None
        self.dismiss_generation = 0
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

    def configure(self, target=None, settings=None):
        if settings is None:
            from config import Settings
            settings = Settings()
        if target is None:
            target = self.target or win.foreground()
        if not settings.feedback:
            self.motion.dismiss()
            self.hide()
            return False
        area = work_area(target)
        if self.area != area:
            self.hide()
            self.area = area
            # Place the hidden window on the target monitor before querying its own DPI.
            if not set_position(self.window, None, area[0] + 8, area[1] + 8, 1, 1,
                                SWP_NOACTIVATE | 0x0004):
                raise c.WinError(c.get_last_error())
        self.target = target
        self.dpi = window_dpi(self.window) or 96
        self.appearance = settings.appearance
        self.reduce = self.animation_failed or reduced_motion(settings.motion)
        return True

    def start_working(self, mode_name="Grammar", target=None, settings=None):
        """Display smooth waveform working state with mode badge."""
        if not self.configure(target, settings):
            return
        now = time.monotonic()
        self.motion.begin(now, label="Refining…", mode_badge=mode_name or "Grammar")
        self.cancel_timers()
        self.paint(now)
        if self.motion.state != "hidden":
            self.present()
        self.schedule()

    def show_success(self, message="Refined", diff_summary=None, cached=False, target=None, settings=None, mode_name=None):
        """Display success state with checkmark, diff summary badge, and cache badge."""
        if not self.configure(target, settings):
            return
        now = time.monotonic()
        if not self.motion.dismissed:
            self.motion.finish("success", message or "Refined", now,
                               diff_badge=diff_summary or "", cached=cached, mode_badge=mode_name)
        self.cancel_timers()
        self.paint(now)
        if self.motion.state != "hidden":
            self.present()
        self.schedule()

    def show_undo(self, message="Reverted", diff_summary=None, target=None, settings=None):
        """Display undo/revert state with return arrow and diff summary."""
        if not self.configure(target, settings):
            return
        now = time.monotonic()
        if not self.motion.dismissed:
            self.motion.finish("undo", message or "Reverted", now,
                               diff_badge=diff_summary or "", mode_badge="Undo")
        self.cancel_timers()
        self.paint(now)
        if self.motion.state != "hidden":
            self.present()
        self.schedule()

    def show_error(self, err_msg="Couldn’t refine", target=None, settings=None):
        """Display error state with warning badge."""
        if not self.configure(target, settings):
            return
        now = time.monotonic()
        if not self.motion.dismissed:
            self.motion.finish("error", err_msg or "Couldn’t refine", now)
        self.cancel_timers()
        self.paint(now)
        if self.motion.state != "hidden":
            self.present()
        self.schedule()

    def show_state(self, state, label, target=None, settings=None, diff_summary=None, cached=False, mode_name=None):
        if not self.configure(target, settings):
            return
        now = time.monotonic()
        if state == "working":
            badge = mode_name or (label if label and label != "Refining…" else "")
            self.motion.begin(now, label or "Refining…", mode_badge=badge)
        elif state == "undo":
            if not self.motion.dismissed:
                self.motion.finish("undo", label or "Reverted", now,
                                   diff_badge=diff_summary or "", mode_badge=mode_name or "Undo")
        elif not self.motion.dismissed:
            self.motion.finish(state, label, now, diff_badge=diff_summary or "",
                               cached=cached, mode_badge=mode_name)
        self.cancel_timers()
        self.paint(now)
        if self.motion.state != "hidden":
            self.present()
        self.schedule()

    def schedule(self):
        if self.motion.state != "hidden":
            if not self.reduce:
                if set_timer(self.window, 1, 16, None):
                    return
                logging.warning('event=overlay.timer_failed windows_error=%d', c.get_last_error())
                self.animation_failed = self.reduce = True
                self.paint(time.monotonic())
            if self.motion.state not in ('hidden', 'working'):
                hold = 2.25 if self.motion.state == 'error' else 1.10
                delay = max(.001, self.motion.finished + hold - time.monotonic())
                if not set_timer(self.window, 1, max(1, round(delay * 1000)), None):
                    # Keep Windows calls on the UI thread, even if Windows cannot
                    # allocate an animation timer. Reject stale dismiss messages.
                    generation = self.dismiss_generation
                    window = self.window
                    self.dismiss_timer = Timer(delay, win.post_message,
                                               args=(window, WM_DISMISS, generation, 0))
                    self.dismiss_timer.daemon = True
                    self.dismiss_timer.start()

    def cancel_timers(self):
        kill_timer(self.window, 1)
        self.dismiss_generation += 1
        if self.dismiss_timer:
            self.dismiss_timer.cancel()
            self.dismiss_timer = None

    def paint(self, now):
        try:
            self.tick(now)
        except Exception as error:
            logging.warning('event=overlay.animation_failed type=%s frames=%s',
                            type(error).__name__, error_frames(error))
            self.cancel_timers()
            self.animation_failed = self.reduce = True
            try:
                self.tick(now)
            except Exception as fallback_error:
                logging.warning('event=overlay.render_failed type=%s frames=%s',
                                type(fallback_error).__name__, error_frames(fallback_error))
                self.motion.dismiss()
                self.hide()

    def present(self):
        # WS_EX_TOPMOST at creation does not raise a hidden window above topmost
        # windows created/activated later. Raise each new status without focus.
        if not set_position(self.window, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOACTIVATE | 0x0001 | 0x0002 | 0x0040):
            raise c.WinError(c.get_last_error())
        self.visible = True

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

        caret_pos = None
        if self.target:
            pos = active_caret_position(self.target)
            if pos:
                cx, cy = pos
                if self.area[0] <= cx <= self.area[2] and self.area[1] <= cy <= self.area[3]:
                    caret_pos = pos

        x, y = pill_position(self.area, image.width, image.height, self.dpi, frame.offset, caret=caret_pos)
        at, size, source = w.POINT(x, y), w.SIZE(*image.size), w.POINT(0, 0)
        blend = Blend(0, 0, round(frame.opacity * 255), 1)
        if not update_layer(self.window, None, c.byref(at), c.byref(size), self.surface.dc,
                            c.byref(source), 0, c.byref(blend), 2):
            raise OSError("Windows could not compose the status overlay.")
        if not self.visible:
            self.present()

    def hide(self):
        self.cancel_timers()
        if self.visible:
            show_window(self.window, 0)
            self.visible = False

    def handle_message(self, window, message, wparam, lparam):
        if message == WM_DISMISS:
            if wparam == self.dismiss_generation and self.motion.state not in ('hidden', 'working'):
                # Automatic expiry is different from the user's close button:
                # later feedback may still arrive for this operation.
                self.motion.state = 'hidden'
                self.hide()
            return 0
        if message == WM_MOUSEACTIVATE:
            return 3  # MA_NOACTIVATE
        if message == WM_NCHITTEST:
            rect = w.RECT()
            if get_window_rect(window, c.byref(rect)):
                x = c.c_short(lparam & 0xFFFF).value
                y = c.c_short((lparam >> 16) & 0xFFFF).value
                s = self.dpi / 96
                if rect.right - 37 * s <= x <= rect.right - 9 * s and rect.top + 9 * s <= y <= rect.bottom - 12 * s:
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
                    was_reduced = self.reduce
                    self.paint(time.monotonic())
                    if self.reduce and not was_reduced:
                        self.schedule()
            except Exception as error:
                logging.warning('event=overlay.message_failed type=%s frames=%s',
                                type(error).__name__, error_frames(error))
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


def check_overlay():
    """Verify real rendering/timers/z-order from source or the packaged runtime.

    Uses only a public status label and never reads document or clipboard data.
    """
    from correction_modes import MODES
    from config import Settings

    set_dpi_context(-4)
    pill = Overlay()
    target = win.foreground()
    visible = win.bind(win.user, 'IsWindowVisible', w.BOOL, w.HWND)
    get_top = win.bind(win.user, 'GetTopWindow', w.HWND, w.HWND)
    get_window = win.bind(win.user, 'GetWindow', w.HWND, w.HWND, w.UINT)
    peek = win.bind(win.user, 'PeekMessageW', w.BOOL, P(w.MSG), w.HWND,
                    w.UINT, w.UINT, w.UINT)
    cover = None
    verified = 0

    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            message = w.MSG()
            while peek(c.byref(message), None, 0, 0, 1):
                win.dispatch_message(c.byref(message))
            time.sleep(.005)

    try:
        area = work_area(target)
        # A tiny nonactivating topmost test window reproduces the z-order
        # condition without covering the user's work surface.
        cover = win.create_window(0x08000088, 'Static', 'Luna overlay check', 0x90000000,
                                  area[0], area[1], 1, 1, None, None, win.get_module(None), None)
        if not cover:
            raise c.WinError(c.get_last_error())
        for mode in MODES.values():
            pill.reset()
            before = win.foreground()
            pill.show_state('working', mode.label, target, Settings())
            if win.foreground() != before:
                raise OSError('The overlay changed foreground focus.')
            pump(.35)
            frame = pill.motion.sample(time.monotonic(), pill.reduce)
            if not visible(pill.window) or not frame or frame.opacity < .95 or frame.label != mode.label:
                raise OSError('The working overlay did not become visible.')
            order = []
            candidate = get_top(None)
            while candidate:
                order.append(candidate)
                candidate = get_window(candidate, 2)
            if order.index(pill.window) >= order.index(cover):
                raise OSError('The overlay was covered by a topmost window.')
            pill.show_state('success', 'Refined', target, Settings())
            pump(.3)
            if not visible(pill.window):
                raise OSError('Success feedback was not visible.')
            pump(1.2)
            if visible(pill.window):
                raise OSError('Success feedback did not dismiss.')
            verified += 1

        pill.show_state('error', 'Connection issue', target, Settings())
        pump(.3)
        if not visible(pill.window):
            raise OSError('Error feedback was not visible.')
        pump(2.4)
        if visible(pill.window):
            raise OSError('Error feedback did not dismiss.')

        # Verify new states: show_undo and show_success with diff & cache
        pill.show_undo('Reverted', diff_summary='-3 words', target=target, settings=Settings())
        pump(.3)
        if not visible(pill.window):
            raise OSError('Undo feedback was not visible.')
        pump(1.2)
        if visible(pill.window):
            raise OSError('Undo feedback did not dismiss.')

        pill.show_success('Refined', diff_summary='+5 / -2 words', cached=True, target=target, settings=Settings())
        pump(.3)
        if not visible(pill.window):
            raise OSError('Success with diff feedback was not visible.')
        pump(1.2)
        if visible(pill.window):
            raise OSError('Success with diff feedback did not dismiss.')

        return verified
    finally:
        pill.close()
        if cover:
            win.destroy_window(cover)
