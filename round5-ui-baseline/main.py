"""Luna Grammar entry point."""

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import AppError, SETTINGS_PATH, api_key, load_settings
from diagnostics import OperationFilter, error_frames


def configure_logging(diagnostic: bool):
    logging.getLogger("comtypes").setLevel(logging.WARNING)
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    try:
        folder = Path(os.environ["LOCALAPPDATA"]) / "LunaGrammar"
        folder.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            folder / "luna-grammar.log", maxBytes=128_000, backupCount=1, encoding="utf-8",
        ))
    except (KeyError, OSError):
        if sys.stderr is not None:
            print("Could not open the Luna Grammar log file.", file=sys.stderr)
    handlers = handlers or [logging.NullHandler()]
    for handler in handlers:
        handler.addFilter(OperationFilter())
    logging.basicConfig(
        level=logging.DEBUG if diagnostic else logging.INFO,
        format="%(asctime)s %(levelname)s op=%(operation_id)s %(message)s",
        handlers=handlers,
    )


def check():
    from windows_hotkey import check_hotkey
    from input_monitor import InputMonitor

    failed = False
    try:
        with InputMonitor():
            logging.info("Editing-input monitoring initialized and released.")
    except AppError as error:
        failed = True
        logging.error("event=command.failed category=%s detail=%s", error.code, error)
    try:
        from text_selection import Automation

        Automation()
        logging.info("Windows UI Automation initialized.")
    except Exception as error:
        failed = True
        logging.error("UI Automation could not initialize (%s). Verify comtypes is installed.",
                      type(error).__name__)
    try:
        import openai

        logging.info("OpenAI Python SDK %s is installed.", openai.__version__)
    except ImportError:
        failed = True
        logging.error("OpenAI SDK is missing. Run pip install -r requirements.txt.")
    try:
        import ssl

        ssl.create_default_context()
        logging.info("TLS initialized with certificate verification enabled.")
    except (ImportError, OSError) as error:
        failed = True
        logging.error("TLS initialization failed (%s).", type(error).__name__)
    try:
        from pill_art import font

        font(13)
        logging.info("Overlay renderer and Poppins font are available.")
    except (ImportError, OSError):
        failed = True
        logging.error("Overlay assets or Pillow are missing. Run pip install -r requirements.txt.")
    try:
        check_hotkey()
        logging.info("Ctrl+Win+Z registration succeeded and was released.")
    except AppError as error:
        failed = True
        logging.error("event=command.failed category=%s detail=%s", error.code or "command.rejected", error)
    if os.environ.get("OPENAI_API_KEY", "").strip():
        logging.info("OPENAI_API_KEY is present. No API request was made.")
    else:
        logging.info("OPENAI_API_KEY is missing. Set it before starting the listener.")
    return int(failed)


def inspect_clipboard():
    import win32 as win
    from clipboard_manager import Clipboard, clipboard_owner, describe, format_name, formats, sequence

    with Clipboard(None).locked():
        owner = clipboard_owner()
        pid = win.window_pid(owner) if owner else 0
        try:
            app = win.executable(pid) if pid else "-"
        except AppError:
            app = "-"
        logging.info("event=clipboard.inspection owner_app=%r sequence=%d formats=%s", app, sequence(),
                     ", ".join(describe(fmt, format_name(fmt)) for fmt in formats()) or "(empty)")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Correct selected text with Ctrl+Win+Z.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="check local setup without calling OpenAI")
    modes.add_argument("--check-api", action="store_true", help="check access to the configured model")
    modes.add_argument("--inspect-clipboard", action="store_true", help="log clipboard format names only")
    modes.add_argument("--settings", action="store_true", help="open Luna Grammar settings")
    modes.add_argument("--stop", action="store_true", help="stop the background listener")
    parser.add_argument("--diagnostic", action="store_true", help="enable additional status logging")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Luna Grammar requires Windows.")
    configure_logging(args.diagnostic)
    try:
        if args.stop:
            from windows_hotkey import stop_listener

            if stop_listener():
                logging.info("Stop requested. A pending request may take a moment to finish.")
            else:
                logging.info("Luna Grammar is not running.")
            return 0
        if args.settings:
            from settings_window import show_settings

            return show_settings()
        if args.inspect_clipboard:
            return inspect_clipboard()
        settings = load_settings(SETTINGS_PATH)
        if args.check:
            return check()
        key = api_key()
        if args.check_api:
            from grammar_engine import GrammarEngine

            engine = GrammarEngine(settings, key)
            try:
                engine.check_model()
                logging.info("The configured model is available to your OpenAI project.")
            finally:
                engine.close()
            return 0
        from windows_hotkey import Listener

        return Listener(settings, key).run()
    except AppError as error:
        logging.error("%s", error)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        logging.error("Luna Grammar stopped after an unexpected error (%s). Run --check.", type(error).__name__)
        logging.debug("event=command.unexpected_failure frames=%s", error_frames(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
