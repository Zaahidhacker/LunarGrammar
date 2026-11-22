"""Windows smoke harness — run on Zaahid's laptop after installing LunaGrammar.

    python tests\\windows_smoke.py

Runs the unit suite, prints the last-failure diagnostics (if any), and
then walks the real-world checklist prompts: for each app/field, select
some text, press Ctrl+Win+Z, and report what the pill showed. Answers are
saved to %LOCALAPPDATA%\\LunaGrammar\\smoke-results.txt — send that file
back with any failure report (app, field, exact pill message, log lines).
This script needs Windows + the repo checkout; on Linux it only reports
that it cannot run.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = [
    ("Notepad (Win11)", "Select a sentence in Notepad, Ctrl+Win+Z"),
    ("Word — body text", "Select a paragraph in Word, Ctrl+Win+Z"),
    ("Outlook — compose", "Select text in a new mail, Ctrl+Win+Z"),
    ("Chrome — textarea", "Select text in a web textarea, Ctrl+Win+Z"),
    ("Chrome — Google Docs", "Select text in Docs (clipboard-only expected), Ctrl+Win+Z"),
    ("Firefox — textarea", "Select text in Firefox, Ctrl+Win+Z (clipboard-first)"),
    ("VS Code", "Select text in VS Code, Ctrl+Win+Z"),
    ("Notepad++", "Select text in Notepad++, Ctrl+Win+Z"),
    ("WhatsApp Desktop", "Select text in a WhatsApp message box, Ctrl+Win+Z"),
    ("Terminal (refusal expected)", "Select text in Windows Terminal — expect a clear refusal, no paste"),
    ("Password field (refusal expected)", "Try in a password field — expect a clear refusal"),
    ("Elevated Notepad (refusal expected)", "Run Notepad as admin, try — expect the elevated-target message"),
]


def main() -> int:
    if sys.platform != "win32":
        print("windows_smoke.py needs Windows. On this machine it cannot run.")
        return 2
    print("== LunaGrammar Windows smoke ==")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(result.stdout[-2000:])
    print(result.stderr[-2000:])
    diag = Path(os.environ["LOCALAPPDATA"]) / "LunaGrammar" / "last-failure.json"
    if diag.exists():
        print("\nLast failure diagnostics:")
        print(diag.read_text(encoding="utf-8", errors="replace")[:2000])
    else:
        print("\nNo last-failure diagnostics file — no failure recorded yet.")
    print("\nNow walk the checklist. For each field, do the step, then type")
    print("what the pill showed (or 'ok' / 'fail: <pill message>').")
    answers = []
    try:
        for name, step in FIELDS:
            print(f"\n[{name}] {step}")
            answer = input("Result: ").strip()
            answers.append({"field": name, "step": step, "result": answer})
    except KeyboardInterrupt:
        print("\nStopped early — saving what was answered so far.")
    out = Path(os.environ["LOCALAPPDATA"]) / "LunaGrammar" / "smoke-results.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(answers, indent=2), encoding="utf-8")
    print(f"\nSaved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
