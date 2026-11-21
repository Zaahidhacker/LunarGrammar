"""Exercise the real layered window and its real Windows timer/message loop."""
import ctypes as c
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import overlay
import win32 as win
from config import Settings


def main():
    overlay.set_dpi_context(-4)
    pill = overlay.Overlay()
    observed, failures = [], []
    area=overlay.work_area(win.foreground())
    cover=win.create_window(0x08000088,'Static','Luna overlay occlusion fixture',0x90000000,
                            area[0],area[3]-130,area[2]-area[0],130,
                            None,None,win.get_module(None),None)
    get_top=win.bind(win.user,'GetTopWindow',win.w.HWND,win.w.HWND)
    get_window=win.bind(win.user,'GetWindow',win.w.HWND,win.w.HWND,win.w.UINT)
    original_tick = pill.tick
    def tick(now):
        try:
            original_tick(now)
            frame = pill.motion.sample(now, pill.reduce)
            observed.append(dict(state=pill.motion.state, visible=pill.visible,
                                 opacity=frame.opacity if frame else 0))
        except Exception as error:
            failures.append(dict(type=type(error).__name__, message=str(error)))
            raise
    peek = win.bind(win.user, 'PeekMessageW', win.w.BOOL, c.POINTER(win.w.MSG),
                    win.w.HWND, win.w.UINT, win.w.UINT, win.w.UINT)
    try:
        with patch.object(pill, 'tick', tick):
            pill.show_state('working', 'Perfecting…', win.foreground(), Settings())
            deadline = time.monotonic() + .5
            while time.monotonic() < deadline:
                message = win.w.MSG()
                while peek(c.byref(message), None, 0, 0, 1):
                    win.dispatch_message(c.byref(message))
                time.sleep(.005)
            print(json.dumps(dict(frames=observed, failures=failures), indent=2))
            assert not failures, failures
            assert any(row['visible'] and row['opacity'] >= .95 for row in observed), 'No opaque timer-driven frame appeared'
            order=[]
            candidate=get_top(None)
            while candidate:
                order.append(candidate)
                candidate=get_window(candidate,2)
            assert order.index(pill.window)<order.index(cover), 'Overlay is behind another topmost window'
    finally:
        pill.close()
        win.destroy_window(cover)


if __name__ == '__main__':
    main()
