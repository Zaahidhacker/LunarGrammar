"""Single-instance listener and one worker for selection, network, and clipboard I/O."""

import ctypes as c
import logging
import subprocess
from contextlib import contextmanager
from ctypes import wintypes as w
from queue import Empty, Queue, SimpleQueue
from threading import Event, Thread
from uuid import uuid4

import win32 as win
from clipboard_manager import Clipboard
from config import AppError, SETTINGS_PATH, app_command, independent_process_environment, load_settings, update_settings
from diagnostics import error_frames, operation
from input_monitor import InputMonitor
from grammar_engine import GrammarEngine
from text_selection import Automation, Trigger, correct_selection
from tray import Tray, WM_TRAY


CLASS_NAME = "LunaGrammar.MessageWindow.v1"
MUTEX_NAME = r"Local\LunaGrammar.42a925fb-a52d-4177-9e45-dfbe72b351c2"
WM_STATUS = 0x8011
WM_RELOAD = 0x8012
WM_READY = 0x8013


def register(window=None):
    if not win.register_hotkey(window, win.HOTKEY_ID, win.HOTKEY_MODIFIERS, win.HOTKEY_KEY):
        error = c.get_last_error()
        raise AppError(
            f"Could not register Ctrl+Win+Z (Windows error {error}). "
            "It may already be in use by Windows, Luna Grammar, or another application.",
            "Shortcut unavailable", "hotkey.registration_failed",
        )


def check_hotkey():
    register()
    win.unregister_hotkey(None, win.HOTKEY_ID)


@contextmanager
def single_instance():
    c.set_last_error(0)
    mutex = win.create_mutex(None, False, MUTEX_NAME)
    error = c.get_last_error()
    if not mutex:
        raise AppError(f"Could not open the Luna Grammar instance lock (Windows error {error}).")
    try:
        if error == 183:  # ERROR_ALREADY_EXISTS
            raise AppError("Luna Grammar is already running. Quit it from the notification area first.",
                           "Already running", "startup.duplicate")
        yield
    finally:
        win.close_handle(mutex)


def stop_listener():
    window = find_listener()
    if not window:
        return False
    if not win.post_message(window, win.WM_CLOSE, 0, 0):
        raise AppError("Could not ask Luna Grammar to stop.")
    return True


def find_listener():
    return (win.find_window(None, None, CLASS_NAME, None)
            or win.find_window(win.HWND_MESSAGE, None, CLASS_NAME, None))


def reload_listener():
    window = find_listener()
    return bool(window and win.post_message(window, WM_RELOAD, 0, 0))


class Listener:
    def __init__(self, settings, key):
        self.settings = settings
        self.key = key
        self.epoch = 0
        self.ready = Event()
        self.stop = Event()
        self.busy = Event()
        self.jobs = Queue()
        self.ui_events = SimpleQueue()
        self.active_trigger = None
        self.failed = False
        self.clipboard = None
        self.window = None
        self.overlay = None
        self.tray = None
        self.settings_process = None
        self.registered = False
        self.window_proc = win.WNDPROC(self.handle_message)
        self.event_proc = win.WIN_EVENT(self.handle_focus)
        self.console_proc = win.CONSOLE_HANDLER(self.handle_console)

    def handle_focus(self, _hook, event, window, _object, _child, _thread, timestamp):
        trigger = self.active_trigger
        if self.busy.is_set() and trigger and trigger.message_time is not None:
            # Out-of-context WinEvents can arrive after a newer WM_HOTKEY.
            if (timestamp - trigger.message_time) & 0x80000000:
                return
        # Ignore accessibility notifications from applications in the background.
        if event == 0x0003 or (window and win.window_pid(window) == win.window_pid(win.foreground())):
            self.epoch += 1

    def handle_console(self, event):
        return event in (0, 1) and bool(win.post_message(self.window, win.WM_CLOSE, 0, 0))

    def request_stop(self):
        if not self.stop.is_set():
            self.stop.set()
            self.jobs.put_nowait(None)

    def status(self, trigger, state, label=""):
        if self.overlay and self.settings.feedback and not self.stop.is_set():
            self.ui_events.put((trigger, state, label))
            win.post_message(self.window, WM_STATUS, 0, 0)

    def update_overlay(self):
        try:
            trigger, state, label = self.ui_events.get_nowait()
        except Empty:
            return
        if self.overlay and trigger is self.active_trigger and not self.stop.is_set():
            try:
                self.overlay.show_state(state, label, trigger.target.window, self.settings)
            except Exception as error:
                logging.debug("Overlay unavailable (%s).", type(error).__name__)
                self.overlay.reset()

    def reload(self):
        settings = load_settings(SETTINGS_PATH)
        self.settings = settings
        if not settings.enabled and self.registered:
            self.epoch += 1
            win.unregister_hotkey(self.window, win.HOTKEY_ID)
            self.registered = False
            logging.info("Luna Grammar is paused.")
        elif settings.enabled and not self.registered and self.ready.is_set():
            register(self.window)
            self.registered = True
            logging.info("Luna Grammar resumed on Ctrl+Win+Z.")
        if self.overlay and (not settings.feedback or not settings.enabled):
            self.overlay.reset()
            self.active_trigger = None
        if self.tray:
            self.tray.update(self.registered)

    def open_settings(self):
        if self.settings_process is None or self.settings_process.poll() is not None:
            self.settings_process = subprocess.Popen(
                app_command("--settings"),
                creationflags=subprocess.CREATE_NO_WINDOW,
                # A one-file executable launched as a standalone instance must
                # unpack independently so it can outlive the listener.
                env=independent_process_environment(),
            )

    def tray_event(self, wparam, lparam):
        event = lparam & 0xFFFF
        if event in (0x0400, 0x0401):  # NIN_SELECT, NIN_KEYSELECT
            self.open_settings()
        elif event == 0x007B:  # WM_CONTEXTMENU
            x = c.c_short(wparam & 0xFFFF).value
            y = c.c_short((wparam >> 16) & 0xFFFF).value
            command = self.tray.menu((x, y) if (x, y) != (-1, -1) else None)
            if command == 1:
                update_settings({"enabled": not self.registered})
                self.reload()
            elif command == 2:
                self.open_settings()
            elif command == 3:
                self.request_stop()

    def handle_message(self, window, message, wparam, lparam):
        if message == win.WM_HOTKEY and wparam == win.HOTKEY_ID:
            if (self.settings.enabled and self.ready.is_set()
                    and not self.stop.is_set() and not self.busy.is_set()):
                target = win.current_target()
                if target:
                    self.busy.set()
                    self.active_trigger = Trigger(
                        target, self.epoch, uuid4().hex[:12], win.get_message_time() & 0xFFFFFFFF,
                    )
                    if self.overlay:
                        self.overlay.reset()
                    self.jobs.put_nowait(self.active_trigger)
                else:
                    logging.debug("event=hotkey.no_target")
            return 0
        if message == win.WM_RENDERFORMAT and self.clipboard:
            token = operation.set(self.active_trigger.operation_id if self.active_trigger else "-")
            try:
                self.clipboard.render(wparam)
            except Exception as error:
                logging.warning("event=clipboard.render_failed type=%s", type(error).__name__)
            finally:
                operation.reset(token)
            return 0
        if message == win.WM_CLOSE:
            self.request_stop()
            return 0
        if message == WM_READY:
            if not self.stop.is_set():
                try:
                    if self.settings.enabled:
                        register(self.window)
                        self.registered = True
                    self.ready.set()
                    if self.tray:
                        self.tray.update(self.registered)
                    logging.info("Luna Grammar is listening on Ctrl+Win+Z." if self.registered else
                                 "Luna Grammar started paused. Resume it from the tray.")
                except AppError as error:
                    self.failed = True
                    logging.error("event=%s detail=%s", error.code, error)
                    self.request_stop()
            return 0
        if message == WM_STATUS:
            self.update_overlay()
            return 0
        if message in (WM_RELOAD, WM_TRAY) or (self.tray and message == self.tray.created_message):
            try:
                if message == WM_RELOAD:
                    self.reload()
                elif self.tray:
                    if message == WM_TRAY:
                        self.tray_event(wparam, lparam)
                    else:
                        self.tray.add()
            except AppError as error:
                logging.info("%s", error)
            except Exception as error:
                logging.warning("Windows settings action failed (%s).", type(error).__name__)
            return 0
        if message == win.WM_WORKER_STOPPED:
            win.post_quit(int(self.failed))
            return 0
        return win.default_proc(window, message, wparam, lparam)

    def worker(self):
        engine = None
        automation = None
        comtypes = None
        initialized = False
        try:
            # The main thread imports comtypes first, so this worker owns exactly one COM init.
            import comtypes

            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            initialized = True
            try:
                automation = Automation()
            except Exception as error:
                logging.warning("event=startup.uia_unavailable type=%s",
                                type(error).__name__)
            engine = GrammarEngine(self.settings, self.key)
            self.key = None
            if not win.post_message(self.window, WM_READY, 0, 0):
                raise AppError("Could not signal that the correction worker is ready.")
            while not self.stop.is_set():
                trigger = self.jobs.get()
                if trigger is None or self.stop.is_set():
                    break
                token = operation.set(trigger.operation_id)
                try:
                    logging.debug("event=operation.started")
                    settings = self.settings
                    engine.configure(settings)
                    result = correct_selection(
                        trigger, lambda: self.epoch, self.stop, settings,
                        automation, self.clipboard, engine,
                        progress=lambda: self.status(trigger, "working"),
                    )
                    if result in ("success", "unchanged"):
                        self.status(trigger, result, "Refined" if result == "success" else "Already refined")
                    logging.debug("event=operation.finished result=%s", result)
                except AppError as error:
                    logging.info("event=operation.failed category=%s status=%r detail=%s",
                                 error.code or "correction.rejected", error.status, error)
                    self.status(trigger, "error", error.status)
                except Exception as error:
                    logging.warning("event=operation.unexpected_failure type=%s", type(error).__name__)
                    self.status(trigger, "error", "Couldn’t refine")
                finally:
                    operation.reset(token)
                    self.busy.clear()
        except AppError as error:
            self.failed = True
            logging.error("%s", error)
        except Exception as error:
            self.failed = True
            logging.error("Luna Grammar could not start (%s). Run --check.", type(error).__name__)
            logging.debug("event=startup.unexpected_failure frames=%s", error_frames(error))
        finally:
            try:
                if engine:
                    engine.close()
            finally:
                try:
                    automation = None
                    if initialized:
                        comtypes.CoUninitialize()
                finally:
                    win.post_message(self.window, win.WM_WORKER_STOPPED, 0, 0)

    def run(self):
        try:
            import comtypes  # noqa: F401. First import initializes COM on this thread.
        except ImportError:
            raise AppError("Install the dependencies with pip install -r requirements.txt.") from None

        with single_instance(), InputMonitor():
            try:
                from overlay import Overlay, set_dpi_context

                set_dpi_context(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
                self.overlay = Overlay()
            except Exception as error:
                logging.warning("Visual feedback unavailable (%s).", type(error).__name__)
            instance = win.get_module(None)
            definition = win.WindowClass(proc=self.window_proc, instance=instance, name=CLASS_NAME)
            if not win.register_class(c.byref(definition)):
                if self.overlay:
                    self.overlay.close()
                raise AppError("Could not register the hidden Luna Grammar window class.")
            hooks = []
            console = False
            worker = None
            try:
                self.window = win.create_window(
                    0x80, CLASS_NAME, CLASS_NAME, 0, 0, 0, 0, 0, None, None, instance, None,
                )
                if not self.window:
                    raise AppError("Could not create the hidden Luna Grammar window.")
                self.clipboard = Clipboard(self.window)
                try:
                    self.tray = Tray(self.window, self.registered)
                except OSError as error:
                    logging.warning("%s", error)
                for event in (0x0003, 0x8005):  # EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_FOCUS
                    hook = win.set_event_hook(event, event, None, self.event_proc, 0, 0, 0x0002)
                    if not hook:
                        raise AppError("Could not watch for Windows focus changes.")
                    hooks.append(hook)
                console = win.set_console_handler(self.console_proc, True)
                thread = Thread(target=self.worker, name="luna-grammar-worker")
                thread.start()
                worker = thread
                message = w.MSG()
                while True:
                    result = win.get_message(c.byref(message), None, 0, 0)
                    if result == 0:
                        return int(message.wParam)
                    if result == -1:
                        raise AppError("The Windows hotkey message loop failed.")
                    win.dispatch_message(c.byref(message))
            finally:
                self.request_stop()
                if worker:
                    worker.join()
                if console:
                    win.set_console_handler(self.console_proc, False)
                for hook in hooks:
                    win.unhook_event(hook)
                if self.registered:
                    win.unregister_hotkey(self.window, win.HOTKEY_ID)
                if self.tray:
                    self.tray.close()
                if self.overlay:
                    self.overlay.close()
                if self.window:
                    win.destroy_window(self.window)
                win.unregister_class(CLASS_NAME, instance)
