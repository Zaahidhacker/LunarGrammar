import sys
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import AppError, Settings

if sys.platform == "win32":
    import win32 as win
    from text_selection import Automation, Guard, Selection, Trigger, correct_selection
    from windows_hotkey import Listener, single_instance


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class SelectionFlowTests(unittest.TestCase):
    def setUp(self):
        self.target = win.Target(10, 20, 30, 40)
        self.trigger = Trigger(self.target, 0)
        self.stop = Event()
        self.clipboard = Mock()
        self.engine = Mock()
        self.original = "i went home"
        self.engine.correct.return_value = "I went home."
        self.current = self.patch("current_target", return_value=self.target)
        self.tick = self.patch("last_input", return_value=123)
        self.patch("keys_down", return_value=False)
        self.patch("executable", return_value="example.exe")
        self.patch("native_edit", return_value=True)
        self.patch("window_pid", return_value=self.target.pid)
        self.style = self.patch("get_style", return_value=0)
        self.patch("is_enabled", return_value=True)
        self.patch("send_window_message", return_value=0)
        self.offsets = self.patch("native_range", return_value=(5, 16))
        self.capacity = self.patch("check_native_capacity")
        self.replace = self.patch("replace_native")
        self.clipboard.copy_native.return_value = self.original

    def patch(self, name, **kwargs):
        patcher = patch.object(win, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def run_flow(self, settings=Settings(), automation=None):
        correct_selection(
            self.trigger, lambda: 0, self.stop, settings, automation, self.clipboard, self.engine,
        )

    def test_native_fallback_rechecks_and_replaces_only_after_response(self):
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.assertEqual(self.clipboard.copy_native.call_count, 2)
        self.replace.assert_called_once_with(20, "I went home.")

    def test_professional_mode_reuses_the_same_capture_and_replacement_path(self):
        self.trigger = Trigger(self.target, 0, mode='professional_3')
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, mode='professional_3', fallback_models=True)
        self.replace.assert_called_once_with(20, 'I went home.')

    def test_input_between_chord_commit_and_capture_cancels_before_api(self):
        self.trigger = Trigger(self.target, 0, input_stamp=124)
        with self.assertRaisesRegex(AppError, 'before capture'):
            self.run_flow()
        self.engine.correct.assert_not_called()
        self.replace.assert_not_called()

    def test_classic_edit_can_refine_without_any_clipboard_access(self):
        read = self.patch("classic_selection", return_value=self.original)
        self.run_flow()
        self.assertEqual(read.call_count, 2)
        self.assertFalse(self.clipboard.mock_calls)
        self.replace.assert_called_once_with(20, "I went home.")

    def test_api_failure_and_noop_do_not_replace(self):
        self.engine.correct.side_effect = AppError("API failure")
        with self.assertRaisesRegex(AppError, "API failure"):
            self.run_flow()
        self.engine.correct.side_effect = None
        self.engine.correct.return_value = self.original
        self.run_flow()
        self.replace.assert_not_called()
        self.clipboard.paste.assert_not_called()

    def test_empty_password_and_excluded_targets_never_call_api(self):
        self.offsets.return_value = (5, 5)
        self.run_flow()
        self.style.return_value = win.ES_PASSWORD
        with self.assertRaisesRegex(AppError, "protected"):
            self.run_flow()
        with self.assertRaisesRegex(AppError, "excluded"):
            self.run_flow(Settings(excluded_apps=("example.exe",)))
        self.engine.correct.assert_not_called()
        self.clipboard.copy_native.assert_not_called()

    def test_focus_and_input_changes_after_api_cancel(self):
        def focus_change(_, **kwargs):
            self.current.return_value = win.Target(11, 21, 31, 41)
            return "I went home."

        self.engine.correct.side_effect = focus_change
        with self.assertRaisesRegex(AppError, "canceled"):
            self.run_flow()
        self.current.return_value = self.target

        def new_input(_, **kwargs):
            self.tick.return_value += 1
            return "I went home."

        self.engine.correct.side_effect = new_input
        with self.assertRaisesRegex(AppError, "canceled"):
            self.run_flow()
        self.replace.assert_not_called()

    def test_identical_text_at_different_native_offsets_is_rejected(self):
        self.offsets.side_effect = [(5, 16), (20, 31)]
        with self.assertRaisesRegex(AppError, "selection moved"):
            self.run_flow()
        self.replace.assert_not_called()

    def test_native_control_with_insufficient_capacity_is_not_edited(self):
        self.capacity.side_effect = AppError("text limit")
        with self.assertRaisesRegex(AppError, "text limit"):
            self.run_flow()
        self.replace.assert_not_called()

    def test_ui_automation_requires_matching_range_and_text(self):
        automation = Mock()
        automation.com_error = OSError
        automation.writable.return_value = True
        element, pattern, original_range = Mock(), Mock(), Mock()
        automation.focused_edit.return_value = element, element, pattern, None
        live = automation.selection.return_value
        live.Compare.return_value = False
        live.GetText.return_value = self.original
        selection = Selection(self.original, Guard(self.trigger, lambda: 0, self.stop, 123),
                              element=element, text_range=original_range, owner=element)
        with self.assertRaisesRegex(AppError, "selection changed"):
            selection.verify(automation, self.clipboard, 6000)
        live.Compare.return_value = True
        selection.verify(automation, self.clipboard, 6000)
        live.Compare.assert_called_with(original_range)

    def test_value_fallback_rechecks_unique_selected_text_before_preparing_paste(self):
        automation = Mock(com_error=OSError)
        element = Mock()
        automation.focused_edit.return_value = element, None, None, None
        automation.editable_value.return_value = "prefix i went home suffix"
        self.patch("native_edit", return_value=False)
        self.clipboard.copy_keyboard.return_value = self.original

        def verify_before_dispatch(_text, _target, verify, _guard):
            self.assertEqual(self.clipboard.copy_keyboard.call_count, 2)
            verify()
            self.assertEqual(self.clipboard.copy_keyboard.call_count, 2)

        self.clipboard.paste.side_effect = verify_before_dispatch
        self.run_flow(automation=automation)
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.clipboard.paste.assert_called_once()

    def test_value_fallback_rejects_duplicate_copied_text(self):
        automation = Mock(com_error=OSError)
        automation.focused_edit.return_value = Mock(), None, None, None
        automation.editable_value.return_value = "i went home and i went home"
        self.patch("native_edit", return_value=False)
        self.clipboard.copy_keyboard.return_value = self.original
        with self.assertRaisesRegex(AppError, "one selection"):
            self.run_flow(automation=automation)
        self.engine.correct.assert_not_called()

    def test_cold_chromium_provider_is_refreshed_once_before_using_selection(self):
        automation = Mock(com_error=OSError)
        element, pattern = Mock(), Mock()
        automation.focused_edit.side_effect = [
            (element, None, None, None), (element, element, pattern, None),
            (element, element, pattern, None),
        ]
        automation.editable_value.return_value = None
        automation.is_edit_control.side_effect = [False, True]
        automation.selection.return_value.GetText.return_value = self.original
        automation.writable.return_value = True
        self.patch("executable", return_value="chrome.exe")
        self.patch("native_edit", return_value=False)
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow(automation=automation)
        automation.client.ElementFromHandle.assert_called_once_with(self.target.window)
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)

    def test_browser_without_accessibility_patterns_uses_copy_and_recopy(self):
        self.patch("native_edit", return_value=False)
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.patch("executable", return_value="msedge.exe")
        self.clipboard.copy_keyboard.return_value = self.original
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.assertEqual(self.clipboard.copy_keyboard.call_count, 2)
        self.clipboard.paste.assert_called_once()
        self.replace.assert_not_called()

    def test_embedded_chromium_focus_can_use_the_same_guarded_fallback(self):
        self.target = win.Target(10, 20, 30, 40, focus_pid=41)
        self.trigger = Trigger(self.target, 0)
        self.current.return_value = self.target
        self.patch("window_pid", return_value=41)
        self.patch("native_edit", return_value=False)
        self.patch("class_name", return_value="chrome_renderwidgethosthwnd")
        self.clipboard.copy_keyboard.return_value = self.original
        self.run_flow()
        self.assertEqual(self.clipboard.copy_keyboard.call_count, 2)
        self.clipboard.paste.assert_called_once()

    def test_focused_chromium_widget_child_of_native_host_can_use_fallback(self):
        automation = Mock(com_error=OSError)
        wrapper = Mock()
        automation.focused_edit.return_value = wrapper, None, None, None
        automation.is_edit_control.return_value = False
        automation.focused_element.return_value = wrapper
        self.patch("native_edit", return_value=False)
        self.patch("class_name", side_effect=lambda hwnd: (
            "chrome_widgetwin_0" if hwnd == self.target.focus else "winuidesktopwin32windowclass"
        ))
        self.patch("get_ancestor", return_value=self.target.window)
        self.clipboard.copy_keyboard.return_value = self.original
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow(automation=automation)
        automation.client.ElementFromHandle.assert_called_once_with(self.target.focus)
        self.assertEqual(self.clipboard.copy_keyboard.call_count, 2)
        self.clipboard.paste.assert_called_once()

    def test_unattached_chromium_widget_does_not_authorize_native_host(self):
        self.patch("native_edit", return_value=False)
        self.patch("class_name", return_value="chrome_widgetwin_0")
        self.patch("get_ancestor", return_value=999)
        with self.assertRaisesRegex(AppError, "safe copy target"):
            self.run_flow()
        self.clipboard.copy_keyboard.assert_not_called()

    def test_browser_recopy_mismatch_and_focus_switch_never_paste(self):
        self.patch("native_edit", return_value=False)
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.patch("executable", return_value="chrome.exe")
        self.clipboard.copy_keyboard.side_effect = [self.original, "different selection"]
        with self.assertRaisesRegex(AppError, "Re-copy"):
            self.run_flow()
        self.clipboard.paste.assert_not_called()

        self.clipboard.copy_keyboard.side_effect = [self.original]

        def change_target(_text, **kwargs):
            self.current.return_value = win.Target(11, 21, 31, 41)
            return "I went home."

        self.engine.correct.side_effect = change_target
        with self.assertRaisesRegex(AppError, "target changed"):
            self.run_flow()
        self.clipboard.paste.assert_not_called()

    def test_waits_for_hotkey_release_before_keyboard_copy(self):
        self.patch("native_edit", return_value=False)
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.patch("executable", return_value="chrome.exe")
        down = self.patch("keys_down", side_effect=[True, True] + [False] * 15)
        self.engine.correct.return_value = self.original

        def copy(*_):
            self.assertGreaterEqual(down.call_count, 4)
            return self.original

        self.clipboard.copy_keyboard.side_effect = copy
        with patch.object(self.stop, "wait", wraps=self.stop.wait) as wait:
            self.run_flow()
            self.assertEqual(wait.call_count, 2)

    def test_guard_seals_the_input_timestamp_after_its_own_copy(self):
        self.patch("tick_count", return_value=500)
        guard = Guard(self.trigger, lambda: 0, self.stop, 123)
        self.assertEqual(guard.begin_keyboard(), 500)
        self.tick.return_value = 516
        guard.finish_copy()
        self.assertEqual(guard.input_tick, 516)
        self.assertIsNone(guard.synthetic_tick)
        self.tick.return_value = 520
        with self.assertRaisesRegex(AppError, "User input changed"):
            guard.check()

    def test_native_injection_only_emits_copy_or_paste_keys(self):
        sent = []

        def send(count, inputs, _size):
            self.assertTrue(all(item.data.keyboard.extra == win.INPUT_TAG for item in inputs))
            sent.extend(item.data.keyboard.key for item in inputs)
            return count

        self.patch("send_input", side_effect=send)
        win.edit_shortcut("C", 123)
        win.edit_shortcut("V", 124)
        self.assertEqual(sent, [0x11, 0x43, 0x43, 0x11, 0x11, 0x56, 0x56, 0x11])
        with self.assertRaises(ValueError):
            win.edit_shortcut("\r")

    def test_opaque_unknown_application_is_not_sent_ctrl_c(self):
        self.patch("native_edit", return_value=False)
        with self.assertRaisesRegex(AppError, "safe copy target"):
            self.run_flow()
        self.clipboard.copy_keyboard.assert_not_called()
        self.engine.correct.assert_not_called()

    def test_detected_browser_password_does_not_fall_back(self):
        self.patch("native_edit", return_value=False)
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.patch("executable", return_value="chrome.exe")
        automation = Mock(com_error=OSError)
        automation.focused_edit.side_effect = AppError("protected", "Protected field")
        with self.assertRaisesRegex(AppError, "protected"):
            self.run_flow(automation=automation)
        self.clipboard.copy_keyboard.assert_not_called()

    def test_ancestor_text_pattern_requires_active_caret_at_selection_boundary(self):
        automation = object.__new__(Automation)
        automation.types = SimpleNamespace(
            UIA_EditControlTypeId=1, UIA_DocumentControlTypeId=2, UIA_CustomControlTypeId=3,
            UIA_GroupControlTypeId=4, UIA_PaneControlTypeId=5, UIA_TextPatternId=11,
            UIA_TextPattern2Id=12, IUIAutomationTextPattern2=object(),
        )
        automation.client = Mock()
        focus = Mock(CurrentProcessId=self.target.pid, CurrentIsPassword=False,
                     CurrentIsEnabled=True, CurrentControlType=7)
        host = Mock(CurrentProcessId=self.target.pid, CurrentIsPassword=False,
                    CurrentIsEnabled=True, CurrentControlType=1)
        automation.client.GetFocusedElement.return_value = focus
        automation.client.ControlViewWalker.GetParentElement.side_effect = [host, None]
        pattern = host.GetCurrentPattern.return_value.QueryInterface.return_value
        caret = Mock()
        pattern.GetCaretRange.return_value = True, caret
        self.assertEqual(automation.focused_edit(self.target), (focus, host, pattern, caret))
        host.GetCurrentPattern.assert_called_once_with(12)
        ranges = pattern.GetSelection.return_value
        ranges.Length = 1
        selected = ranges.GetElement.return_value
        selected.CompareEndpoints.return_value = 1
        with self.assertRaisesRegex(AppError, "active caret"):
            automation.selection(pattern, caret)
        selected.CompareEndpoints.side_effect = [1, 0]
        self.assertIs(automation.selection(pattern, caret), selected)

    def test_selection_with_embedded_objects_and_soft_breaks_is_sanitized_and_refined(self):
        text_with_objects = "hello\x0bworld \ufffc this is a test"
        self.patch("classic_selection", return_value=text_with_objects)
        self.engine.correct.return_value = "Hello world this is a test."
        self.run_flow()
        self.engine.correct.assert_called_once_with("hello\nworld   this is a test", fallback_models=True)
        self.replace.assert_called_once_with(20, "Hello world this is a test.")

    def test_word_and_office_document_target_can_use_keyboard_fallback(self):
        self.patch("native_edit", return_value=False)
        self.patch("executable", return_value="winword.exe")
        self.patch("class_name", return_value="_wwg")
        self.clipboard.copy_keyboard.return_value = self.original
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.clipboard.paste.assert_called_once()

    def test_whatsapp_and_chat_editors_can_use_keyboard_fallback(self):
        self.patch("native_edit", return_value=False)
        self.patch("executable", return_value="whatsapp.exe")
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.clipboard.copy_keyboard.return_value = self.original
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.clipboard.paste.assert_called_once()

    def test_vscode_and_code_editors_can_use_keyboard_fallback(self):
        self.patch("native_edit", return_value=False)
        self.patch("executable", return_value="code.exe")
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.clipboard.copy_keyboard.return_value = self.original
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.clipboard.paste.assert_called_once()

    def test_telegram_and_qt_editors_can_use_keyboard_fallback(self):
        self.patch("native_edit", return_value=False)
        self.patch("executable", return_value="telegram.exe")
        self.patch("class_name", return_value="qt6qwindowicon")
        self.clipboard.copy_keyboard.return_value = self.original
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.clipboard.paste.assert_called_once()

    def test_recopy_no_fresh_text_with_unchanged_input_succeeds(self):
        self.patch("native_edit", return_value=False)
        self.patch("executable", return_value="code.exe")
        self.patch("class_name", return_value="chrome_widgetwin_1")
        self.clipboard.copy_keyboard.side_effect = [
            self.original,
            AppError("The editor did not copy fresh text.", "Nothing copied", "capture.no_fresh_text"),
        ]
        self.clipboard.paste.side_effect = lambda _text, _target, verify, _guard: verify()
        self.run_flow()
        self.engine.correct.assert_called_once_with(self.original, fallback_models=True)
        self.clipboard.paste.assert_called_once()


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class ListenerTests(unittest.TestCase):
    def test_second_hotkey_while_busy_is_not_queued(self):
        listener = Listener(Settings(), "test-key")
        listener.ready.set()
        listener.registered = True
        with patch.object(win, "current_target", return_value=win.Target(10, 20, 30, 40)):
            for _ in range(2):
                listener.shortcut_events.put(('start', 0, 1, 1, 1))
                listener.shortcut_events.put(('commit', 0, 2, 2, 1))
                listener.dispatch_shortcut()
                listener.handle_message(0, win.WM_HOTKEY, win.HOTKEY_ID, 0)
        self.assertEqual(listener.jobs.qsize(), 1)

    def test_queued_focus_event_from_before_hotkey_does_not_cancel(self):
        listener = Listener(Settings(), "test-key")
        listener.active_trigger = Trigger(win.Target(10, 20, 30, 40), 0, message_time=4)
        listener.busy.set()
        listener.handle_focus(None, 0x0003, 10, 0, 0, 0, 0xFFFFFFFE)
        self.assertEqual(listener.epoch, 0)
        listener.handle_focus(None, 0x0003, 10, 0, 0, 0, 5)
        self.assertEqual(listener.epoch, 1)

    def test_instance_lock_releases_and_rejects_duplicates(self):
        with patch("windows_hotkey.MUTEX_NAME", r"Local\LunaGrammar.Unittest." + str(id(self))):
            with single_instance():
                with self.assertRaisesRegex(AppError, "already running"):
                    with single_instance():
                        self.fail("The second instance acquired the lock.")
            with single_instance():
                pass
