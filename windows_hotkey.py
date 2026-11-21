"""Single-instance listener and one worker for selection, network, and clipboard I/O."""

import ctypes as c
import logging
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from ctypes import wintypes as w
from queue import Empty, Queue, SimpleQueue
from threading import Event, Thread
from uuid import uuid4
from time import perf_counter_ns

import win32 as win
from clipboard_manager import Clipboard
from config import AppError, SETTINGS_PATH, app_command, independent_process_environment, load_settings, update_settings
import diagnostics
from diagnostics import error_frames, operation, timing, measure
from correction_modes import MODES, MODE_NAMES
from input_monitor import InputMonitor
from grammar_engine import GrammarEngine, RefinementCache
from text_selection import Automation, Guard, Selection, Trigger, capture, correct_selection
from undo_manager import get_last_undo, get_undo_manager
from tray import Tray, WM_TRAY


CLASS_NAME = "LunaGrammar.MessageWindow.v1"
MUTEX_NAME = r"Local\LunaGrammar.42a925fb-a52d-4177-9e45-dfbe72b351c2"
WM_STATUS = 0x8011
WM_RELOAD = 0x8012
WM_READY = 0x8013
WM_SHORTCUT = 0x8014


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
        self.pending_trigger = None
        self.shortcut_events = SimpleQueue()
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

    def shortcut_enabled(self):
        return self.registered and self.settings.enabled and not self.stop.is_set()

    def is_target_excluded(self, target):
        if not target or not getattr(self.settings, 'excluded_apps', None):
            return False
        excluded = {app.casefold() for app in self.settings.excluded_apps}
        try:
            exe = win.executable(target.pid)
            if exe in excluded:
                return True
        except Exception:
            pass
        if getattr(target, 'focus_pid', None):
            try:
                exe = win.executable(target.focus_pid)
                if exe in excluded:
                    return True
            except Exception:
                pass
        return False

    def shortcut_event(self, kind, level, started, timestamp):
        # Runs on the existing input-hook thread: queue only, never query UIA,
        # clipboard, target windows, render animations, or perform network I/O.
        self.shortcut_events.put((kind, level, started, timestamp, win.edit_input()))
        if not win.post_message(self.window, WM_SHORTCUT, 0, 0):
            self.request_stop()

    def dispatch_shortcut(self):
        while True:
            try:
                kind, level, started, timestamp, input_stamp = self.shortcut_events.get_nowait()
            except Empty:
                return
            if kind == 'start':
                if self.shortcut_enabled() and not self.busy.is_set():
                    target = win.current_target()
                    if target:
                        if self.is_target_excluded(target):
                            logging.debug("event=shortcut.excluded_app pid=%d", target.pid)
                            continue
                        self.busy.set()
                        self.pending_trigger = Trigger(target, self.epoch, uuid4().hex[:12],
                                                       timestamp, started_ns=started)
                continue
            pending, self.pending_trigger = self.pending_trigger, None
            if pending is None:
                continue
            if kind != 'commit' or not self.shortcut_enabled() or self.is_target_excluded(pending.target):
                self.busy.clear()
                continue

            if level == 'undo':
                mode_name = 'undo'
                mode_badge = 'Undo'
                mode_label = 'Reverting…'
            elif isinstance(level, int) and 0 <= level < len(MODE_NAMES):
                mode_name = MODE_NAMES[level]
                mode_obj = MODES.get(mode_name)
                mode_badge = getattr(mode_obj, 'name', mode_name.capitalize()) if mode_obj else mode_name.capitalize()
                mode_label = mode_obj.label if mode_obj else 'Refining…'
            elif isinstance(level, str) and level in MODES:
                mode_name = level
                mode_obj = MODES.get(mode_name)
                mode_badge = getattr(mode_obj, 'name', mode_name.capitalize()) if mode_obj else mode_name.capitalize()
                mode_label = mode_obj.label if mode_obj else 'Refining…'
            else:
                default_idx = getattr(self.settings, 'default_mode', 0)
                if not (isinstance(default_idx, int) and 0 <= default_idx < len(MODE_NAMES)):
                    default_idx = 0
                mode_name = MODE_NAMES[default_idx]
                mode_obj = MODES.get(mode_name)
                mode_badge = getattr(mode_obj, 'name', mode_name.capitalize()) if mode_obj else mode_name.capitalize()
                mode_label = mode_obj.label if mode_obj else 'Refining…'

            trigger = replace(pending, mode=mode_name, input_stamp=input_stamp)
            self.active_trigger = trigger
            token = operation.set(trigger.operation_id)
            try:
                timing('shortcut_commit_dispatch', started)
                if trigger.started_ns:
                    timing('shortcut_hold_and_dispatch', trigger.started_ns)
            finally:
                operation.reset(token)
            if self.overlay:
                self.overlay.reset()
                # Start feedback on the message thread before the worker begins
                # capture/network work; this also handles a busy worker queue.
                self.ui_events.put((trigger, 'working', mode_label, None, False, mode_badge))
                self.update_overlay()
            self.jobs.put_nowait(trigger)

    def handle_focus(self, _hook, event, window, _object, _child, _thread, timestamp):
        trigger = self.pending_trigger or self.active_trigger
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

    def status(self, trigger, state, label="", diff_summary=None, cached=False, mode_name=None):
        if self.overlay and self.settings.feedback and not self.stop.is_set():
            self.ui_events.put((trigger, state, label, diff_summary, cached, mode_name))
            win.post_message(self.window, WM_STATUS, 0, 0)

    def update_overlay(self):
        try:
            event = self.ui_events.get_nowait()
        except Empty:
            return
        trigger, state, label = event[0], event[1], event[2]
        diff_summary = event[3] if len(event) > 3 else None
        cached = event[4] if len(event) > 4 else False
        mode_name = event[5] if len(event) > 5 else None
        if self.overlay and trigger is self.active_trigger and not self.stop.is_set():
            try:
                with measure('ui_feedback'):
                    if state == 'working' and getattr(self.overlay.motion, 'state', None) == 'working':
                        return  # Do not restart the entry fade for worker progress.
                    self.overlay.show_state(
                        state, label, trigger.target.window, self.settings,
                        diff_summary=diff_summary, cached=cached, mode_name=mode_name,
                    )
            except Exception as error:
                logging.warning('event=overlay.feedback_failed type=%s frames=%s',
                                type(error).__name__, error_frames(error))
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
        if message == WM_SHORTCUT:
            self.dispatch_shortcut()
            return 0
        if message == win.WM_HOTKEY and wparam == win.HOTKEY_ID:
            # RegisterHotKey retains the OS reservation/conflict check. Only
            # the hook's completed chord can enqueue work, never WM_HOTKEY.
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
                    logging.debug("event=operation.started mode=%s", trigger.mode)
                    settings = self.settings

                    if trigger.mode == "undo":
                        with measure('undo_pipeline'):
                            record = get_last_undo(trigger.target.pid)
                            if record is None:
                                record = get_last_undo(None)
                            if record is None:
                                self.status(trigger, "error", "Nothing to undo")
                                continue
                            selection = None
                            try:
                                selection = capture(
                                    trigger, lambda: self.epoch, self.stop, settings,
                                    automation, self.clipboard,
                                )
                            except Exception:
                                pass
                            if selection is None:
                                guard = Guard(trigger, lambda: self.epoch, self.stop, win.edit_input())
                                selection = Selection(text=record.refined_text, guard=guard, keyboard_copy=False)
                            selection.replace_with_keyboard(
                                record.original_text, self.clipboard, automation, settings.max_selection_chars,
                            )
                            diff_summary = record.diff.summary if getattr(settings, 'show_diff_preview', True) else None
                            self.status(trigger, "undo", "Reverted", diff_summary=diff_summary, mode_name="Undo")
                            logging.debug("event=operation.finished result=undo")
                        continue

                    engine.configure(settings)
                    mode_obj = MODES.get(trigger.mode)
                    mode_label = mode_obj.label if mode_obj else "Refining…"
                    mode_badge = getattr(mode_obj, "name", trigger.mode.capitalize()) if mode_obj else trigger.mode.capitalize()
                    with measure('correction_pipeline'):
                        result = correct_selection(
                            trigger, lambda: self.epoch, self.stop, settings,
                            automation, self.clipboard, engine,
                            progress=lambda: self.status(trigger, "working", mode_label, mode_name=mode_badge),
                        )
                    diff_summary = getattr(result, "diff_summary", None) if getattr(settings, "show_diff_preview", True) else None
                    cached = getattr(result, "cached", False) or diagnostics.is_cache_hit()
                    if result in ("success", "unchanged"):
                        self.status(
                            trigger,
                            result,
                            "Refined" if result == "success" else "Already refined",
                            diff_summary=diff_summary,
                            cached=cached,
                            mode_name=mode_badge,
                        )
                    elif result == 'empty':
                        self.status(trigger, 'error', 'Select some text')
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

        with single_instance(), InputMonitor(self.shortcut_event, self.shortcut_enabled):
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
