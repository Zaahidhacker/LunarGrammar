import ctypes as c
import sys
import unittest
from threading import Event
from unittest.mock import patch

from config import AppError

if sys.platform == "win32":
    import win32 as win
    import input_monitor as im
    from text_selection import Guard, Trigger


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class InputMonitorTests(unittest.TestCase):
    def setUp(self):
        self.monitor = im.InputMonitor()
        next_hook = patch.object(im, "next_hook", return_value=31)
        self.next_hook = next_hook.start()
        self.addCleanup(next_hook.stop)

    def test_pointer_movement_does_not_change_the_editing_stamp(self):
        self.assertEqual(self.monitor.mouse(0, 0x0200, 0), 31)
        self.assertEqual(self.monitor.stamp(), 0)
        self.next_hook.assert_called_once_with(None, 0, 0x0200, 0)

    def test_mouse_click_and_wheel_cancel_a_pending_edit(self):
        event = im.MouseEvent()
        for message in (0x0201, 0x0202, 0x020A, 0x020E):
            self.monitor.mouse(0, message, c.addressof(event))
        self.assertEqual(self.monitor.stamp(), 4)

    def test_only_lunas_tagged_keyboard_events_are_ignored(self):
        own = im.KeyboardEvent(flags=0x10, extra=win.INPUT_TAG)
        self.monitor.keyboard(0, 0x0100, c.addressof(own))
        self.assertEqual(self.monitor.stamp(), 0)
        external = im.KeyboardEvent(flags=0x10, extra=win.INPUT_TAG ^ 1)
        self.monitor.keyboard(0, 0x0100, c.addressof(external))
        physical = im.KeyboardEvent()
        self.monitor.keyboard(0, 0x0104, c.addressof(physical))
        self.assertEqual(self.monitor.stamp(), 2)
        self.monitor.keyboard(0, 0x0101, c.addressof(physical))
        self.assertEqual(self.monitor.stamp(), 2)

    def test_negative_hook_code_does_not_access_the_event_pointer(self):
        self.assertEqual(self.monitor.keyboard(-1, 0x0100, 0), 31)
        self.assertEqual(self.monitor.mouse(-1, 0x0201, 0), 31)
        self.assertEqual(self.monitor.stamp(), 0)

    def test_tracked_input_does_not_use_the_synthetic_timestamp_tolerance(self):
        target = win.Target(1, 2, 3, 4)
        guard = Guard(Trigger(target, 0), lambda: 0, Event(), 100, synthetic_tick=100)
        with patch.object(win, "current_target", return_value=target):
            with patch.object(win, "editing_input_stamp", return_value=101):
                with self.assertRaisesRegex(AppError, "User input changed"):
                    guard.check_input()

    def test_stopped_monitor_rejects_a_new_edit(self):
        self.monitor.stopped.set()
        with self.assertRaises(AppError) as failure:
            self.monitor.stamp()
        self.assertEqual(failure.exception.code, "input.monitor_failed")

    def test_observed_z_release_overrides_stale_windows_state_but_not_held_modifiers(self):
        def stale(key):
            return 0x8000 if key == win.HOTKEY_KEY else 0
        with patch.object(win,'get_key',side_effect=stale), \
             patch.object(win,'shortcut_key_state',self.monitor.shortcut_pressed):
            self.assertTrue(win.keys_down())  # Unknown at startup: fail closed.
            event=im.KeyboardEvent(key=win.HOTKEY_KEY)
            self.monitor.keyboard(0,0x0101,c.addressof(event))
            self.assertFalse(win.keys_down())  # Z physically released, OS stale.
            self.monitor.keyboard(0,0x0100,c.addressof(event))
            self.assertTrue(win.keys_down())  # Real held Z still blocks capture.
            self.monitor.keyboard(0,0x0101,c.addressof(event))
            with patch.object(win,'get_key',side_effect=lambda key: 0x8000 if key==0x11 else 0):
                self.assertTrue(win.keys_down())  # Ctrl safety check remains.

    def test_reserved_key_releases_always_reach_windows(self):
        self.monitor=im.InputMonitor(lambda *_args: None,lambda:True)
        for key in (0xA2,0x5B,0x5A,0x31):
            event=im.KeyboardEvent(key=key)
            self.monitor.keyboard(0,0x0100,c.addressof(event))
        for key in (0x5A,0x31,0x5B,0xA2):
            event=im.KeyboardEvent(key=key)
            self.assertEqual(self.monitor.keyboard(0,0x0101,c.addressof(event)),31)

    def test_stopped_shortcut_state_fails_closed(self):
        self.monitor.z_down=False
        self.monitor.stopped.set()
        with patch.object(win,'get_key',return_value=0), \
             patch.object(win,'shortcut_key_state',self.monitor.shortcut_pressed):
            with self.assertRaises(AppError):
                win.keys_down()

