"""The small Win32 surface used by Luna Grammar."""

import ctypes as c
from ctypes import wintypes as w
from dataclasses import dataclass
from pathlib import PureWindowsPath
from secrets import randbits

from config import AppError

user = c.WinDLL("user32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
ole = c.WinDLL("ole32", use_last_error=True)
gdi = c.WinDLL("gdi32", use_last_error=True)
P = c.POINTER
UINT_PTR = c.c_size_t
LRESULT = c.c_ssize_t
WNDPROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
CONSOLE_HANDLER = c.WINFUNCTYPE(w.BOOL, w.DWORD)
WIN_EVENT = c.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND, w.LONG, w.LONG, w.DWORD, w.DWORD)
INPUT_TAG = randbits(c.sizeof(UINT_PTR) * 8) or 1
editing_input_stamp = None
shortcut_key_state = None


class WindowClass(c.Structure):
    _fields_ = [
        ("style", w.UINT), ("proc", WNDPROC), ("class_extra", c.c_int),
        ("window_extra", c.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
        ("cursor", w.HANDLE), ("brush", w.HBRUSH), ("menu", w.LPCWSTR), ("name", w.LPCWSTR),
    ]


class GuiThreadInfo(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("flags", w.DWORD), ("active", w.HWND), ("focus", w.HWND),
        ("capture", w.HWND), ("menu", w.HWND), ("move", w.HWND), ("caret", w.HWND),
        ("caret_rect", w.RECT),
    ]


class LastInput(c.Structure):
    _fields_ = [("size", w.UINT), ("time", w.DWORD)]


class ProcessEntry(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD), ("heap", UINT_PTR),
        ("module", w.DWORD), ("threads", w.DWORD), ("parent_pid", w.DWORD),
        ("priority", w.LONG), ("flags", w.DWORD), ("image", w.WCHAR * 260),
    ]


class MouseInput(c.Structure):
    _fields_ = [
        ("x", w.LONG), ("y", w.LONG), ("data", w.DWORD),
        ("flags", w.DWORD), ("time", w.DWORD), ("extra", UINT_PTR),
    ]


class KeyboardInput(c.Structure):
    _fields_ = [
        ("key", w.WORD), ("scan", w.WORD), ("flags", w.DWORD),
        ("time", w.DWORD), ("extra", UINT_PTR),
    ]


class HardwareInput(c.Structure):
    _fields_ = [("message", w.DWORD), ("low", w.WORD), ("high", w.WORD)]


class InputData(c.Union):
    _fields_ = [("mouse", MouseInput), ("keyboard", KeyboardInput), ("hardware", HardwareInput)]


class Input(c.Structure):
    _fields_ = [("type", w.DWORD), ("data", InputData)]


def bind(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype = result
    fn.argtypes = args
    return fn


register_class = bind(user, "RegisterClassW", w.ATOM, P(WindowClass))
unregister_class = bind(user, "UnregisterClassW", w.BOOL, w.LPCWSTR, w.HINSTANCE)
create_window = bind(
    user, "CreateWindowExW", w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
    c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID,
)
find_window = bind(user, "FindWindowExW", w.HWND, w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR)
destroy_window = bind(user, "DestroyWindow", w.BOOL, w.HWND)
default_proc = bind(user, "DefWindowProcW", LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
get_message = bind(user, "GetMessageW", c.c_int, P(w.MSG), w.HWND, w.UINT, w.UINT)
get_message_time = bind(user, "GetMessageTime", w.LONG)
dispatch_message = bind(user, "DispatchMessageW", LRESULT, P(w.MSG))
post_message = bind(user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
post_quit = bind(user, "PostQuitMessage", None, c.c_int)
register_hotkey = bind(user, "RegisterHotKey", w.BOOL, w.HWND, c.c_int, w.UINT, w.UINT)
unregister_hotkey = bind(user, "UnregisterHotKey", w.BOOL, w.HWND, c.c_int)
set_event_hook = bind(
    user, "SetWinEventHook", w.HANDLE, w.DWORD, w.DWORD, w.HMODULE, WIN_EVENT,
    w.DWORD, w.DWORD, w.DWORD,
)
unhook_event = bind(user, "UnhookWinEvent", w.BOOL, w.HANDLE)
foreground = bind(user, "GetForegroundWindow", w.HWND)
get_ancestor = bind(user, "GetAncestor", w.HWND, w.HWND, w.UINT)
get_window_thread = bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, P(w.DWORD))
get_gui_info = bind(user, "GetGUIThreadInfo", w.BOOL, w.DWORD, P(GuiThreadInfo))
get_last_input = bind(user, "GetLastInputInfo", w.BOOL, P(LastInput))
tick_count = bind(kernel, "GetTickCount", w.DWORD)
get_key = bind(user, "GetAsyncKeyState", c.c_short, c.c_int)
get_class_name = bind(user, "GetClassNameW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
get_style = bind(user, "GetWindowLongW", w.LONG, w.HWND, c.c_int)
get_client_rect = bind(user, "GetClientRect", w.BOOL, w.HWND, P(w.RECT))
is_enabled = bind(user, "IsWindowEnabled", w.BOOL, w.HWND)
is_unicode = bind(user, "IsWindowUnicode", w.BOOL, w.HWND)
send_message_timeout = bind(
    user, "SendMessageTimeoutW", LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM,
    w.UINT, w.UINT, P(UINT_PTR),
)
send_input = bind(user, "SendInput", w.UINT, w.UINT, P(Input), c.c_int)
get_module = bind(kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)
create_mutex = bind(kernel, "CreateMutexW", w.HANDLE, w.LPVOID, w.BOOL, w.LPCWSTR)
close_handle = bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
process_snapshot = bind(kernel, "CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
first_process = bind(kernel, "Process32FirstW", w.BOOL, w.HANDLE, P(ProcessEntry))
next_process = bind(kernel, "Process32NextW", w.BOOL, w.HANDLE, P(ProcessEntry))
open_process = bind(kernel, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
query_process_name = bind(
    kernel, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, P(w.DWORD),
)
set_console_handler = bind(kernel, "SetConsoleCtrlHandler", w.BOOL, CONSOLE_HANDLER, w.BOOL)

WM_CLOSE = 0x0010
WM_HOTKEY = 0x0312
WM_RENDERFORMAT = 0x0305
WM_COPY = 0x0301
EM_GETSEL = 0x00B0
EM_REPLACESEL = 0x00C2
EM_GETPASSWORDCHAR = 0x00D2
EM_GETLIMITTEXT = 0x00D5
WM_GETTEXTLENGTH = 0x000E
WM_GETTEXT = 0x000D
GWL_STYLE = -16
ES_PASSWORD = 0x0020
ES_READONLY = 0x0800
WM_WORKER_STOPPED = 0x8001
HOTKEY_ID = 1
HOTKEY_MODIFIERS = 0x0002 | 0x0008 | 0x4000  # Ctrl, Win, no auto-repeat.
HOTKEY_KEY = ord("Z")
HWND_MESSAGE = -3
GUARD_KEYS = (0x01, 0x02, 0x04, 0x05, 0x06, 0x10, 0x11, 0x12, 0x5B, 0x5C, HOTKEY_KEY)
NATIVE_EDITS = {"edit", "richedit20w", "richedit50w", "richeditd2d", "richeditd2dpt"}


@dataclass(frozen=True)
class Target:
    window: int
    focus: int
    thread: int
    pid: int
    focus_pid: int = 0

    def contains_process(self, pid: int) -> bool:
        if not pid:
            return False
        if pid in (self.pid, self.focus_pid):
            return True
        return same_app(pid, self.pid) or (bool(self.focus_pid) and same_app(pid, self.focus_pid))


def current_target() -> Target | None:
    window = foreground()
    if not window:
        return None
    pid = w.DWORD()
    thread = get_window_thread(window, c.byref(pid))
    info = GuiThreadInfo(size=c.sizeof(GuiThreadInfo))
    focus = 0
    if thread and get_gui_info(thread, c.byref(info)) and info.focus:
        focus = info.focus
    elif get_gui_info(0, c.byref(info)) and info.focus:
        focus = info.focus
    else:
        focus = window
    if info.active and info.active != window and foreground() != window:
        return None
    focus_pid = window_pid(focus)
    if focus_pid and focus_pid != pid.value:
        root = get_ancestor(focus, 2)
        owner = get_ancestor(focus, 3)
        if root != window and owner != window and not same_app(focus_pid, pid.value):
            return None
    return Target(window, focus, thread, pid.value, focus_pid if focus_pid and focus_pid != pid.value else 0)


def targets_match(current: Target | None, original: Target) -> bool:
    if not current:
        return False
    if current == original:
        return True
    if current.window != original.window or current.pid != original.pid:
        return False
    if current.focus == original.focus:
        return True
    return current.contains_process(window_pid(current.focus))


def same_app(pid1: int, pid2: int) -> bool:
    if not pid1 or not pid2:
        return False
    if pid1 == pid2:
        return True
    try:
        exe1 = executable(pid1)
        exe2 = executable(pid2)
        if exe1 and exe1 == exe2:
            return True
    except Exception:
        pass
    return process_related(pid1, pid2)


def process_related(pid1: int, pid2: int) -> bool:
    if not pid1 or not pid2:
        return False
    snapshot = process_snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == c.c_void_p(-1).value:
        return False
    try:
        parents = {}
        images = {}
        entry = ProcessEntry(size=c.sizeof(ProcessEntry))
        found = first_process(snapshot, c.byref(entry))
        while found:
            parents[entry.pid] = entry.parent_pid
            images[entry.pid] = entry.image.casefold()
            found = next_process(snapshot, c.byref(entry))
        if parents.get(pid1) == pid2 or parents.get(pid2) == pid1:
            return True
        p = pid1
        for _ in range(4):
            p = parents.get(p)
            if not p:
                break
            if p == pid2:
                return True
        p = pid2
        for _ in range(4):
            p = parents.get(p)
            if not p:
                break
            if p == pid1:
                return True
        brokers = {"applicationframehost.exe", "runtimebroker.exe", "msedgewebview2.exe"}
        if images.get(pid1) in brokers and parents.get(pid1) == pid2:
            return True
        if images.get(pid2) in brokers and parents.get(pid2) == pid1:
            return True
        return False
    finally:
        close_handle(snapshot)


def window_pid(window: int) -> int:
    pid = w.DWORD()
    get_window_thread(window, c.byref(pid))
    return pid.value


def embedded_chromium_widget(target: Target, focus_class: str) -> bool:
    return (focus_class == "chrome_widgetwin_0"
            and target.focus != target.window
            and get_ancestor(target.focus, 2) == target.window)  # GA_ROOT


def webview_child_of(pid: int, host_pid: int) -> bool:
    snapshot = process_snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == c.c_void_p(-1).value:
        return False
    try:
        entry = ProcessEntry(size=c.sizeof(ProcessEntry))
        found = first_process(snapshot, c.byref(entry))
        while found:
            if entry.pid == pid:
                return entry.parent_pid == host_pid and entry.image.casefold() == "msedgewebview2.exe"
            found = next_process(snapshot, c.byref(entry))
        return False
    finally:
        close_handle(snapshot)


def clipboard_window_matches(target: Target, window: int) -> bool:
    if not window:
        return False
    if window in (target.window, target.focus):
        return True
    pid = window_pid(window)
    if target.contains_process(pid):
        return True
    focus_cls = class_name(target.focus)
    if embedded_chromium_widget(target, focus_cls):
        return bool(pid and webview_child_of(pid, target.pid))
    try:
        if get_ancestor(window, 2) in (target.window, target.focus):
            return True
        if get_ancestor(window, 3) in (target.window, target.focus):
            return True
    except Exception:
        pass
    return False


def executable(pid: int) -> str:
    process = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        raise AppError("Could not identify the focused application.")
    try:
        path = c.create_unicode_buffer(32768)
        length = w.DWORD(len(path))
        if not query_process_name(process, 0, path, c.byref(length)):
            raise AppError("Could not identify the focused application.")
        return PureWindowsPath(path.value).name.casefold()
    finally:
        close_handle(process)


def last_input() -> int:
    info = LastInput(size=c.sizeof(LastInput))
    if not get_last_input(c.byref(info)):
        raise AppError("Could not verify recent Windows input.")
    return info.time


def edit_input() -> int:
    return editing_input_stamp() if editing_input_stamp is not None else last_input()


def keys_down() -> bool:
    for key in GUARD_KEYS:
        # A suppressed Z press/release can leave GetAsyncKeyState stale, and
        # hooks run before Windows updates that API. Prefer an observed physical
        # state for Z; keep the original OS checks for modifiers/mouse buttons.
        state = shortcut_key_state() if key == HOTKEY_KEY and shortcut_key_state else None
        pressed = bool(state) if state is not None else bool(get_key(key) & 0x8000)
        if pressed:
            return True
    return False


def class_name(window: int) -> str:
    name = c.create_unicode_buffer(128)
    return name.value.casefold() if get_class_name(window, name, len(name)) else ""


def native_edit(window: int) -> bool:
    return class_name(window) in NATIVE_EDITS


def send_window_message(window: int, message: int, wparam: int = 0, lparam: int = 0) -> int:
    result = UINT_PTR()
    # Abort if hung, and cancel pending sends if the target window is destroyed.
    if not send_message_timeout(window, message, wparam, lparam, 0x22, 450, c.byref(result)):
        raise AppError("The focused control did not accept a Windows edit message.")
    return result.value


def native_range(window: int) -> tuple[int, int]:
    start = w.DWORD(0xFFFFFFFF)
    end = w.DWORD(0xFFFFFFFF)
    send_window_message(window, EM_GETSEL, c.addressof(start), c.addressof(end))
    if start.value > end.value or end.value == 0xFFFFFFFF:
        raise AppError("This editor's selection offsets could not be verified.")
    return start.value, end.value


def classic_selection(window: int, offsets: tuple[int, int]) -> str | None:
    """Read only when Win32 Edit offsets and text use the same UTF-16 representation."""
    if class_name(window) != "edit" or not is_unicode(window):
        return None
    length = send_window_message(window, WM_GETTEXTLENGTH)
    if not offsets[1] <= length <= 65536:
        return None
    buffer = c.create_unicode_buffer(length + 1)
    copied = send_window_message(window, WM_GETTEXT, len(buffer), c.addressof(buffer))
    if copied != length or native_range(window) != offsets:
        raise AppError("The native selection changed during capture.", "Selection changed", "selection.changed")
    start, end = offsets
    data = c.string_at(c.addressof(buffer) + start * 2, (end - start) * 2)
    return data.decode("utf-16-le", errors="surrogatepass")


def check_native_capacity(window: int, offsets: tuple[int, int], text: str):
    style = get_style(window, GWL_STYLE)
    if style & (0x0008 | 0x0010 | 0x0400 | 0x2000):  # ES_UPPERCASE/LOWERCASE/OEMCONVERT/NUMBER
        raise AppError("The editor imposes text transformations. Correction skipped.")
    client = w.RECT()
    if not get_client_rect(window, c.byref(client)) or client.right <= 0 or client.bottom <= 0:
        raise AppError("The focused editor has no visible editing area.")
    if class_name(window) == "edit":
        # Classic Edit can discard inserted text when its viewport cannot scroll.
        scroll_style = 0x0040 if style & 0x0004 else 0x0080  # ES_AUTOVSCROLL or ES_AUTOHSCROLL
        if not style & scroll_style:
            raise AppError("The focused editor has a fixed editing area. Correction skipped.")
    limit = send_window_message(window, EM_GETLIMITTEXT)
    length = send_window_message(window, WM_GETTEXTLENGTH)
    inserted = len(text.encode("utf-16-le")) // 2
    selected = offsets[1] - offsets[0]
    if not limit or selected > length or length - selected + inserted > limit:
        raise AppError("The correction may exceed the editor's text limit.")


def replace_native(window: int, text: str):
    value = c.create_unicode_buffer(text)
    send_window_message(window, EM_REPLACESEL, 1, c.addressof(value))


def edit_shortcut(key: str, input_tick: int = 0):
    """Dispatch only a standard copy or paste chord with the tracked injection timestamp."""
    if key not in ("C", "V"):
        raise ValueError("Only copy and paste shortcuts are supported.")
    if keys_down():
        raise AppError("A modifier is still held. Correction canceled.",
                       "Release shortcut", "hotkey.modifiers_held")
    ctrl = 0x11
    vk = ord(key)
    events = [(ctrl, 0), (vk, 0), (vk, 2), (ctrl, 2)]
    inputs = (Input * len(events))(
        *(Input(1, InputData(keyboard=KeyboardInput(code, 0, flags, input_tick, INPUT_TAG)))
          for code, flags in events)
    )
    count = send_input(len(inputs), inputs, c.sizeof(Input))
    if count != len(inputs):
        releases = []
        if count == 2:
            releases.append(Input(1, InputData(keyboard=KeyboardInput(vk, 0, 2, input_tick, INPUT_TAG))))
        if count:
            releases.append(Input(1, InputData(keyboard=KeyboardInput(ctrl, 0, 2, input_tick, INPUT_TAG))))
            send_input(len(releases), (Input * len(releases))(*releases), c.sizeof(Input))
        raise AppError("Windows blocked the editing shortcut. Check the target's permissions.",
                       "Copy unavailable" if key == "C" else "Paste blocked")
