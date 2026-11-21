"""Pure release-based chord arbitration. No timers, I/O, or blocking in hooks.

Ctrl+Win reserves Z, mode digits 0-5 (including numpad), and Undo (U or Backspace).
The first digit wins. A chord commits once after all participating keys are up.
Holding/repeating keys cannot start another correction. Unrelated input cancels
the pending chord.
"""
from time import perf_counter_ns

CTRL = {0x11, 0xA2, 0xA3}
WIN = {0x5B, 0x5C}
Z = 0x5A
U = 0x55
BACKSPACE = 0x08
UNDO_KEYS = {U, BACKSPACE}

# Top-row digits (0x30-0x35), Numpad with NumLock (0x60-0x65),
# and Numpad navigation without NumLock (Insert, End, Down, PageDown, Left, Clear).
DIGITS = {
    0x30: 0, 0x31: 1, 0x32: 2, 0x33: 3, 0x34: 4, 0x35: 5,
    0x60: 0, 0x61: 1, 0x62: 2, 0x63: 3, 0x64: 4, 0x65: 5,
    0x2D: 0, 0x23: 1, 0x28: 2, 0x22: 3, 0x25: 4, 0x0C: 5,
}

NUMPAD_NAV_SCANS = {
    0x2D: 0x52,  # Insert -> 0
    0x23: 0x4F,  # End -> 1
    0x28: 0x50,  # Down -> 2
    0x22: 0x51,  # PageDown -> 3
    0x25: 0x4B,  # Left -> 4
    0x0C: 0x4C,  # Clear -> 5
}

CHORD_KEYS = CTRL | WIN | {Z} | set(DIGITS) | UNDO_KEYS


class ShortcutState:
    def __init__(self, emit):
        self.emit = emit
        self.down = set()
        self.suppressed = set()
        self.active = False
        self.level = None
        self.canceled = False

    def key(self, key, down, timestamp=0, scan=0, extended=False, enabled=True):
        # Dedicated navigation keys must retain their normal behavior. Numpad
        # navigation with NumLock off uses the same VKs but non-extended scans.
        digit = DIGITS.get(key)
        if key in NUMPAD_NAV_SCANS and (extended or scan != NUMPAD_NAV_SCANS[key]):
            digit = None
        repeated = down and key in self.down
        if down:
            self.down.add(key)
        else:
            self.down.discard(key)
        consume = key in self.suppressed
        if enabled and down and not repeated:
            modifiers = (bool(self.down & CTRL) and bool(self.down & WIN)
                         and not self.down & {0x10, 0xA0, 0xA1, 0x12, 0xA4, 0xA5})
            if digit is not None and (modifiers or self.active):
                consume = True
                self.suppressed.add(key)
                if self.level is None:
                    self.level = digit
            if not self.active and modifiers and Z in self.down:
                self.active = True
                self.canceled = False
                consume = True if key == Z else consume
                self.suppressed.add(Z)
                # A bare chord carries NO digit (None): the listener applies
                # Settings' default_mode at commit time. Emitting 0 here used
                # to hard-wire Grammar & Spelling and ignore the setting.
                self.emit('start', self.level, perf_counter_ns(), timestamp)
            elif not self.active and modifiers and (key in UNDO_KEYS or bool(self.down & UNDO_KEYS)):
                self.active = True
                self.canceled = False
                self.level = 'undo'
                consume = True
                self.suppressed.add(key)
                self.emit('start', 'undo', perf_counter_ns(), timestamp)
            elif self.active and key not in CTRL | WIN | {Z} | UNDO_KEYS and digit is None:
                self.canceled = True
            elif not self.active and key not in CTRL | WIN | {Z} | UNDO_KEYS and digit is None:
                self.level = None
        if not enabled and self.active:
            self.canceled = True
        if not down:
            self.suppressed.discard(key)
        # Wait for modifier release as the existing capture path requires.
        if not self.down & CHORD_KEYS:
            if self.active:
                # Bare chord (no digit) commits with level None so the
                # listener substitutes the configured default_mode.
                emit_level = 'undo' if self.level == 'undo' else self.level
                self.emit('cancel' if self.canceled else 'commit', emit_level,
                          perf_counter_ns(), timestamp)
            self.active = False
            self.level = None
            self.canceled = False
        # Suppress presses/repeats only. Windows and downstream hooks must see
        # releases so a previously delivered press cannot remain logically held.
        # A key-up cannot insert the digit into an editor.
        return consume and down
