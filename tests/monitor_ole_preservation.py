"""Compare cached clipboard data before and after a live Luna correction."""

import argparse
import os
from pathlib import Path
import time

from windows_cached_ole_integration import fingerprint, native_memory, require_hr, cm, win, w


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=120)
    options = parser.parse_args()
    init = win.bind(win.ole, "OleInitialize", w.LONG, w.LPVOID)
    uninit = win.bind(win.ole, "OleUninitialize", None)
    require_hr(init(None))
    log = Path(os.environ["LOCALAPPDATA"]) / "LunaGrammar" / "luna-grammar.log"
    clipboard = cm.Clipboard(None)
    try:
        with clipboard.locked():
            starting_sequence = cm.sequence()
        original_ole = fingerprint()
        with clipboard.locked():
            original_memory = native_memory()
            if cm.sequence() != starting_sequence:
                raise RuntimeError("The clipboard changed while establishing the baseline.")
        offset = log.stat().st_size
        print("Baseline ready. Run one scratch correction without copying a new item.", flush=True)
        deadline = time.monotonic() + options.timeout
        while time.monotonic() < deadline:
            if log.stat().st_size < offset:
                offset = 0
            with log.open("r", encoding="utf-8") as stream:
                stream.seek(offset)
                text = stream.read()
                offset = stream.tell()
            if "event=operation.finished result=success" in text:
                after_ole = fingerprint()
                with clipboard.locked():
                    after_memory = native_memory()
                if after_ole != original_ole or after_memory != original_memory:
                    raise RuntimeError("The clipboard differs from the baseline after the correction.")
                print("PASS: the live correction preserved all cached native blocks and OLE medium data.")
                return 0
            time.sleep(0.2)
        print("No completed correction was observed before the monitor timed out.")
        return 1
    finally:
        uninit()


if __name__ == "__main__":
    raise SystemExit(main())
