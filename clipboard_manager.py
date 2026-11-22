"""Short-lived clipboard transactions that preserve supported original formats."""

import ctypes as c
import logging
from diagnostics import traced
import time
from contextlib import contextmanager
from ctypes import wintypes as w
from dataclasses import dataclass, field
from secrets import token_bytes
from threading import Event
from typing import Callable

import win32 as win
from config import AppError

CF_UNICODETEXT = 13
MEMORY_FORMATS = {1, 4, 5, 6, 7, 8, 10, 11, 12, CF_UNICODETEXT, 15, 16, 17, 0x81}
BITMAP, PALETTE, ENHMETAFILE = 2, 9, 14
METAFILEPICT = 3
OBJECT_FORMATS = {BITMAP, PALETTE, ENHMETAFILE, METAFILEPICT, 0x82, 0x83, 0x8E}
# OLE's Win32 backing entries can describe a live IDataObject. Republishing
# their bytes under Luna's HWND does not transfer the source's COM identity.
OLE_INTERNAL = {"dataobject", "ole private data"}
BYTE_LIMIT = 64 * 1024 * 1024
PASTE_SETTLE_SECONDS = 0.18

open_clipboard = win.bind(win.user, "OpenClipboard", w.BOOL, w.HWND)
close_clipboard = win.bind(win.user, "CloseClipboard", w.BOOL)
empty_clipboard = win.bind(win.user, "EmptyClipboard", w.BOOL)
clipboard_owner = win.bind(win.user, "GetClipboardOwner", w.HWND)
clipboard_reader = win.bind(win.user, "GetOpenClipboardWindow", w.HWND)
sequence = win.bind(win.user, "GetClipboardSequenceNumber", w.DWORD)
enum_format = win.bind(win.user, "EnumClipboardFormats", w.UINT, w.UINT)
get_format_name = win.bind(win.user, "GetClipboardFormatNameW", c.c_int, w.UINT, w.LPWSTR, c.c_int)
register_format = win.bind(win.user, "RegisterClipboardFormatW", w.UINT, w.LPCWSTR)
get_data = win.bind(win.user, "GetClipboardData", w.HANDLE, w.UINT)
set_data = win.bind(win.user, "SetClipboardData", w.HANDLE, w.UINT, w.HANDLE)
has_format = win.bind(win.user, "IsClipboardFormatAvailable", w.BOOL, w.UINT)
global_alloc = win.bind(win.kernel, "GlobalAlloc", w.HGLOBAL, w.UINT, c.c_size_t)
global_free = win.bind(win.kernel, "GlobalFree", w.HGLOBAL, w.HGLOBAL)
global_size = win.bind(win.kernel, "GlobalSize", c.c_size_t, w.HGLOBAL)
global_lock = win.bind(win.kernel, "GlobalLock", w.LPVOID, w.HGLOBAL)
global_unlock = win.bind(win.kernel, "GlobalUnlock", w.BOOL, w.HGLOBAL)
duplicate_data = win.bind(win.ole, "OleDuplicateData", w.HANDLE, w.HANDLE, w.WORD, w.UINT)
delete_object = win.bind(win.gdi, "DeleteObject", w.BOOL, w.HANDLE)
delete_metafile = win.bind(win.gdi, "DeleteEnhMetaFile", w.BOOL, w.HANDLE)
delete_classic_metafile = win.bind(win.gdi, "DeleteMetaFile", w.BOOL, w.HANDLE)
copy_metafile = win.bind(win.gdi, "CopyEnhMetaFileW", w.HANDLE, w.HANDLE, w.LPCWSTR)


class MetafilePicture(c.Structure):
    _fields_ = [("mode", c.c_int), ("x", c.c_int), ("y", c.c_int), ("metafile", w.HANDLE)]


@dataclass
class ClipboardItem:
    format: int
    handle: int | None

    def publish(self):
        if not set_data(self.format, self.handle):
            raise AppError("Windows could not write a clipboard format.")
        self.handle = None  # Clipboard now owns the handle.

    def free(self):
        if self.handle:
            if self.format in (BITMAP, PALETTE, 0x82):
                delete_object(self.handle)
            elif self.format in (ENHMETAFILE, 0x8E):
                delete_metafile(self.handle)
            else:
                if self.format in (METAFILEPICT, 0x83):
                    pointer = global_lock(self.handle)
                    if pointer:
                        try:
                            delete_classic_metafile(MetafilePicture.from_address(pointer).metafile)
                        finally:
                            global_unlock(self.handle)
                global_free(self.handle)
            self.handle = None


def memory_item(format: int, data: bytes) -> ClipboardItem:
    item = ClipboardItem(format, global_alloc(0x0002, len(data)))  # GMEM_MOVEABLE
    if not item.handle:
        raise AppError("Windows could not allocate clipboard memory.")
    pointer = global_lock(item.handle)
    if not pointer:
        item.free()
        raise AppError("Windows could not lock clipboard memory.")
    try:
        c.memmove(pointer, data, len(data))
    finally:
        global_unlock(item.handle)
    return item


def formats():
    previous = 0
    while True:
        c.set_last_error(0)
        current = enum_format(previous)
        if not current:
            if c.get_last_error():
                raise AppError("Windows could not enumerate clipboard formats.")
            return
        yield current
        previous = current


def format_name(format: int) -> str:
    name = c.create_unicode_buffer(256)
    return name.value if get_format_name(format, name, len(name)) else ""


def describe(format: int, name: str = "") -> str:
    return f"0x{format:04x}({name!r})" if name else f"0x{format:04x}"


def can_duplicate(format: int, name: str | None = None) -> bool:
    # Despite the name, Windows defines CF_GDIOBJ* as movable HGLOBAL data.
    if format in MEMORY_FORMATS or format in OBJECT_FORMATS or 0x0300 <= format <= 0x03FF:
        return True
    if not 0xC000 <= format <= 0xFFFF:
        return False
    name = format_name(format) if name is None else name
    # RegisterClipboardFormat documents HGLOBAL for registered Win32 data.
    return bool(name) and name.casefold() not in OLE_INTERNAL


def cached_ole_item(available: dict[int, str], trusted_owner: int | None = None) -> bool:
    """Recognize a materialized cache without trusting a live OLE source reference."""
    names = {name.casefold(): fmt for fmt, name in available.items()}
    if not OLE_INTERNAL <= names.keys():
        return False
    owner = clipboard_owner()
    if owner and owner != trusted_owner:
        return False
    handle = get_data(names["dataobject"])
    if not handle or global_size(handle) not in (4, 8):
        return False
    pointer = global_lock(handle)
    if not pointer:
        return False
    try:
        return not any(c.string_at(pointer, global_size(handle)))
    finally:
        global_unlock(handle)


@traced('clipboard_snapshot')
def snapshot(trusted_owner: int | None = None) -> list[ClipboardItem]:
    """Called with the clipboard open, before any mutation."""
    available = {format: format_name(format) if format >= 0xC000 else "" for format in formats()}
    logging.debug("event=clipboard.snapshot formats=%s",
                  ", ".join(describe(fmt, name) for fmt, name in available.items()))
    cached = cached_ole_item(available, trusted_owner)
    unsupported = [
        describe(fmt, name) for fmt, name in available.items()
        if not can_duplicate(fmt, name) and not (cached and name.casefold() in OLE_INTERNAL)
    ]
    if unsupported:
        logging.debug("event=clipboard.preservation_limited formats=%s", ", ".join(unsupported))
        raise AppError("Clipboard contains a format Luna cannot safely preserve. Correction skipped.",
                       "Clipboard preservation limited", "clipboard.preservation_limited")
    if cached:
        logging.debug("event=clipboard.cached_ole_snapshot")
    items = []
    size = 0
    try:
        for format in available:
            original = get_data(format)
            if not original:
                logging.debug("event=clipboard.read_failed format=%s", describe(format, available[format]))
                raise AppError("A clipboard format could not be read. Correction skipped.",
                               "Clipboard unavailable", "clipboard.read_failed")
            if format not in OBJECT_FORMATS:
                length = global_size(original)
                size += length
                if not length or size > BYTE_LIMIT:
                    raise AppError("Clipboard data is too large or could not be backed up.",
                                   "Clipboard preservation limited", "clipboard.preservation_limited")
            if format in (ENHMETAFILE, 0x8E):
                cloned = copy_metafile(original, None)
            else:
                base = {0x82: BITMAP, 0x83: METAFILEPICT}.get(format, format)
                cloned = duplicate_data(original, base, 0x0002)
            if not cloned:
                logging.debug("event=clipboard.clone_failed format=%s", describe(format, available[format]))
                raise AppError("A clipboard format could not be backed up. Correction skipped.",
                               "Clipboard preservation limited", "clipboard.preservation_limited")
            items.append(ClipboardItem(format, cloned))
        return items
    except BaseException:
        for item in items:
            item.free()
        raise


def safe_snapshot(trusted_owner: int | None = None) -> list[ClipboardItem]:
    """Capture only safe, duplicable formats, ignoring unsupported or OLE formats."""
    items = []
    try:
        for format in formats():
            name = format_name(format) if format >= 0xC000 else ""
            if not can_duplicate(format, name):
                continue
            try:
                original = get_data(format)
                if not original:
                    continue
                if format not in OBJECT_FORMATS:
                    length = global_size(original)
                    if not length or length > BYTE_LIMIT:
                        continue
                if format in (ENHMETAFILE, 0x8E):
                    cloned = copy_metafile(original, None)
                else:
                    base = {0x82: BITMAP, 0x83: METAFILEPICT}.get(format, format)
                    cloned = duplicate_data(original, base, 0x0002)
                if cloned:
                    items.append(ClipboardItem(format, cloned))
            except Exception:
                continue
        return items
    except BaseException:
        for item in items:
            item.free()
        return []


@traced('clipboard_restore')
def restore(items: list[ClipboardItem]):
    if not empty_clipboard():
        raise AppError("Windows could not empty the temporary clipboard for restoration.",
                       "Clipboard restore failed", "clipboard.restore_failed")
    failed = False
    for item in items:
        try:
            item.publish()
        except AppError:
            logging.warning("event=clipboard.restore_format_failed format=%s",
                            describe(item.format, format_name(item.format)))
            failed = True
    if failed:
        raise AppError("Windows rejected one or more clipboard formats during restoration.",
                       "Clipboard restore failed", "clipboard.restore_failed")


def selected_text(limit: int) -> str:
    handle = get_data(CF_UNICODETEXT)
    if not handle:
        return ""
    pointer = global_lock(handle)
    if not pointer:
        raise AppError("Could not read the copied text.", "Copy unavailable")
    try:
        length = min(global_size(handle), (2 * limit + 1) * 2)
        raw = c.string_at(pointer, length - length % 2)
    finally:
        global_unlock(handle)
    text, terminator, _ = raw.decode("utf-16-le", errors="surrogatepass").partition("\0")
    if not terminator or len(text) > limit:
        raise AppError("The selection exceeds the configured length limit.", "Selection too long")
    return text


@dataclass
class PasteOffer:
    item: ClipboardItem
    target: win.Target
    still_focused: Callable[[], bool]
    token: bytes
    armed: Event = field(default_factory=Event)
    rendered: Event = field(default_factory=Event)


class Clipboard:
    def __init__(self, owner: int):
        self.owner = owner
        self.offer: PasteOffer | None = None
        # Fail closed by default: refuse a correction rather than silently
        # destroying clipboard formats Luna cannot back up. Set False (via
        # settings.clipboard_strict_preservation) to keep the old
        # best-effort behaviour.
        self.strict_preservation = True
        self.private_format = register_format("ExcludeClipboardContentFromMonitorProcessing")
        if not self.private_format:
            raise AppError("Could not register the private Windows clipboard marker.")

    @contextmanager
    def locked(self, timeout=0.35):
        deadline = time.monotonic() + timeout
        delay = 0.01  # bounded exponential back-off on clipboard contention
        while not open_clipboard(self.owner):
            if time.monotonic() >= deadline:
                raise AppError("The Windows clipboard is busy.", "Clipboard busy", "clipboard.busy")
            time.sleep(delay)
            delay = min(delay * 2, 0.05)
        try:
            yield
        finally:
            close_clipboard()

    @contextmanager
    def restoration_lock(self):
        try:
            with self.locked(timeout=1):
                yield
        except AppError as error:
            if error.code == "clipboard.busy":
                raise AppError("The clipboard stayed locked during restoration.",
                               "Clipboard restore failed", "clipboard.restore_failed") from None
            raise

    def copy_native(self, target: win.Target, limit: int, verify: Callable[[], None]) -> str:
        return self.copy(target, limit, verify, lambda: win.send_window_message(target.focus, win.WM_COPY))

    def copy_keyboard(self, target: win.Target, limit: int, guard) -> str:
        text = self.copy(target, limit, guard.check, lambda: win.edit_shortcut("C", guard.begin_keyboard()),
                         verify_result=guard.check_input, copy_attributable=guard.input_matches)
        guard.finish_copy()
        return text

    @traced('clipboard_copy')
    def copy(self, target: win.Target, limit: int, verify, dispatch,
             verify_result=None, copy_attributable=lambda: True) -> str:
        wait = verify_result is not None
        with self.locked():
            try:
                backup = snapshot(self.owner)
            except AppError as err:
                if err.code == "clipboard.preservation_limited" and not self.strict_preservation:
                    backup = safe_snapshot(self.owner)
                else:
                    raise
            before = sequence()
            previous_owner = clipboard_owner()
        try:
            verify()
            if not before:
                raise AppError("Windows did not provide a clipboard sequence number.", "Copy unavailable")
            if sequence() != before or clipboard_owner() != previous_owner:
                raise AppError("The clipboard changed before capture. Correction skipped.",
                               "Clipboard changed", "clipboard.changed")
            text = ""
            try:
                logging.debug("event=clipboard.copy_dispatch method=%s", "Ctrl+C" if wait else "WM_COPY")
                dispatch()
                if wait:
                    deadline = time.monotonic() + 0.75
                    while (sequence() == before and clipboard_owner() == previous_owner
                           and time.monotonic() < deadline):
                        time.sleep(0.01)
            finally:
                open_window = clipboard_reader()
                copied = sequence()
                observed_owner = clipboard_owner()
                with self.restoration_lock():
                    owner = clipboard_owner()
                    current = sequence()
                    owns_copy = (
                        owner == observed_owner and (current != before or owner != previous_owner)
                        and owner and win.clipboard_window_matches(target, owner)
                        and (current == copied or (wait and open_window == observed_owner))
                        and copy_attributable()
                    )
                    if owns_copy:
                        try:
                            (verify_result or verify)()
                            text = selected_text(limit)
                        finally:
                            restore(backup)
                        logging.debug("event=clipboard.copy_restored")
                    else:
                        logging.debug("event=clipboard.copy_unattributed owner_pid=%s sequence_changed=%s",
                                      win.window_pid(owner) if owner else None, current != before)
            if wait and not text:
                raise AppError("The editor did not copy fresh text. Select editable text and try again.",
                               "Nothing copied", "capture.no_fresh_text")
            return text
        finally:
            for item in backup:
                item.free()

    def stage_text(self, text: str) -> None:
        """Place text on the clipboard for manual pasting (copy-only mode).

        Unlike paste(), this deliberately does NOT back up or restore the
        previous clipboard: the corrected text IS what the user wants there.
        """
        line_endings = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        item = memory_item(CF_UNICODETEXT, (line_endings + "\0").encode("utf-16-le"))
        try:
            with self.locked():
                if not empty_clipboard():
                    raise AppError("Windows could not prepare the clipboard.",
                                   "Clipboard unavailable", "clipboard.busy")
                item.publish()
        except BaseException:
            item.free()
            raise

    def render(self, format: int):
        """Runs on the clipboard owner's message thread, while the reader holds the lock."""
        offer = self.offer
        if format != CF_UNICODETEXT or not offer:
            return
        if not offer.armed.is_set():
            logging.debug("clipboard paste: read requested before dispatch")
            return
        if not offer.item.handle or clipboard_owner() != self.owner or not offer.still_focused():
            logging.debug("clipboard paste: read denied by target/input guard")
            return
        reader = clipboard_reader()
        if reader and not win.clipboard_window_matches(offer.target, reader):
            logging.debug("clipboard paste: read requested by a different process")
            return
        try:
            offer.item.publish()
        except AppError as error:
            logging.debug("%s", error)
            return
        offer.rendered.set()
        logging.debug("clipboard paste: verified reader received text")

    def matches_token(self, token: bytes) -> bool:
        """Check the offer under the clipboard lock, without reading its delayed text."""
        if clipboard_owner() != self.owner or not has_format(self.private_format):
            return False
        handle = get_data(self.private_format)
        if not handle or global_size(handle) < len(token):
            return False
        pointer = global_lock(handle)
        if not pointer:
            return False
        try:
            return c.string_at(pointer, len(token)) == token
        finally:
            global_unlock(handle)

    def paste(self, text: str, target: win.Target, verify, guard):
        line_endings = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        item = memory_item(CF_UNICODETEXT, (line_endings + "\0").encode("utf-16-le"))
        marker = None
        backup = []
        replaced = False
        offer = PasteOffer(item, target, guard.unchanged_input, token_bytes(16))
        try:
            # The exclusion format accepts any payload. A nonce distinguishes
            # this offer even when Windows advances the sequence synthesizing formats.
            marker = memory_item(self.private_format, offer.token)
            with self.locked():
                try:
                    backup = snapshot(self.owner)
                except AppError as err:
                    if err.code == "clipboard.preservation_limited" and not self.strict_preservation:
                        backup = safe_snapshot(self.owner)
                    else:
                        raise
                if not empty_clipboard():
                    raise AppError("Windows could not prepare the clipboard for paste.")
                replaced = True
                try:
                    marker.publish()
                    self.offer = offer
                    c.set_last_error(0)
                    set_data(CF_UNICODETEXT, None)  # A NULL handle is successful for delayed rendering.
                    if c.get_last_error() or not has_format(CF_UNICODETEXT):
                        raise AppError("Windows rejected delayed clipboard rendering.")
                except BaseException:
                    replaced = False
                    restore(backup)
                    raise
            verify()
            with self.locked():
                if not self.matches_token(offer.token):
                    raise AppError("The clipboard changed before paste. Correction skipped.",
                                   "Clipboard changed", "clipboard.changed")
            input_tick = guard.begin_keyboard()
            if clipboard_owner() != self.owner:
                raise AppError("The clipboard changed before paste. Correction skipped.",
                               "Clipboard changed", "clipboard.changed")
            offer.armed.set()
            logging.debug("clipboard paste: dispatching Ctrl+V")
            win.edit_shortcut("V", input_tick)
            if not offer.rendered.wait(0.5):
                # Fallback: if the target application does not read via delayed rendering
                # within 500ms (e.g. out-of-process broker or no WM_RENDERFORMAT pump),
                # directly publish the Unicode text so paste succeeds in any text box!
                guard.check_input()
                second_paste = False
                with self.locked():
                    if not self.matches_token(offer.token):
                        raise AppError("The clipboard changed during paste.",
                                       "Clipboard changed", "clipboard.changed")
                    if offer.rendered.is_set():
                        # A late read from the first Ctrl+V already got the
                        # text. Sending a second Ctrl+V now would paste it
                        # twice, so skip it.
                        logging.debug("clipboard paste: late first read, skipping second Ctrl+V")
                    elif offer.item.handle:
                        logging.debug("clipboard paste: falling back to direct rendering")
                        offer.item.publish()
                        offer.rendered.set()
                        second_paste = True
                if second_paste:
                    input_tick = guard.begin_keyboard()
                    win.edit_shortcut("V", input_tick)
                time.sleep(PASTE_SETTLE_SECONDS)
            else:
                # Browser paste can make several asynchronous clipboard reads. Keep
                # the same item available briefly after the first read, while the
                # target and clipboard ownership remain unchanged.
                deadline = time.monotonic() + PASTE_SETTLE_SECONDS
                while (time.monotonic() < deadline and clipboard_owner() == self.owner
                       and guard.unchanged_input()):
                    time.sleep(0.01)
        finally:
            offer.armed.clear()
            try:
                if replaced:
                    with self.restoration_lock():
                        if self.matches_token(offer.token):
                            restore(backup)
                            logging.debug("event=clipboard.paste_restored")
                        else:
                            logging.debug("event=clipboard.paste_restore_skipped reason=newer_item")
            finally:
                self.offer = None
                item.free()
                if marker:
                    marker.free()
                for entry in backup:
                    entry.free()
