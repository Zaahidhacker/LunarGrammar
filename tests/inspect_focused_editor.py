"""Inspect the focused editor's Windows provider metadata without reading text."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import win32 as win
from config import AppError
from text_selection import Automation


def inspect(automation, target):
    print(f"Windows classes: top={win.class_name(target.window)!r}, "
          f"focus={win.class_name(target.focus)!r}, native_edit={win.native_edit(target.focus)}, "
          f"child_of_top={target.focus != target.window and win.get_ancestor(target.focus, 2) == target.window}")
    if target.focus_pid:
        print(f"Embedded focus process: {win.executable(target.focus_pid)}")
    try:
        element = automation.client.GetFocusedElement()
        for depth in range(4):
            if not element:
                break
            types = automation.types
            supported = []
            for name, identifier in (
                ("Text", "UIA_TextPatternId"), ("Text2", "UIA_TextPattern2Id"),
                ("TextEdit", "UIA_TextEditPatternId"), ("Value", "UIA_ValuePatternId"),
                ("LegacyIAccessible", "UIA_LegacyIAccessiblePatternId"),
            ):
                pattern_id = getattr(types, identifier, None)
                pattern = element.GetCurrentPattern(pattern_id) if pattern_id is not None else None
                if pattern:
                    supported.append(name)
                    if name == "LegacyIAccessible":
                        legacy = pattern.QueryInterface(types.IUIAutomationLegacyIAccessiblePattern)
                        supported[-1] += f"(role=0x{legacy.CurrentRole:x},state=0x{legacy.CurrentState:x})"
            print(f"UIA depth={depth} control={element.CurrentControlType} "
                  f"framework={element.CurrentFrameworkId!r} "
                  f"pid_matches={target.contains_process(element.CurrentProcessId)} "
                  f"patterns={','.join(supported) or 'none'}")
            element = automation.client.ControlViewWalker.GetParentElement(element)
    except automation.com_error as error:
        print(f"UI Automation failed (HRESULT 0x{error.hresult & 0xffffffff:08x}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", nargs="+", help="Foreground executable names, for example whatsapp.exe")
    parser.add_argument("--timeout", type=int, default=75)
    options = parser.parse_args()

    sys.coinit_flags = 0  # MTA, as in the production UI Automation worker.
    automation = Automation()
    deadline = time.monotonic() + options.timeout
    apps = {name.casefold() for name in options.app}
    print(f"Focus a scratch editor in {', '.join(sorted(apps))}. "
          f"Waiting for up to {options.timeout} seconds.", flush=True)
    while time.monotonic() < deadline:
        target = win.current_target()
        if target:
            try:
                name = win.executable(target.pid)
                if name in apps:
                    time.sleep(1)
                    if win.current_target() == target:
                        print(f"Application: {name}")
                        inspect(automation, target)
                        return 0
            except AppError:
                pass
        time.sleep(0.15)
    print("No matching focused editor was observed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
