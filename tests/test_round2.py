"""Round-2 tests: per-app profiles, focus restore, RichEdit ranges,
API retry, correction history, DPAPI fallback, clipboard back-off.

Windows-only paths are skipped on Linux; the pure-logic paths run
everywhere. Win32 calls are mocked, never executed against a real desktop.
"""

import sys
import unittest
from unittest import mock

sys.path.insert(0, __file__.rsplit("/tests/", 1)[0] if "/tests/" in __file__ else ".")

from config import AppError, Settings
from history import CorrectionHistory
from text_selection import APP_PROFILES, TERMINAL_EXES, profile_for


class ProfileTests(unittest.TestCase):
    def test_terminal_refused(self):
        for exe in ("cmd.exe", "powershell.exe", "wt.exe", "conhost.exe", "pwsh.exe"):
            self.assertTrue(profile_for(exe)["refuse"], exe)
            self.assertEqual(profile_for(exe)["layers"], ())

    def test_firefox_clipboard_first(self):
        self.assertEqual(profile_for("firefox.exe")["layers"][:1], ("clipboard",))

    def test_code_clipboard_first(self):
        self.assertEqual(profile_for("code.exe")["layers"][:1], ("clipboard",))

    def test_chrome_uia_first(self):
        self.assertEqual(profile_for("chrome.exe")["layers"][:1], ("uia",))

    def test_unknown_app_default_layers(self):
        profile = profile_for("notepad.exe")
        self.assertFalse(profile["refuse"])
        self.assertIn("uia", profile["layers"])
        self.assertIn("clipboard", profile["layers"])

    def test_profile_names_case_insensitive(self):
        self.assertEqual(profile_for("Firefox.EXE"), profile_for("firefox.exe"))


class FocusRestoreTests(unittest.TestCase):
    def test_restore_focus_noop_off_windows(self):
        import win32 as win

        if sys.platform == "win32":
            self.skipTest("Windows-only behaviour differs; mocked below")
        target = win.Target(window=1, focus=2, thread=3, pid=4)
        self.assertTrue(win.restore_focus(target))

    def test_restore_focus_calls_attach_and_setfocus(self):
        import ctypes as c
        import win32 as win

        if sys.platform != "win32":
            self.skipTest("needs Windows Win32 bindings")
        target = win.Target(window=1, focus=2, thread=99, pid=4)

        def _gui_info_ok(thread, info_ref):
            # The real GetGUIThreadInfo fills the struct; the fake must
            # too, or restore_focus correctly reports focus did not land.
            c.cast(info_ref, c.POINTER(win.GuiThreadInfo)).contents.focus = target.focus
            return True

        with mock.patch.object(win, "current_thread_id", return_value=7), \
                mock.patch.object(win, "attach_thread_input", return_value=True) as attach, \
                mock.patch.object(win, "set_focus", return_value=2) as focus_fn, \
                mock.patch.object(win, "get_gui_info", side_effect=_gui_info_ok) as gui:
            self.assertTrue(win.restore_focus(target))
            self.assertTrue(attach.called)
            focus_fn.assert_called_once_with(2)

    def test_ime_composing_false_off_windows(self):
        import win32 as win

        self.assertFalse(win.is_ime_composing(123))


class RichEditRangeTests(unittest.TestCase):
    def test_em_ex_constants(self):
        import win32 as win

        self.assertEqual(win.EM_EXGETSEL, 0x0434)
        self.assertEqual(win.EM_EXSETSEL, 0x0435)

    def test_rich_edit_uses_ex_range(self):
        import win32 as win

        if sys.platform == "win32":
            self.skipTest("mocked path is Linux-only here")
        with mock.patch.object(win, "class_name", return_value="richedit50w"), \
                mock.patch.object(win, "rich_edit_range", return_value=(70000, 70010)) as ex:
            self.assertEqual(win.native_range(5), (70000, 70010))
            ex.assert_called_once_with(5)


class ApiRetryTests(unittest.TestCase):
    def _engine(self):
        from grammar_engine import GrammarEngine

        engine = GrammarEngine.__new__(GrammarEngine)
        engine.model = "gpt-4o-mini"
        engine.timeout = 5.0
        engine.expand_shorthand = False
        engine.cache_enabled = False
        engine.cache = None
        engine.fallback_models = None
        engine.custom_prompt = ""
        engine.temperature = 0.0
        return engine

    def test_transient_error_retried_then_succeeds(self):
        engine = self._engine()
        calls = {"n": 0}

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise AppError("The OpenAI request timed out.", "Request timed out", "api.timeout")
            return "Fixed text."

        with mock.patch.object(engine, "_execute_api_call", side_effect=flaky), \
                mock.patch("grammar_engine.time.sleep") as sleep:
            self.assertEqual(engine.correct("Fixd text."), "Fixed text.")
            self.assertEqual(calls["n"], 3)
            self.assertEqual(sleep.call_count, 2)

    def test_non_transient_error_not_retried(self):
        engine = self._engine()
        calls = {"n": 0}

        def failing(**kwargs):
            calls["n"] += 1
            raise AppError("OpenAI rejected OPENAI_API_KEY.", "API key rejected", "api.authentication_failed")

        with mock.patch.object(engine, "_execute_api_call", side_effect=failing):
            with self.assertRaises(AppError):
                engine.correct("Fixd text.")
            self.assertEqual(calls["n"], 1)

    def test_connection_method_exists(self):
        engine = self._engine()
        self.assertTrue(callable(getattr(engine, "test_connection", None)))


class HistoryTests(unittest.TestCase):
    def test_record_and_list_newest_first(self):
        history = CorrectionHistory(max_items=3)
        history.record("a", "A", "grammar", "notepad.exe")
        history.record("b", "B", "grammar", "word.exe")
        items = history.list()
        self.assertEqual([i.original for i in items], ["b", "a"])
        self.assertEqual(items[0].app, "word.exe")

    def test_bounded_size(self):
        history = CorrectionHistory(max_items=2)
        for i in range(5):
            history.record(f"orig{i}", f"fixed{i}", "grammar")
        self.assertEqual(len(history), 2)
        self.assertEqual(history.list()[0].original, "orig4")

    def test_zero_max_disables(self):
        history = CorrectionHistory(max_items=0)
        self.assertIsNone(history.record("a", "A", "grammar"))
        self.assertEqual(len(history), 0)

    def test_clear(self):
        history = CorrectionHistory()
        history.record("a", "A", "grammar")
        history.clear()
        self.assertEqual(len(history), 0)

    def test_set_max_trims(self):
        history = CorrectionHistory(max_items=5)
        for i in range(5):
            history.record(f"o{i}", f"f{i}", "grammar")
        history.set_max_items(2)
        self.assertEqual(len(history), 2)


class DpapiTests(unittest.TestCase):
    def test_store_raises_off_windows(self):
        from config import store_api_key_dpapi

        if sys.platform == "win32":
            self.skipTest("Windows-only storage")
        with self.assertRaises(AppError):
            store_api_key_dpapi("sk-test")

    def test_load_returns_none_off_windows(self):
        from config import load_api_key_dpapi

        if sys.platform == "win32":
            self.skipTest("Windows-only storage")
        self.assertIsNone(load_api_key_dpapi())

    def test_api_key_prefers_env_var(self):
        import os
        from config import api_key

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}):
            self.assertEqual(api_key(), "sk-env")


class SettingsRound2Tests(unittest.TestCase):
    def test_appearance_system_allowed(self):
        settings = Settings(appearance="system")
        self.assertEqual(settings.appearance, "system")

    def test_history_settings_defaults(self):
        settings = Settings()
        self.assertTrue(settings.history_enabled)
        self.assertEqual(settings.max_history_items, 20)


if __name__ == "__main__":
    unittest.main()
