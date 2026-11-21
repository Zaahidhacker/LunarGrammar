"""Real listener/overlay message flow with delayed mock corrections, no text I/O."""
import ctypes as c
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import overlay
import win32 as win
import windows_hotkey as hotkey
from config import Settings
from correction_modes import MODE_NAMES
from text_selection import Trigger


def main():
    frames, failures = [], []
    class ObservedOverlay(overlay.Overlay):
        def tick(self, now):
            try:
                super().tick(now)
                frame=self.motion.sample(now,self.reduce)
                if frame and frame.opacity >= .95:
                    frames.append((frame.state,frame.label,self.visible))
            except Exception as error:
                failures.append(type(error).__name__+': '+str(error))
                raise
    class FixtureListener(hotkey.Listener):
        index=0
        def queue_next(self):
            if self.index >= len(MODE_NAMES):
                self.request_stop()
                return
            self.active_trigger=Trigger(win.current_target(),self.epoch,mode=MODE_NAMES[self.index])
            self.index+=1
            self.busy.set()
            self.jobs.put(self.active_trigger)
        def handle_message(self,window,message,wparam,lparam):
            if message==overlay.WM_TIMER and wparam==99:
                overlay.kill_timer(window,99)
                self.queue_next()
                return 0
            result=super().handle_message(window,message,wparam,lparam)
            if message==hotkey.WM_READY and self.ready.is_set():
                self.queue_next()
            return result
        def update_overlay(self):
            super().update_overlay()
            if self.overlay.motion.state in ('success','unchanged','error'):
                overlay.set_timer(self.window,99,1600,None)
    def correction(*_args,progress,**_kwargs):
        progress()
        time.sleep(.6)
        return 'success'
    with patch('overlay.Overlay',ObservedOverlay), patch.object(hotkey,'GrammarEngine'), \
         patch.object(hotkey,'Automation'), patch.object(hotkey,'correct_selection',correction):
        result=FixtureListener(Settings(),'fixture-key-only').run()
    print(json.dumps(dict(result=result,opaque_states=sorted(set(frames)),failures=failures),indent=2))
    assert not failures,failures
    for label in ('Refining…','Polishing…','Professional…','Perfecting…'):
        assert ('working',label,True) in frames,label
    assert ('success','Refined',True) in frames


if __name__=='__main__':
    main()
