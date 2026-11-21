"""Disposable native editor for end-to-end release checks; contains public sample only."""
import ctypes as c
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import win32 as win


def main():
    editor=None
    focus=win.bind(win.user,'SetFocus',win.w.HWND,win.w.HWND)
    @win.WNDPROC
    def proc(window,message,wparam,lparam):
        if message==0x0007 and editor:
            focus(editor)
            return 0
        if message==win.WM_CLOSE:
            win.destroy_window(window)
            win.post_quit(0)
            return 0
        return win.default_proc(window,message,wparam,lparam)
    instance=win.get_module(None)
    name='LunaGrammar.ScratchEditor'
    definition=win.WindowClass(proc=proc,instance=instance,name=name)
    if not win.register_class(c.byref(definition)):
        raise c.WinError(c.get_last_error())
    root=None
    try:
        root=win.create_window(0,name,'Luna Grammar scratch test',0x10CF0000,
                               100,100,800,280,None,None,instance,None)
        editor=win.create_window(0,'Edit','Before [hey can u send me the files when ur free] After',
                                 0x508010C4,20,20,740,180,root,None,instance,None)
        if not root or not editor:
            raise c.WinError(c.get_last_error())
        win.send_window_message(editor,0x00B1,8,46)
        focus=win.bind(win.user,'SetFocus',win.w.HWND,win.w.HWND)
        focus(editor)
        msg=win.w.MSG()
        translate=win.bind(win.user,'TranslateMessage',win.w.BOOL,c.POINTER(win.w.MSG))
        while win.get_message(c.byref(msg),None,0,0)>0:
            translate(c.byref(msg))
            win.dispatch_message(c.byref(msg))
    finally:
        if root:
            win.destroy_window(root)
        win.unregister_class(name,instance)


if __name__=='__main__':
    main()
