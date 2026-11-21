"""Keep a real mode pill visible briefly for computer-use inspection, no API."""
import ctypes as c
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import overlay
import win32 as win
from config import Settings


def main():
    overlay.set_dpi_context(-4)
    pill=overlay.Overlay()
    peek=win.bind(win.user,'PeekMessageW',win.w.BOOL,c.POINTER(win.w.MSG),win.w.HWND,
                  win.w.UINT,win.w.UINT,win.w.UINT)
    try:
        pill.show_state('working','Perfecting…',win.foreground(),Settings())
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            msg=win.w.MSG()
            while peek(c.byref(msg),None,0,0,1):
                win.dispatch_message(c.byref(msg))
            time.sleep(.005)
    finally:
        pill.close()


if __name__=='__main__':
    main()
