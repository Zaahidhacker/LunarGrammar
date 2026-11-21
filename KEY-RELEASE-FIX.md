# Shortcut release repair — 13 November 2026

The repeated **Release shortcut** error was reproduced in the runtime log. Windows reported `GetAsyncKeyState(Z) == 0x8000` even when the chord had been released. The shortcut hook suppressed key-up events as well as presses, allowing Windows/downstream hooks to retain a stale held-key state.

Changes:

- `shortcut_state.py` now consumes reserved key-down/repeat events only. Releases always reach Windows and downstream hooks. Key-up events do not type digits.
- `input_monitor.py` tracks observed Z press/release state and publishes a health-checked state provider.
- `win32.py` uses that observed state for Z, avoiding stale/pre-update asynchronous state. Real held Z still blocks editing. Modifier and mouse-button checks remain unchanged; unknown startup state uses the original Windows check, and a failed monitor fails closed.
- Monitor shutdown removes the new state provider. Selection, clipboard, API, overlay and professionalism behavior were preserved.

Verification:

- **92 automated tests passed**, including stale OS-state reproduction, a physically held Z, held Ctrl, unknown startup state, stopped-monitor rejection, forwarding all reserved releases, and the existing 588 chord-order/repeat scenarios.
- Native input hooks passed three start/stop cycles. The native Edit fixture passed three Unicode/multiline corrections with surrounding text and undo intact.
- Final executable archive verification passed, including current `win32.py`, all other application modules, GUI subsystem and original asset bytes.
- The final executable's real overlay check passed with exit 0.
- Two live packaged corrections passed in a disposable native editor: Ctrl+Win+Z and Ctrl+Win+Numpad 2+Z. Both reached capture, made one API request and completed replacement. Afterward, Windows reported Ctrl, both Win keys, Z and numpad 2 as released. No repeated Release shortcut error occurred in these packaged corrections.

Packaged operation IDs: `13b733bbdc7a` (grammar), `2ad0942b4742` (Level 2). Test input was the public sentence `i cant come today`; no real message was sent. The no-network source harness also confirmed that release detection progressed to target validation; early harness attempts with focus on its outer window were rejected as unsupported and are not counted as successful corrections.

Current executable: `dist/LunaGrammar.exe`, **28,911,574 bytes**.

SHA-256: `F07C1F9FEBBF7501BB01F87783681FC1434C19A85B260BC94320D6D829B05F2D`.

The prior executable is retained in `release-key-baseline/`. This report supersedes the executable checksum in `UI-FIX-REPORT.md`. The repaired executable was restarted in normal mode after verification.
