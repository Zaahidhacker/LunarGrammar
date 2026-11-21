import ctypes as c
from itertools import permutations
import unittest
from unittest.mock import Mock, patch

from shortcut_state import ShortcutState
from correction_modes import MODE_NAMES
from config import Settings
from windows_hotkey import Listener
import input_monitor as im
import win32 as win


class ShortcutTests(unittest.TestCase):
    def test_modes_orders_release_orders_repeats_and_restarts(self):
        scenarios = 0
        for digit in (0, 0x31, 0x32, 0x33, 0x61, 0x62, 0x63):
            keys = [0xA2, 0x5B, 0x5A] + ([digit] if digit else [])
            for mods in permutations(keys[:2]):
                for tail in permutations(keys[2:]):
                    for releases in permutations(keys):
                        events = []
                        state = ShortcutState(lambda *event: events.append(event))
                        for cycle in range(2):
                            for key in (*mods, *tail):
                                consumed = state.key(key, True, enabled=True)
                                if key in (0x5A, digit):
                                    self.assertTrue(consumed)
                                for _repeat in range(3):
                                    self.assertEqual(state.key(key, True, enabled=True), consumed)
                            self.assertEqual(len([e for e in events if e[0] == 'commit']), cycle)
                            for key in releases:
                                consumed = state.key(key, False, enabled=True)
                                self.assertFalse(consumed)
                        commits = [e for e in events if e[0] == 'commit']
                        self.assertEqual([e[1] for e in commits], [digit % 16 if digit else 0] * 2)
                        self.assertEqual(len([e for e in events if e[0] == 'start']), 2)
                        scenarios += 1
        self.assertEqual(scenarios, 588)

    def test_rollover_after_z_release_and_first_digit_wins(self):
        emit = Mock()
        state = ShortcutState(emit)
        for key in (0xA3, 0x5C, 0x5A):
            state.key(key, True)
        state.key(0x5A, False)
        for key in (0x32, 0x33):
            self.assertTrue(state.key(key, True))
            self.assertFalse(state.key(key, False))
        state.key(0x5C, False)
        state.key(0xA3, False)
        self.assertEqual(emit.call_args.args[:2], ('commit', 2))
        self.assertEqual(emit.call_count, 2)

    def test_navigation_during_an_active_chord_cancels_instead_of_selecting_a_level(self):
        events = []
        state = ShortcutState(lambda *event: events.append(event))
        for key in (0xA2, 0x5B, 0x5A):
            state.key(key, True)
        self.assertFalse(state.key(0x23, True, scan=0x4F, extended=True))
        for key in (0x23, 0x5A, 0xA2, 0x5B):
            state.key(key, False, scan=0x4F, extended=True)
        self.assertEqual([event[0] for event in events], ['start','cancel'])

    def test_canceled_or_paused_chord_does_not_commit(self):
        for cancel in ('key', 'pause'):
            events = []
            state = ShortcutState(lambda *event: events.append(event))
            for key in (0xA2, 0x5B, 0x5A):
                state.key(key, True)
            if cancel == 'key':
                self.assertFalse(state.key(0x41, True))
                state.key(0x41, False)
            for key in (0xA2, 0x5B, 0x5A):
                state.key(key, False, enabled=cancel != 'pause')
            self.assertEqual([e[0] for e in events], ['start', 'cancel'])

    def test_unrelated_keys_pass_and_numpad_navigation_is_distinguished(self):
        for extended, scan, expected in ((False, 0x4F, 1), (True, 0x4F, 0), (False, 0, 0)):
            events = []
            state = ShortcutState(lambda *event: events.append(event))
            for key in (0xA2, 0x5B):
                self.assertFalse(state.key(key, True))
            self.assertEqual(state.key(0x23, True, scan=scan, extended=extended), bool(expected))
            state.key(0x5A, True)
            for key in (0x23, 0x5A, 0xA2, 0x5B):
                state.key(key, False, scan=scan, extended=extended)
            self.assertEqual(events[-1][1], expected)

    def test_listener_queues_only_committed_mode_and_preserves_start_target(self):
        for level, name in enumerate(MODE_NAMES):
            listener = Listener(Settings(), 'test-key')
            listener.registered = True
            listener.ready.set()
            target = win.Target(1, 2, 3, 4)
            with patch.object(win, 'current_target', return_value=target):
                listener.shortcut_events.put(('start', 0, 1, 10, 1))
                listener.dispatch_shortcut()
                self.assertTrue(listener.jobs.empty())
                listener.epoch += 1
                listener.shortcut_events.put(('commit', level, 2, 11, 99))
                listener.dispatch_shortcut()
                listener.handle_message(0, win.WM_HOTKEY, win.HOTKEY_ID, 0)
                trigger = listener.jobs.get_nowait()
                self.assertEqual((trigger.mode, trigger.epoch, trigger.target, trigger.input_stamp),
                                 (name, 0, target, 99))
                self.assertTrue(listener.jobs.empty())

    def test_hook_suppresses_reserved_events_but_ignores_own_injection(self):
        emit = Mock()
        monitor = im.InputMonitor(emit, lambda: True)
        with patch.object(im, 'next_hook', return_value=31):
            for key in (0xA2, 0x5B, 0x5A, 0x33):
                event = im.KeyboardEvent(key=key)
                result = monitor.keyboard(0, 0x0100, c.addressof(event))
                self.assertEqual(result, 1 if key in (0x5A, 0x33) else 31)
            for key in (0x5B, 0x33, 0xA2, 0x5A):
                event = im.KeyboardEvent(key=key)
                monitor.keyboard(0, 0x0101, c.addressof(event))
            self.assertEqual(emit.call_args.args[:2], ('commit', 3))
            event = im.KeyboardEvent(key=0x5A, flags=0x10, extra=win.INPUT_TAG)
            self.assertEqual(monitor.keyboard(0, 0x0100, c.addressof(event)), 31)


if __name__ == '__main__':
    unittest.main()
