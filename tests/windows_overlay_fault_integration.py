"""Native UI checks with injected animation/Windows-timer failures; no API."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import overlay
from correction_modes import list_modes


def main():
    mode_count = len(list_modes())
    render=overlay.render
    failures=[]
    def intermittent(frame,*args):
        if not failures and frame.state=='working' and 0<frame.opacity<1:
            failures.append('injected')
            raise OSError('Intentional animation failure from regression fixture')
        return render(frame,*args)
    with patch.object(overlay,'render',intermittent):
        assert overlay.check_overlay() == mode_count
    assert failures, 'The animation-failure path was not exercised'
    print(f'PASS: real window recovered from an animation-frame failure in all {mode_count} modes.')
    with patch.object(overlay,'set_timer',return_value=0):
        assert overlay.check_overlay() == mode_count
    print('PASS: real window survived Windows timer failure; static feedback and message-thread fallback dismissal passed.')


if __name__=='__main__':
    main()
