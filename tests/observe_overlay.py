"""Observe only Luna's status-window metadata during a real scratch correction."""
import argparse
import ctypes as c
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import win32 as win


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    is_visible=win.bind(win.user,'IsWindowVisible',win.w.BOOL,win.w.HWND)
    get_rect=win.bind(win.user,'GetWindowRect',win.w.BOOL,win.w.HWND,c.POINTER(win.w.RECT))
    get_top=win.bind(win.user,'GetTopWindow',win.w.HWND,win.w.HWND)
    get_window=win.bind(win.user,'GetWindow',win.w.HWND,win.w.HWND,win.w.UINT)
    seen=[]
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        window=win.find_window(None,None,'LunaGrammar.StatusPill.v2',None)
        if window and is_visible(window):
            rect=win.w.RECT()
            get_rect(window,c.byref(rect))
            top=get_top(None)
            stack=[]
            while top:
                stack.append(top)
                top=get_window(top,2)
            foreground=win.foreground()
            seen.append(dict(rect=(rect.left,rect.top,rect.right,rect.bottom),
                             above_foreground=window in stack and foreground in stack
                             and stack.index(window)<stack.index(foreground)))
        elif seen:
            break
        time.sleep(.05)
    result=dict(visible_samples=len(seen),above_foreground=bool(seen) and all(x['above_foreground'] for x in seen),
                first_rect=seen[0]['rect'] if seen else None,automatically_hidden=bool(seen) and time.monotonic()<deadline)
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    assert result['visible_samples']>=3 and result['above_foreground'] and result['automatically_hidden'],result


if __name__=='__main__':
    main()
