"""User settings. Secrets come exclusively from the process environment."""

import json
import math
import os
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath


class AppError(Exception):
    """An error with a fixed, safe-to-log message."""

    def __init__(self, message: str, status: str = "Couldn’t refine", code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


SOURCE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = (
    Path(os.environ["LOCALAPPDATA"]) / "LunaGrammar" / "settings.json"
    if getattr(sys, "frozen", False) else SOURCE_DIR / "settings.json"
)

_CONFIG_LOCK = threading.RLock()


def app_command(*args: str, windowless=False) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    python = Path(sys.executable)
    if windowless:
        python = python.with_name("pythonw.exe")
    return [str(python), str(SOURCE_DIR / "main.py"), *args]


def independent_process_environment() -> dict[str, str] | None:
    if getattr(sys, "frozen", False):
        return dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    return None


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-6-luna"
    timeout_seconds: float = 10
    max_selection_chars: int = 6000
    excluded_apps: tuple[str, ...] = ()
    enabled: bool = True
    feedback: bool = True
    expand_shorthand: bool = True
    appearance: str = "dark"
    motion: str = "system"
    active_model: str = "gpt-6-luna"
    cache_enabled: bool = True
    custom_prompt: str = ""
    default_mode: int = 0
    show_diff_preview: bool = True
    sound_enabled: bool = True
    temperature: float = 0.0
    # Per-app default mode for a bare Ctrl+Win+Z (explicit digits always win).
    # Maps lowercase exe name -> mode level 0-5, e.g. {"outlook.exe": 2}.
    per_app_modes: dict = field(default_factory=dict)
    # When True, corrections are staged on the clipboard for manual Ctrl+V
    # instead of being pasted automatically (safe mode for fragile fields).
    copy_only: bool = False
    # When True (default), a correction is refused rather than silently
    # destroying clipboard formats Luna cannot back up (images/OLE data).
    # Set False to keep the old behaviour: back up only the formats that
    # can be duplicated and lose the rest.
    clipboard_strict_preservation: bool = True
    # When True, the correction is held for review (Apply / Discard in the
    # overlay) instead of being pasted immediately. Default off: corrections
    # apply automatically, as before.
    review_before_apply: bool = False
    # Recent-corrections history (in-memory only, never written to disk).
    history_enabled: bool = True
    max_history_items: int = 20

    def __post_init__(self):
        # Keep model and active_model in sync. When exactly one is the
        # default, the other wins; when both are set to different
        # non-default values, active_model wins (it is what the engine reads).
        if self.model != "gpt-6-luna" and self.active_model == "gpt-6-luna":
            object.__setattr__(self, "active_model", self.model)
        elif self.active_model != "gpt-6-luna" and self.model == "gpt-6-luna":
            object.__setattr__(self, "model", self.active_model)
        elif self.model != self.active_model:
            object.__setattr__(self, "model", self.active_model)

    def to_dict(self) -> dict:
        return {
            "active_model": self.active_model,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "max_selection_chars": self.max_selection_chars,
            "excluded_apps": list(self.excluded_apps),
            "enabled": self.enabled,
            "feedback": self.feedback,
            "expand_shorthand": self.expand_shorthand,
            "appearance": self.appearance,
            "motion": self.motion,
            "cache_enabled": self.cache_enabled,
            "custom_prompt": self.custom_prompt,
            "default_mode": self.default_mode,
            "show_diff_preview": self.show_diff_preview,
            "sound_enabled": self.sound_enabled,
            "temperature": self.temperature,
            "per_app_modes": dict(self.per_app_modes),
            "copy_only": self.copy_only,
            "clipboard_strict_preservation": self.clipboard_strict_preservation,
            "review_before_apply": self.review_before_apply,
            "history_enabled": self.history_enabled,
            "max_history_items": self.max_history_items,
        }


def migrate_settings_dict(data: dict) -> tuple[dict, bool]:
    """Migrate legacy settings dictionary to modern schema. Returns (data, was_migrated)."""
    if not isinstance(data, dict):
        return data, False
    migrated = dict(data)
    changed = False

    # Key migrations
    if "model" in migrated and "active_model" not in migrated:
        migrated["active_model"] = migrated["model"]
        changed = True
    elif "active_model" in migrated and "model" not in migrated:
        migrated["model"] = migrated["active_model"]
        changed = True

    if "theme" in migrated and "appearance" not in migrated:
        migrated["appearance"] = migrated.pop("theme")
        changed = True

    if "sound" in migrated and "sound_enabled" not in migrated:
        migrated["sound_enabled"] = migrated.pop("sound")
        changed = True

    return migrated, changed


def auto_migrate_settings(path: Path) -> bool:
    """Migrate settings file on disk if it contains legacy format. Thread-safe."""
    with _CONFIG_LOCK:
        if not path.exists():
            return False
        try:
            raw = path.read_text(encoding="utf-8-sig")
            data = json.loads(raw) if raw.strip() else {}
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        migrated, changed = migrate_settings_dict(data)
        if changed:
            temp = None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8",
                                                 suffix=".tmp", delete=False) as output:
                    temp = Path(output.name)
                    json.dump(migrated, output, indent=2)
                    output.write("\n")
                temp.replace(path)
                return True
            except OSError:
                if temp:
                    temp.unlink(missing_ok=True)
                return False
        return False


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    with _CONFIG_LOCK:
        if path.exists():
            try:
                auto_migrate_settings(path)
            except Exception:
                pass
        return parse_settings(read_settings(path))


def read_settings(path: Path = SETTINGS_PATH) -> dict:
    with _CONFIG_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        except (OSError, ValueError):
            raise AppError("Could not read settings.json. Check that it contains valid JSON.") from None
        if not isinstance(data, dict):
            raise AppError("settings.json must contain only the documented settings.")
        data, _ = migrate_settings_dict(data)
        if data.keys() - Settings.__dataclass_fields__.keys():
            raise AppError("settings.json must contain only the documented settings.")
        return data


def parse_settings(data: dict) -> Settings:
    defaults = Settings()
    active_model = os.environ.get(
        "LUNA_GRAMMAR_MODEL",
        data.get("active_model", data.get("model", defaults.active_model))
    )
    timeout = data.get("timeout_seconds", defaults.timeout_seconds)
    limit = data.get("max_selection_chars", defaults.max_selection_chars)
    excluded = data.get("excluded_apps", list(defaults.excluded_apps))

    if not isinstance(active_model, str) or not active_model.strip():
        raise AppError("Set a nonempty OpenAI model ID.")
    active_model = active_model.strip()

    if type(timeout) not in (int, float) or not (1 <= timeout <= 60) or not math.isfinite(timeout):
        raise AppError("timeout_seconds must be between 1 and 60.")

    if type(limit) is not int or not (1 <= limit <= 20000):
        raise AppError("max_selection_chars must be an integer between 1 and 20000.")

    if not isinstance(excluded, (list, tuple)) or any(
        not isinstance(name, str)
        or PureWindowsPath(name).name != name
        or not name.casefold().endswith(".exe")
        for name in excluded
    ):
        raise AppError("excluded_apps must be a list of executable names such as notepad.exe.")

    toggles = {}
    for name in ("enabled", "feedback", "expand_shorthand", "cache_enabled", "show_diff_preview", "sound_enabled",
                 "copy_only", "clipboard_strict_preservation", "review_before_apply", "history_enabled"):
        value = data.get(name, getattr(defaults, name))
        if type(value) is not bool:
            raise AppError(f"{name} must be true or false.")
        toggles[name] = value

    max_history = data.get("max_history_items", defaults.max_history_items)
    if type(max_history) is not int or not (0 <= max_history <= 100):
        raise AppError("max_history_items must be an integer between 0 and 100.")

    per_app_modes = data.get("per_app_modes", {})
    if not isinstance(per_app_modes, dict) or any(
        not isinstance(name, str)
        or PureWindowsPath(name).name != name
        or not name.casefold().endswith(".exe")
        or type(level) is not int or not (0 <= level <= 5)
        for name, level in per_app_modes.items()
    ):
        raise AppError('per_app_modes must map executable names to a mode level 0-5, e.g. {"outlook.exe": 2}.')
    per_app_modes = {name.casefold(): level for name, level in per_app_modes.items()}

    appearance = data.get("appearance", defaults.appearance)
    motion = data.get("motion", defaults.motion)
    if appearance not in ("dark", "light", "system") or motion not in ("system", "reduced"):
        raise AppError("Use dark, light or system for appearance, and system or reduced for motion.")

    custom_prompt = data.get("custom_prompt", defaults.custom_prompt)
    if not isinstance(custom_prompt, str):
        raise AppError("custom_prompt must be a string.")

    default_mode = data.get("default_mode", defaults.default_mode)
    if type(default_mode) is not int or not (0 <= default_mode <= 5):
        raise AppError("default_mode must be an integer between 0 and 5.")

    temperature = data.get("temperature", defaults.temperature)
    if type(temperature) not in (int, float) or not (0.0 <= temperature <= 2.0) or not math.isfinite(temperature):
        raise AppError("temperature must be a number between 0.0 and 2.0.")

    return Settings(
        model=active_model,
        timeout_seconds=timeout,
        max_selection_chars=limit,
        excluded_apps=tuple(name.casefold() for name in excluded),
        enabled=toggles["enabled"],
        feedback=toggles["feedback"],
        expand_shorthand=toggles["expand_shorthand"],
        appearance=appearance,
        motion=motion,
        active_model=active_model,
        cache_enabled=toggles["cache_enabled"],
        custom_prompt=custom_prompt,
        default_mode=default_mode,
        show_diff_preview=toggles["show_diff_preview"],
        sound_enabled=toggles["sound_enabled"],
        temperature=float(temperature),
        per_app_modes=per_app_modes,
        copy_only=toggles["copy_only"],
        clipboard_strict_preservation=toggles["clipboard_strict_preservation"],
        review_before_apply=toggles["review_before_apply"],
        history_enabled=toggles["history_enabled"],
        max_history_items=max_history,
    )


def update_settings(changes: dict, path: Path = SETTINGS_PATH):
    with _CONFIG_LOCK:
        current = read_settings(path)
        data = current | changes
        # Synchronize active_model and model
        if "active_model" in changes and "model" not in changes:
            data["model"] = changes["active_model"]
        elif "model" in changes and "active_model" not in changes:
            data["active_model"] = changes["model"]
        elif "active_model" in data and "model" not in data:
            data["model"] = data["active_model"]
        elif "model" in data and "active_model" not in data:
            data["active_model"] = data["model"]

        parse_settings(data)
        temp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8",
                                             suffix=".tmp", delete=False) as output:
                temp = Path(output.name)
                json.dump(data, output, indent=2)
                output.write("\n")
            temp.replace(path)
        except OSError:
            raise AppError("Could not save settings.json.") from None
        finally:
            if temp:
                temp.unlink(missing_ok=True)


def _dpapi_path() -> Path:
    return SETTINGS_PATH.parent / "api_key.dpapi"


def store_api_key_dpapi(key: str) -> None:
    """Store the OpenAI API key with Windows DPAPI (user scope, no new
    dependency). Raises AppError off Windows. The key file is never
    committed and never logged."""
    if sys.platform != "win32":
        raise AppError("DPAPI key storage requires Windows.")
    import ctypes as _c
    from ctypes import wintypes as _w

    class _Blob(_c.Structure):
        _fields_ = [("cb_data", _w.DWORD), ("pb_data", _c.POINTER(_c.c_byte))]

    crypt32 = _c.WinDLL("crypt32", use_last_error=True)
    kernel32 = _c.WinDLL("kernel32", use_last_error=True)
    data = key.encode("utf-8")
    blob_in = _Blob(len(data), _c.cast(_c.create_string_buffer(data, len(data)), _c.POINTER(_c.c_byte)))
    blob_out = _Blob()
    protect = crypt32.CryptProtectData
    protect.argtypes = [_c.POINTER(_Blob), _w.LPCWSTR, _c.c_void_p, _c.c_void_p, _c.c_void_p, _w.DWORD, _c.POINTER(_Blob)]
    protect.restype = _w.BOOL
    if not protect(_c.byref(blob_in), "LunaGrammar API key", None, None, None, 0, _c.byref(blob_out)):
        raise AppError("Windows could not protect the API key.")
    try:
        protected = _c.string_at(blob_out.pb_data, blob_out.cb_data)
    finally:
        kernel32.LocalFree(blob_out.pb_data)
    path = _dpapi_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(protected)


def load_api_key_dpapi() -> str | None:
    """Return the DPAPI-stored key, or None if there is none / it cannot
    be read. Returns None (never raises) off Windows."""
    if sys.platform != "win32":
        return None
    path = _dpapi_path()
    if not path.exists():
        return None
    try:
        import ctypes as _c
        from ctypes import wintypes as _w

        class _Blob(_c.Structure):
            _fields_ = [("cb_data", _w.DWORD), ("pb_data", _c.POINTER(_c.c_byte))]

        crypt32 = _c.WinDLL("crypt32", use_last_error=True)
        kernel32 = _c.WinDLL("kernel32", use_last_error=True)
        protected = path.read_bytes()
        blob_in = _Blob(len(protected), _c.cast(_c.create_string_buffer(protected, len(protected)), _c.POINTER(_c.c_byte)))
        blob_out = _Blob()
        unprotect = crypt32.CryptUnprotectData
        unprotect.argtypes = [_c.POINTER(_Blob), _c.POINTER(_w.LPWSTR), _c.c_void_p, _c.c_void_p, _c.c_void_p, _w.DWORD, _c.POINTER(_Blob)]
        unprotect.restype = _w.BOOL
        if not unprotect(_c.byref(blob_in), None, None, None, None, 0, _c.byref(blob_out)):
            return None
        try:
            return _c.string_at(blob_out.pb_data, blob_out.cb_data).decode("utf-8")
        finally:
            kernel32.LocalFree(blob_out.pb_data)
    except Exception:
        return None


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    stored = load_api_key_dpapi()
    if stored:
        return stored.strip()
    raise AppError("OPENAI_API_KEY is missing. Set it before starting Luna Grammar.")
