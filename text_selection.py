"""Capture the current editable selection and fail closed if its target changes."""

import logging
import os
import time
from dataclasses import dataclass
from threading import Event
from typing import Callable

import win32 as win
from config import AppError
import diagnostics
from diagnostics import measure
from undo_manager import compute_text_diff, record_replacement


BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
            "chromium.exe", "opera.exe", "vivaldi.exe", "arc.exe",
            "tor.exe", "waterfox.exe"}

EDITORS = {
    # Office & Document editors
    "winword.exe", "outlook.exe", "powerpnt.exe", "excel.exe", "onenote.exe",
    "wordpad.exe", "soffice.bin", "wps.exe", "notepad.exe",
    # Messaging & Social
    "whatsapp.exe", "telegram.exe", "slack.exe", "discord.exe", "teams.exe",
    "ms-teams.exe", "skype.exe", "signal.exe",
    # Code editors & IDEs
    "code.exe", "sublime_text.exe", "notepad++.exe", "devenv.exe",
    "idea64.exe", "pycharm64.exe", "webstorm64.exe", "clion64.exe",
    "rider64.exe", "studio64.exe", "eclipse.exe",
    # Terminals
    "windowsterminal.exe", "conhost.exe", "cmd.exe", "powershell.exe",
    # Python & runtime scratch tools
    "python.exe", "pythonw.exe",
}

EDITOR_CLASSES = {
    "_wwg", "netuihwnd", "rich_edit",
    "scintilla", "px_window_class", "sunawtframe", "sunawtdialog",
    "windows.ui.core.corewindow", "applicationframewindow", "winuidesktopwin32windowclass",
    "chrome_widgetwin_1", "chrome_renderwidgethosthwnd",
    "qt5qwindowicon", "qt6qwindowicon", "qwidget",
}


def is_editor_target(target: win.Target, focus_class: str, executable: str,
                     element: object, automation: object) -> bool:
    if executable in EDITORS or executable in BROWSERS:
        return True
    if focus_class in EDITOR_CLASSES or any(cls in focus_class for cls in ("edit", "richedit", "scintilla", "text", "term", "hwndwrapper")):
        return True
    if element and automation:
        try:
            types = automation.types
            if element.CurrentControlType in (
                types.UIA_EditControlTypeId, types.UIA_DocumentControlTypeId,
                types.UIA_TextControlTypeId, types.UIA_CustomControlTypeId,
                types.UIA_PaneControlTypeId, types.UIA_GroupControlTypeId,
            ):
                for pid_name in ("UIA_TextPatternId", "UIA_TextPattern2Id", "UIA_ValuePatternId", "UIA_TextEditPatternId"):
                    pid = getattr(types, pid_name, None)
                    if pid is not None and element.GetCurrentPattern(pid):
                        return True
        except Exception:
            pass
    return False


# Windows can stamp injected key releases on a later system-clock tick.
SYNTHETIC_INPUT_WINDOW_MS = 32


def sanitize_text(text: str) -> str:
    """Normalize soft breaks, object placeholders, surrogates, and control chars."""
    if not isinstance(text, str) or not text:
        return text
    # Convert vertical tab (Shift+Enter in Word/WordPad) and form feed to newline
    text = text.replace("\x0b", "\n").replace("\x0c", "\n")
    # Replace object replacement character (inline emojis, mentions, badges) with space
    text = text.replace("\ufffc", " ").replace("\x00", "")
    # Clean up unpaired surrogates
    text = text.encode("utf-16", errors="surrogatepass").decode("utf-16", errors="replace")
    # Keep printable characters, tab, LF, CR, and Unicode
    text = "".join(char for char in text if ord(char) >= 32 or char in "\t\r\n")
    return text


class RangeUnavailable(AppError):
    """The provider could not establish a selection; another method may work."""


class Automation:
    def __init__(self):
        from comtypes import COMError
        from comtypes.client import CreateObject, GetModule

        self.com_error = COMError
        self.types = GetModule(os.path.join(os.environ["SystemRoot"], "System32", "UIAutomationCore.dll"))
        self.client = CreateObject(self.types.CUIAutomation8, interface=self.types.IUIAutomation2)
        self.client.ConnectionTimeout = 500
        self.client.TransactionTimeout = 600

    def focused_element(self, target: win.Target):
        element = self.client.GetFocusedElement()
        if element:
            if not target.contains_process(element.CurrentProcessId):
                raise AppError("Accessibility reported focus in a different application.", "Target changed")
            if element.CurrentIsPassword or not element.CurrentIsEnabled:
                raise AppError("The focused field is protected or unavailable.", "Protected field")
        return element

    def focused_edit(self, target: win.Target):
        element = self.focused_element(target)
        eligible = (
            self.types.UIA_EditControlTypeId, self.types.UIA_DocumentControlTypeId,
            self.types.UIA_CustomControlTypeId, self.types.UIA_GroupControlTypeId,
            self.types.UIA_PaneControlTypeId,
        )
        # Browser accessibility providers sometimes put the text pattern on the editing host
        # and expose focus on a child. Accept an ancestor only if it owns the active caret.
        owner = element
        for depth in range(4):
            if not owner or not target.contains_process(owner.CurrentProcessId):
                break
            if owner.CurrentIsPassword or not owner.CurrentIsEnabled:
                raise AppError("The focused field is protected or unavailable.", "Protected field")
            if owner.CurrentControlType in eligible:
                if depth == 0:
                    pattern = owner.GetCurrentPattern(self.types.UIA_TextPatternId)
                    if pattern:
                        return element, owner, pattern.QueryInterface(self.types.IUIAutomationTextPattern), None
                pattern = owner.GetCurrentPattern(self.types.UIA_TextPattern2Id)
                if pattern:
                    text = pattern.QueryInterface(self.types.IUIAutomationTextPattern2)
                    active, caret = text.GetCaretRange()
                    if active and caret:
                        return element, owner, text, caret
            owner = self.client.ControlViewWalker.GetParentElement(owner)
        return element, None, None, None

    def selection(self, pattern, caret=None):
        ranges = pattern.GetSelection()
        if not ranges or ranges.Length == 0:
            return None
        if ranges.Length != 1:
            raise AppError("Disjoint selections are unsupported.", "Select one range")
        selected = ranges.GetElement(0)
        if caret and all(selected.CompareEndpoints(endpoint, caret, 0) != 0 for endpoint in (0, 1)):
            raise RangeUnavailable("The selection could not be tied to the active caret.", "Selection unavailable")
        return selected

    def writable(self, element, selection, native: bool):
        readonly = selection.GetAttributeValue(self.types.UIA_IsReadOnlyAttributeId)
        if readonly is True:
            return False
        value = element.GetCurrentPattern(self.types.UIA_ValuePatternId)
        if value:
            return not value.QueryInterface(self.types.IUIAutomationValuePattern).CurrentIsReadOnly
        return True if readonly is False or native else None

    def is_edit_control(self, element) -> bool:
        return bool(element and element.CurrentControlType == self.types.UIA_EditControlTypeId)

    def editable_value(self, element) -> str | None:
        if not self.is_edit_control(element):
            return None
        value = element.GetCurrentPattern(self.types.UIA_ValuePatternId)
        if value:
            value = value.QueryInterface(self.types.IUIAutomationValuePattern)
            if value.CurrentIsReadOnly:
                raise AppError("The focused field is read-only.", "Protected field")
            contents = value.CurrentValue
            if isinstance(contents, str) and len(contents) <= 65536:
                return contents
        return None


@dataclass(frozen=True)
class Trigger:
    target: win.Target
    epoch: int
    operation_id: str = "-"
    message_time: int | None = None
    mode: str = "grammar"
    started_ns: int | None = None
    input_stamp: int | None = None


@dataclass
class Guard:
    trigger: Trigger
    epoch: Callable[[], int]
    stop: Event
    input_tick: int
    synthetic_tick: int | None = None

    def focused(self) -> bool:
        return (
            not self.stop.is_set()
            and self.epoch() == self.trigger.epoch
            and win.targets_match(win.current_target(), self.trigger.target)
        )

    def input_matches(self, latest=None) -> bool:
        if latest is None:
            latest = win.edit_input()
        if win.editing_input_stamp is not None:
            return latest == self.input_tick
        synthetic = self.synthetic_tick
        return latest == self.input_tick or (
            synthetic is not None
            and ((latest - synthetic) & 0xFFFFFFFF) <= SYNTHETIC_INPUT_WINDOW_MS
        )

    def check_input(self):
        if not self.focused():
            raise AppError("The original editing target changed. Correction canceled.",
                           "Target changed", "focus.changed")
        latest = win.edit_input()
        if not self.input_matches(latest):
            logging.debug("event=selection.editing_input_changed")
            raise AppError("User input changed. Correction canceled.", "Selection changed", "selection.changed")
        return latest

    def check(self):
        latest = self.check_input()
        if win.keys_down():
            logging.debug("selection guard: an editing modifier is still down")
            raise AppError("A key or mouse button is still held. Correction canceled.", "Selection changed")
        return latest

    def unchanged_input(self) -> bool:
        try:
            self.check_input()
        except AppError:
            return False
        return True

    def begin_keyboard(self) -> int:
        self.input_tick = self.check()
        self.synthetic_tick = win.tick_count()
        return self.synthetic_tick

    def finish_copy(self):
        # The target can finish its copy while the synthetic Ctrl release
        # is still queued. Wait on key state on the worker, after restoring.
        deadline = time.monotonic() + 0.20
        while win.keys_down() and time.monotonic() < deadline:
            self.check_input()
            if self.stop.wait(0.01):
                break
        self.input_tick = self.check()
        self.synthetic_tick = None


@dataclass
class Selection:
    text: str
    guard: Guard
    native_offsets: tuple[int, int] | None = None
    element: object = None
    text_range: object = None
    owner: object = None
    field_value: str | None = None
    keyboard_copy: bool = False
    classic: bool = False

    def verify(self, automation: Automation | None, clipboard, limit: int):
        self.guard.check()
        target = self.guard.trigger.target
        if self.native_offsets is not None:
            check_native_edit(target)
            if win.native_range(target.focus) != self.native_offsets:
                raise AppError("The selection moved. Correction canceled.", "Selection changed")
        if self.keyboard_copy:
            self.verify_field(automation)
            try:
                live = sanitize_text(clipboard.copy_keyboard(target, limit, self.guard))
                if live and live != self.text:
                    raise AppError("Re-copy did not match the original selection.", "Selection changed")
            except AppError as error:
                if error.code == "capture.no_fresh_text" and self.guard.unchanged_input():
                    logging.debug("Re-copy skipped: input unchanged and target verified.")
                else:
                    raise
            self.verify_field(automation)
        elif self.text_range is None:
            live = (win.classic_selection(target.focus, self.native_offsets) if self.classic
                    else clipboard.copy_native(target, limit, self.guard.check))
            live = sanitize_text(live)
            if live != self.text:
                raise AppError("The selected text changed. Correction canceled.", "Selection changed")
            if win.native_range(target.focus) != self.native_offsets:
                raise AppError("The selection moved. Correction canceled.", "Selection changed")
        else:
            try:
                element, owner, pattern, caret = automation.focused_edit(target)
                if (
                    not pattern or not automation.client.CompareElements(self.element, element)
                    or not automation.client.CompareElements(self.owner, owner)
                ):
                    raise AppError("The focused text control changed.", "Target changed")
                live = automation.selection(pattern, caret)
                live_text = sanitize_text(live.GetText(2 * limit + 1)) if live else ""
                if (
                    not live or not live.Compare(self.text_range)
                    or live_text != self.text
                    or automation.writable(owner, live, self.native_offsets is not None) is False
                ):
                    raise AppError("The selection changed or could not be verified.", "Selection changed")
            except (automation.com_error, RangeUnavailable):
                raise AppError("The UI Automation selection could not be verified.",
                               "Unsafe to replace", "replace.uia_verification_failed") from None
        self.guard.check()

    def verify_field(self, automation):
        self.guard.check()
        if automation:
            try:
                element = automation.focused_element(self.guard.trigger.target)
                if self.element and (
                    not element or not automation.client.CompareElements(self.element, element)
                ):
                    raise AppError("The focused field changed. Correction canceled.", "Target changed")
                if self.field_value is not None and automation.editable_value(element) != self.field_value:
                    raise AppError("The contents of the focused field changed.", "Selection changed")
            except automation.com_error:
                if self.element:
                    raise AppError("The focused field could not be verified.", "Unsafe to replace") from None
        self.guard.check()

    def replace_with_keyboard(self, text: str, clipboard, automation: Automation | None = None, limit: int = 6000):
        """Replace the verified selection using native edit message or clipboard paste."""
        self.guard.check()
        target = self.guard.trigger.target
        if self.native_offsets is not None:
            logging.debug("event=replace.verify method=native")
            with measure("target_verification"):
                self.verify(automation, clipboard, limit)
                win.check_native_capacity(target.focus, self.native_offsets, text)
                if win.native_range(target.focus) != self.native_offsets:
                    raise AppError("The native selection moved before replacement.",
                                   "Selection changed", "selection.changed")
                self.guard.check()
            with measure("replacement"):
                win.replace_native(target.focus, text)
        else:
            logging.debug("event=replace.verify method=clipboard")
            self.guard.check()
            if self.keyboard_copy:
                # A second copy must finish before the replacement clipboard is staged.
                with measure("target_verification"):
                    self.verify(automation, clipboard, limit)
                verify = lambda: self.verify_field(automation)
            else:
                verify = lambda: self.verify(automation, clipboard, limit)
            with measure("replacement_and_clipboard"):
                clipboard.paste(text, target, verify, self.guard)


class CorrectionResult(str):
    """Result string ('success' | 'unchanged' | 'empty') with rich diff and cache metadata."""

    def __new__(
        cls,
        status: str,
        diff: object = None,
        cached: bool = False,
        words_added: int = 0,
        words_removed: int = 0,
        net_word_delta: int = 0,
        net_char_delta: int = 0,
    ):
        obj = super().__new__(cls, status)
        obj.status = status
        obj.diff = diff
        obj.cached = cached
        obj.words_added = words_added
        obj.words_removed = words_removed
        obj.net_word_delta = net_word_delta
        obj.net_char_delta = net_char_delta
        obj.diff_summary = getattr(diff, "summary", None) if diff else None
        return obj


def unique_selection(value: str, copied: str) -> bool:
    value = value.replace("\r\n", "\n")
    copied = copied.replace("\r\n", "\n")
    start = value.find(copied)
    return bool(copied.strip()) and start != -1 and value.find(copied, start + 1) == -1


def check_native_edit(target: win.Target):
    style = win.get_style(target.focus, win.GWL_STYLE)
    if (
        not win.native_edit(target.focus)
        or not target.contains_process(win.window_pid(target.focus))
        or not win.is_enabled(target.focus)
        or style & (win.ES_PASSWORD | win.ES_READONLY)
        # EM_GETPASSWORDCHAR also catches a password mask set after window creation.
        or win.send_window_message(target.focus, win.EM_GETPASSWORDCHAR)
    ):
        raise AppError("The focused field is protected or unavailable.", "Protected field")


def capture(trigger, epoch, stop, settings, automation, clipboard) -> Selection | None:
    target = trigger.target
    executable = win.executable(target.pid)
    logging.debug("event=capture.target app=%r pid=%d", executable, target.pid)
    excluded = {app.casefold() for app in getattr(settings, 'excluded_apps', ())}
    if (executable in excluded or
            target.focus_pid and win.executable(target.focus_pid) in excluded):
        raise AppError("The focused application is excluded in settings.json.", "Excluded app")
    if not win.is_enabled(target.focus):
        raise AppError("The focused control is disabled.", "Protected field")
    deadline = time.monotonic() + 1.2
    while win.keys_down():
        if stop.is_set() or time.monotonic() >= deadline:
            raise AppError("Release the shortcut keys and try again.", "Release shortcut")
        stop.wait(0.01)
    guard = Guard(trigger, epoch, stop, win.edit_input())
    if trigger.input_stamp is not None and trigger.input_stamp != guard.input_tick:
        raise AppError("User input changed before capture. Correction canceled.",
                       "Selection changed", "selection.changed")
    guard.check()

    offsets = None
    if win.native_edit(target.focus):
        check_native_edit(target)
        offsets = win.native_range(target.focus)
        if offsets[0] == offsets[1]:
            return None
    limit = settings.max_selection_chars
    focus_class = win.class_name(target.focus)
    # Windowed Chromium embeds can give keyboard focus to the browser widget
    # itself. A focused child is evidence of an embed even in a non-browser host.
    embedded_widget = win.embedded_chromium_widget(target, focus_class)
    browser = (
        executable in BROWSERS and win.class_name(target.window).startswith(("chrome_", "mozilla"))
        or focus_class == "chrome_renderwidgethosthwnd"
        or embedded_widget
    )
    element, value, editable = None, None, False
    if automation:
        try:
            element, owner, pattern, caret = automation.focused_edit(target)
            editable = automation.is_edit_control(element)
            if not pattern and not editable and browser:
                # A fresh browser renderer can expose only a wrapper while the
                # accessibility tree arrives. Try once before using keyboard copy.
                logging.debug("capture UIA: refreshing browser accessibility")
                automation.client.ElementFromHandle(target.focus if embedded_widget else target.window)
                stop.wait(0.12)
                guard.check()
                element, owner, pattern, caret = automation.focused_edit(target)
                editable = automation.is_edit_control(element)
            if pattern:
                live = automation.selection(pattern, caret)
                if live:
                    text = live.GetText(2 * limit + 1)
                    writable = automation.writable(owner, live, offsets is not None)
                    if writable is False:
                        raise AppError("The focused selection is read-only.", "Protected field")
                    if text and text.strip() and writable is not False:
                        text = sanitize_text(text)
                        logging.debug("capture: UI Automation range verified")
                        return Selection(text, guard, offsets, element, live.Clone(), owner)
                logging.debug("capture UIA: provider returned no usable selection")
            if editable and offsets is None:
                value = automation.editable_value(element)
        except (automation.com_error, RangeUnavailable):
            logging.debug("event=capture.uia_failed")
    if offsets is not None:
        text = win.classic_selection(target.focus, offsets)
        if text is not None:
            guard.check()
            logging.debug("event=capture.native_text_verified")
            text = sanitize_text(text)
            return Selection(text, guard, offsets, classic=True) if text.strip() else None
        logging.debug("capture: native edit clipboard path")
        text = sanitize_text(clipboard.copy_native(target, limit, guard.check))
        return Selection(text, guard, offsets) if text.strip() else None
    if focus_class == "chrome_widgetwin_0" and not embedded_widget:
        logging.debug("event=capture.unattached_chromium_widget")
        raise AppError("This control does not expose a safe copy target.", "Unsupported field",
                       "capture.unsupported_target")
    if (
        not (browser or editable or is_editor_target(target, focus_class, executable, element, automation))
        or not target.contains_process(win.window_pid(target.focus))
    ):
        logging.debug("event=capture.editor_not_recognized focus_class=%r target_pid=%d focus_pid=%d",
                      focus_class, target.pid, win.window_pid(target.focus))
        raise AppError("This control does not expose a safe copy target.", "Unsupported field",
                       "capture.unsupported_target")
    logging.debug("capture: keyboard clipboard fallback")
    text = clipboard.copy_keyboard(target, limit, guard)
    guard.check()
    if not text or not text.strip():
        return None
    text = sanitize_text(text)
    if not text.strip():
        return None
    if value is not None and not unique_selection(value, text):
        raise AppError("The copied text does not identify one selection in the focused field.", "Unsafe to replace")
    result = Selection(text, guard, element=element, field_value=value, keyboard_copy=True)
    result.verify_field(automation)
    return result


def correct_selection(trigger, epoch, stop, settings, automation, clipboard, engine, progress=lambda: None):
    progress()
    with measure("capture"):
        selection = capture(trigger, epoch, stop, settings, automation, clipboard)
    if selection is None:
        logging.debug("No nonempty selection.")
        return "empty"
    selection.text = sanitize_text(selection.text)
    text = selection.text
    if not text or not text.strip():
        logging.debug("No nonempty selection.")
        return "empty"
    limit = settings.max_selection_chars
    if len(text) > limit:
        raise AppError("The selection exceeds the configured length limit.")
    selection.guard.check()
    logging.debug("event=api.request_started")
    # Preserve the original engine call for the default grammar mode and harnesses.
    corrected = (engine.correct(text) if trigger.mode == "grammar"
                 else engine.correct(text, mode=trigger.mode))
    logging.debug("event=api.request_completed")
    if corrected == text:
        logging.debug("No grammar changes needed.")
        return "unchanged"

    # Compute word count and character delta metadata and record in undo manager
    diff = compute_text_diff(text, corrected)
    target_pid = trigger.target.pid if trigger.target else None
    record_replacement(target_pid, text, corrected, trigger.mode)

    selection.replace_with_keyboard(corrected, clipboard, automation, limit)
    logging.debug("Correction submitted to the verified text control.")
    return CorrectionResult(
        "success",
        diff=diff,
        cached=diagnostics.is_cache_hit(),
        words_added=diff.words_added,
        words_removed=diff.words_removed,
        net_word_delta=diff.net_word_delta,
        net_char_delta=diff.net_char_delta,
    )
