import sys
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from config import AppError

if sys.platform == "win32":
    import clipboard_manager as cm
    import win32 as win


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.target = win.Target(11, 12, 13, 14)
        self.patch("register_format", return_value=0xC100)
        self.clipboard = cm.Clipboard(99)
        self.clipboard.locked = Mock(side_effect=lambda **_options: nullcontext())
        self.backup = [Mock()]
        self.patch("snapshot", return_value=self.backup)
        self.patch("empty_clipboard", return_value=True)
        self.patch("has_format", return_value=True)
        self.patch("set_data", return_value=None)
        self.owner = self.patch("clipboard_owner", return_value=99)
        self.token_current = Mock(side_effect=lambda _token: self.owner.return_value == 99)
        self.clipboard.matches_token = self.token_current
        self.patch("clipboard_reader", return_value=None)
        self.restore = self.patch("restore")
        self.item = Mock(handle=1)
        self.marker = Mock(handle=2)
        self.guard = Mock()
        self.guard.begin_keyboard.return_value = 123
        self.guard.unchanged_input.return_value = True
        self.patch("memory_item", side_effect=[self.item, self.marker])
        self.keyboard = self.patch("win.edit_shortcut", side_effect=self.render)

    def patch(self, name, **kwargs):
        patcher = patch(f"clipboard_manager.{name}", **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def render(self, key, _timestamp):
        if key == "V":
            self.clipboard.render(cm.CF_UNICODETEXT)

    def test_paste_offer_renders_and_restores_original_formats(self):
        self.clipboard.paste("Hi 😀", self.target, Mock(), self.guard)
        self.marker.publish.assert_called_once()
        self.item.publish.assert_called_once()
        self.restore.assert_called_once_with(self.backup)
        self.assertIsNone(self.clipboard.offer)

    def test_focus_change_during_preparation_restores_without_pasting(self):
        with self.assertRaisesRegex(AppError, "focus changed"):
            self.clipboard.paste("Hi", self.target, Mock(side_effect=AppError("focus changed")),
                                 self.guard)
        self.keyboard.assert_not_called()
        self.item.publish.assert_not_called()
        self.restore.assert_called_once_with(self.backup)

    def test_new_clipboard_owner_is_preserved(self):
        self.owner.return_value = 100
        with self.assertRaisesRegex(AppError, "clipboard changed"):
            self.clipboard.paste("Hi", self.target, Mock(), self.guard)
        self.keyboard.assert_not_called()
        self.restore.assert_not_called()

    def test_copy_does_not_restore_over_a_newer_item_from_same_process(self):
        self.patch("sequence", side_effect=[100, 100, 101, 102])
        self.patch("win.send_window_message")
        self.patch("win.window_pid", return_value=self.target.pid)
        self.assertEqual(self.clipboard.copy_native(self.target, 100, Mock()), "")
        self.restore.assert_not_called()

    def test_keyboard_copy_waits_for_the_writer_to_finish_committing_formats(self):
        self.patch("sequence", side_effect=[100, 100, 101, 101, 105])
        self.owner.return_value = self.target.focus
        self.patch("clipboard_reader", return_value=self.target.focus)
        self.patch("win.window_pid", return_value=self.target.pid)
        self.patch("selected_text", return_value="fresh 😀")
        self.assertEqual(self.clipboard.copy_keyboard(self.target, 100, self.guard), "fresh 😀")
        self.keyboard.assert_called_once_with("C", 123)
        self.restore.assert_called_once_with(self.backup)

    def test_keyboard_copy_does_not_attribute_another_windows_lock_to_target(self):
        self.patch("sequence", side_effect=[100, 100, 101, 101, 105])
        self.owner.return_value = self.target.focus
        self.patch("clipboard_reader", return_value=101)
        self.patch("win.window_pid", return_value=self.target.pid)
        read = self.patch("selected_text")
        with self.assertRaisesRegex(AppError, "did not copy fresh text"):
            self.clipboard.copy_keyboard(self.target, 100, self.guard)
        read.assert_not_called()
        self.restore.assert_not_called()

    def test_keyboard_copy_can_attribute_a_hosted_webview_writer(self):
        self.patch("sequence", side_effect=[100, 100, 101, 101, 101])
        self.patch("win.window_pid", return_value=151)
        self.patch("win.class_name", return_value="chrome_widgetwin_0")
        self.patch("win.get_ancestor", return_value=self.target.window)
        child = self.patch("win.webview_child_of", return_value=True)
        self.patch("selected_text", return_value="webview selection")
        self.assertEqual(self.clipboard.copy_keyboard(self.target, 100, self.guard), "webview selection")
        child.assert_called_once_with(151, self.target.pid)
        self.restore.assert_called_once_with(self.backup)

    def test_another_hosts_webview_cannot_read_delayed_paste(self):
        self.patch("clipboard_reader", return_value=101)
        self.patch("win.window_pid", return_value=151)
        self.patch("win.class_name", return_value="chrome_widgetwin_0")
        self.patch("win.get_ancestor", return_value=self.target.window)
        self.patch("win.webview_child_of", return_value=False)
        offer = cm.PasteOffer(self.item, self.target, self.guard.unchanged_input, b"fixture")
        offer.armed.set()
        self.clipboard.offer = offer
        self.clipboard.render(cm.CF_UNICODETEXT)
        self.item.publish.assert_not_called()

    def test_keyboard_copy_restores_after_programmatic_focus_loss(self):
        self.patch("sequence", side_effect=[100, 100, 101, 101, 101])
        self.patch("win.window_pid", return_value=self.target.pid)
        self.guard.check_input.side_effect = AppError("focus changed")
        read = self.patch("selected_text")
        with self.assertRaisesRegex(AppError, "focus changed"):
            self.clipboard.copy_keyboard(self.target, 100, self.guard)
        read.assert_not_called()
        self.restore.assert_called_once_with(self.backup)

    def test_copy_does_not_restore_over_newer_input(self):
        self.patch("sequence", side_effect=[100, 100, 101, 101, 101])
        self.patch("win.window_pid", return_value=self.target.pid)
        self.guard.input_matches.return_value = False
        read = self.patch("selected_text")
        with self.assertRaisesRegex(AppError, "did not copy fresh text"):
            self.clipboard.copy_keyboard(self.target, 100, self.guard)
        read.assert_not_called()
        self.restore.assert_not_called()

    def test_paste_does_not_restore_over_replaced_marker_with_same_owner(self):
        self.token_current.side_effect = [True, False]
        self.clipboard.paste("Hi", self.target, Mock(), self.guard)
        self.restore.assert_not_called()

    def test_keyboard_copy_without_fresh_item_never_reads_the_old_text(self):
        self.patch("sequence", return_value=100)
        self.patch("time.monotonic", side_effect=[0, 1])
        read = self.patch("selected_text")
        with self.assertRaisesRegex(AppError, "did not copy fresh text"):
            self.clipboard.copy_keyboard(self.target, 100, self.guard)
        read.assert_not_called()
        self.restore.assert_not_called()

    def test_copy_preserves_safe_formats_when_unsupported_format_present(self):
        # This test exercises the best-effort fallback (safe_snapshot); the
        # clipboard fails closed by default, so opt out of strict mode here.
        self.clipboard.strict_preservation = False
        with patch.object(cm, "snapshot", side_effect=AppError("unsupported", code="clipboard.preservation_limited")):
            safe_backup = [Mock()]
            with patch.object(cm, "safe_snapshot", return_value=safe_backup):
                self.patch("sequence", side_effect=[100, 100, 101, 101, 101])
                self.owner.return_value = self.target.focus
                self.patch("win.window_pid", return_value=self.target.pid)
                self.patch("selected_text", return_value="hello")
                result = self.clipboard.copy_keyboard(self.target, 100, self.guard)
                self.assertEqual(result, "hello")
                self.restore.assert_called_once_with(safe_backup)

    def test_paste_fallback_to_direct_rendering_when_delayed_rendering_times_out(self):
        # When render() is never called by the target application during delayed rendering,
        # paste should fall back to publishing the item directly and succeed.
        def no_render_edit_shortcut(_key, _ts):
            pass  # Does not call render()
        self.keyboard.side_effect = no_render_edit_shortcut
        self.clipboard.paste("Hi fallback", self.target, Mock(), self.guard)
        self.marker.publish.assert_called_once()
        self.item.publish.assert_called_once()
        self.restore.assert_called_once_with(self.backup)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class ClipboardFormatTests(unittest.TestCase):
    def test_cached_ole_requires_zero_marker_and_an_absent_or_trusted_owner(self):
        formats = {0xC001: "DataObject", 0xC002: "Ole Private Data"}
        marker = cm.memory_item(0xC001, bytes(8))
        try:
            with patch.object(cm, "clipboard_owner", return_value=None):
                with patch.object(cm, "get_data", return_value=marker.handle):
                    self.assertTrue(cm.cached_ole_item(formats))
                    self.assertFalse(cm.cached_ole_item({0xC001: "DataObject"}))
            with patch.object(cm, "clipboard_owner", return_value=99):
                with patch.object(cm, "get_data", return_value=marker.handle):
                    self.assertFalse(cm.cached_ole_item(formats))
                    self.assertTrue(cm.cached_ole_item(formats, trusted_owner=99))
        finally:
            marker.free()

    def test_nonzero_ole_reference_is_never_a_cached_snapshot(self):
        marker = cm.memory_item(0xC001, b"\x01" + bytes(7))
        try:
            with patch.object(cm, "clipboard_owner", return_value=None):
                with patch.object(cm, "get_data", return_value=marker.handle):
                    self.assertFalse(cm.cached_ole_item(
                        {0xC001: "DataObject", 0xC002: "Ole Private Data"}))
        finally:
            marker.free()

    def test_chromium_frame_origin_is_a_supported_serialized_format(self):
        def name(_format, buffer, _size):
            buffer.value = "Chromium internal source RFH token"
            return len(buffer.value)

        with patch.object(cm, "get_format_name", side_effect=name):
            self.assertTrue(cm.can_duplicate(0xC247))

    def test_unsupported_format_prevents_any_snapshot_reads(self):
        with patch.object(cm, "formats", return_value=iter([cm.CF_UNICODETEXT, 0x0200])):
            with patch.object(cm, "get_data") as read, self.assertRaisesRegex(AppError, "safely preserve"):
                cm.snapshot()
            read.assert_not_called()

    def test_custom_registered_payload_is_cloned_without_a_name_allowlist(self):
        custom = cm.register_format("Luna.Regression.ArbitraryFormat")
        history = cm.register_format("ClipboardHistoryItemId")
        original = cm.memory_item(custom, b"\x00\x8a\xff\x03")
        clones = []
        try:
            with patch.object(cm, "formats", return_value=iter([custom, history])):
                with patch.object(cm, "get_data", return_value=original.handle):
                    clones = cm.snapshot()
            self.assertEqual([item.format for item in clones], [custom, history])
            self.assertTrue(all(item.handle != original.handle for item in clones))
            for item in clones:
                address = cm.global_lock(item.handle)
                try:
                    self.assertEqual(cm.c.string_at(address, 4), b"\x00\x8a\xff\x03")
                finally:
                    cm.global_unlock(item.handle)
        finally:
            for item in [original, *clones]:
                item.free()

    def test_ole_bookkeeping_is_not_cloned_as_an_opaque_global(self):
        for name in ("DataObject", "Ole Private Data"):
            fmt = cm.register_format(name)
            self.assertFalse(cm.can_duplicate(fmt))
            with patch.object(cm, "formats", return_value=iter([fmt])):
                with patch.object(cm, "get_data") as read, self.assertRaises(AppError) as failure:
                    cm.snapshot()
                self.assertEqual(failure.exception.code, "clipboard.preservation_limited")
                read.assert_not_called()

    def test_win32_unicode_clipboard_memory_round_trips_without_clipboard_access(self):
        original = "Zoë 😀\r\nこんにちは"
        item = cm.memory_item(cm.CF_UNICODETEXT, (original + "\0").encode("utf-16-le"))
        clone = cm.ClipboardItem(cm.CF_UNICODETEXT, None)
        try:
            clone.handle = cm.duplicate_data(item.handle, item.format, 0x0002)
            self.assertTrue(clone.handle)
            self.assertNotEqual(clone.handle, item.handle)
            with patch.object(cm, "get_data", return_value=clone.handle):
                self.assertEqual(cm.selected_text(100), original)
                with self.assertRaisesRegex(AppError, "length limit"):
                    cm.selected_text(4)
        finally:
            item.free()
            clone.free()
