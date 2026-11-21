"""User settings. Secrets come exclusively from the process environment."""

import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
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


def load_settings(path: Path) -> Settings:
    return parse_settings(read_settings(path))


def read_settings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except (OSError, ValueError):
        raise AppError("Could not read settings.json. Check that it contains valid JSON.") from None
    if not isinstance(data, dict) or data.keys() - Settings.__dataclass_fields__.keys():
        raise AppError("settings.json must contain only the documented settings.")
    return data


def parse_settings(data: dict) -> Settings:
    defaults = Settings()
    model = os.environ.get("LUNA_GRAMMAR_MODEL", data.get("model", defaults.model))
    timeout = data.get("timeout_seconds", defaults.timeout_seconds)
    limit = data.get("max_selection_chars", defaults.max_selection_chars)
    excluded = data.get("excluded_apps", [])
    if not isinstance(model, str) or not model.strip():
        raise AppError("Set a nonempty OpenAI model ID.")
    if type(timeout) not in (int, float) or not 1 <= timeout <= 60 or not math.isfinite(timeout):
        raise AppError("timeout_seconds must be between 1 and 60.")
    if type(limit) is not int or not 1 <= limit <= 20000:
        raise AppError("max_selection_chars must be an integer between 1 and 20000.")
    if not isinstance(excluded, list) or any(
        not isinstance(name, str)
        or PureWindowsPath(name).name != name
        or not name.casefold().endswith(".exe")
        for name in excluded
    ):
        raise AppError("excluded_apps must be a list of executable names such as notepad.exe.")
    toggles = {}
    for name in ("enabled", "feedback", "expand_shorthand"):
        value = data.get(name, getattr(defaults, name))
        if type(value) is not bool:
            raise AppError(f"{name} must be true or false.")
        toggles[name] = value
    appearance = data.get("appearance", defaults.appearance)
    motion = data.get("motion", defaults.motion)
    if appearance not in ("dark", "light") or motion not in ("system", "reduced"):
        raise AppError("Use dark or light for appearance, and system or reduced for motion.")
    return Settings(model.strip(), timeout, limit, tuple(name.casefold() for name in excluded),
                    **toggles, appearance=appearance, motion=motion)


def update_settings(changes: dict, path: Path = SETTINGS_PATH):
    data = read_settings(path) | changes
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


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise AppError("OPENAI_API_KEY is missing. Set it before starting Luna Grammar.")
    return key
