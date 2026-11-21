"""Count selection-changing input while allowing ordinary pointer movement."""

import ctypes as c
from ctypes import wintypes as w
from threading import Event, Thread

import win32 as win
from config import AppError

HOOKPROC = c.WINFUNCTYPE(win.LRESULT, c.c_int, w.WPARAM, w.LPARAM)
KEY_DOWN = {0x0100, 0x0104}
MOUSE_ACTIONS = {0x0201, 0x0202, 0x0204, 0x0205, 0x0207, 0x0208, 0x020A,
                 0x020B, 0x020C, 0x020E}


class KeyboardEvent(c.Structure):
    _fields_ = [("key", w.DWORD), ("scan", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("extra", win.UINT_PTR)]


class MouseEvent(c.Structure):
    _fields_ = [("point", w.POINT), ("data", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("extra", win.UINT_PTR)]


install_hook = win.bind(win.user, "SetWindowsHookExW", w.HANDLE,
                        c.c_int, HOOKPROC, w.HINSTANCE, w.DWORD)
remove_hook = win.bind(win.user, "UnhookWindowsHookEx", w.BOOL, w.HANDLE)
next_hook = win.bind(win.user, "CallNextHookEx", win.LRESULT,
                     w.HANDLE, c.c_int, w.WPARAM, w.LPARAM)
thread_id = win.bind(win.kernel, "GetCurrentThreadId", w.DWORD)
post_thread = win.bind(win.user, "PostThreadMessageW", w.BOOL, w.DWORD, w.UINT, w.WPARAM, w.LPARAM)
peek = win.bind(win.user, "PeekMessageW", w.BOOL, c.POINTER(w.MSG), w.HWND,
                w.UINT, w.UINT, w.UINT)


class InputMonitor:
    def __init__(self):
        self.generation = 0
        self.ready = Event()
        self.stopped = Event()
        self.failure = None
        self.id = None
        self.thread = None
        self.keyboard_callback = HOOKPROC(self.keyboard)
        self.mouse_callback = HOOKPROC(self.mouse)

    def keyboard(self, code, message, pointer):
        if code >= 0 and message in KEY_DOWN:
            event = KeyboardEvent.from_address(pointer)
            if not (event.flags & 0x10 and event.extra == win.INPUT_TAG):
                self.generation += 1
        return next_hook(None, code, message, pointer)

    def mouse(self, code, message, pointer):
        if code >= 0 and message in MOUSE_ACTIONS:
            event = MouseEvent.from_address(pointer)
            if not (event.flags & 0x01 and event.extra == win.INPUT_TAG):
                self.generation += 1
        return next_hook(None, code, message, pointer)

    def stamp(self):
        if self.failure or self.stopped.is_set():
            raise AppError("The Windows input monitor is unavailable. Restart Luna.",
                           "Input monitor unavailable", "input.monitor_failed")
        return self.generation

    def run(self):
        hooks = []
        try:
            self.id = thread_id()
            message = w.MSG()
            peek(c.byref(message), None, 0, 0, 0)  # Create the thread message queue.
            for kind, callback in ((13, self.keyboard_callback), (14, self.mouse_callback)):
                hook = install_hook(kind, callback, win.get_module(None), 0)
                if not hook:
                    raise AppError("Could not monitor editing input.",
                                   "Input monitor unavailable", "input.registration_failed")
                hooks.append(hook)
            self.ready.set()
            while True:
                status = win.get_message(c.byref(message), None, 0, 0)
                if status <= 0:
                    if status < 0:
                        raise OSError("The input message loop failed.")
                    break
                win.dispatch_message(c.byref(message))
        except BaseException as error:
            self.failure = error
        finally:
            for hook in hooks:
                remove_hook(hook)
            self.stopped.set()
            self.ready.set()

    def __enter__(self):
        self.thread = Thread(target=self.run, name="luna-input-monitor", daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            if self.id:
                post_thread(self.id, 0x0012, 0, 0)
            raise AppError("The Windows input monitor did not become ready.",
                           "Input monitor unavailable", "input.registration_failed")
        if self.failure:
            self.thread.join()
            raise AppError("Could not initialize the Windows input monitor.",
                           "Input monitor unavailable", "input.registration_failed") from None
        win.editing_input_stamp = self.stamp
        return self

    def __exit__(self, *_error):
        if not self.stopped.is_set():
            post_thread(self.id, 0x0012, 0, 0)  # WM_QUIT
        self.thread.join(timeout=5)
        win.editing_input_stamp = None
        if self.thread.is_alive():
            raise AppError("The Windows input monitor did not stop in time.",
                           "Shutdown failed", "input.shutdown_failed")
