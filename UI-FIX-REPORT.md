# Luna Grammar — UI visibility repair

The later [shortcut-release repair](KEY-RELEASE-FIX.md) supersedes this report's executable checksum and test count; its release retains these UI fixes.

13 November 2026. Current executable: `dist/LunaGrammar.exe`.

## Fixed

The old overlay could render correctly while remaining **behind another topmost window**. A native Windows occlusion test failed on the old code and passes on the repaired code. The pill now explicitly raises itself when displaying a status, using `HWND_TOPMOST` and `SWP_NOACTIVATE`; it does not take focus away from the editor.

Related feedback fixes:

- Display the chosen working label as soon as the shortcut is committed, before capture or network work starts.
- Ignore duplicate worker progress events so they cannot restart the entry fade.
- Log animation/render failures instead of silently hiding the UI. Recover from an animation or Windows-timer failure with static feedback.
- Keep automatic success/error dismissal working when a Windows timer cannot be allocated. Fallback timers post back to the UI thread and use generation IDs, preventing stale expiry messages from hiding a newer operation.
- Keep automatic expiry distinct from the user's close button, so an automatically dismissed result cannot suppress later feedback.
- Add `--check-overlay`, which verifies the actual Windows overlay without reading documents, accessing the clipboard, or making API requests. It works inside the packaged executable.

Changed application files: `overlay.py`, `windows_hotkey.py`, `main.py`. Grammar/model configuration, selection verification, clipboard handling, original visual assets, waveform renderer and font are preserved.

## Executed verification

| Check | Actual result |
| --- | --- |
| Automated suite | **89 tests passed**, including the existing correction, clipboard, hotkey, mode and output-validation regressions, plus new overlay recovery and stale-dismissal tests. |
| Native occlusion regression | Failed before repair; passed after repair. A competing topmost test window no longer covers the pill. |
| Real listener/worker feedback | All four working labels reached visible opaque frames; success feedback appeared. Mocked corrections avoided document edits and API calls. |
| Actual Windows animation-failure test | Passed: injected frame failure recovered to visible static feedback; all four modes and result dismissal worked. |
| Actual Windows timer-failure test | Passed with `SetTimer` forced to fail: working feedback stayed visible, all four modes worked, and success/error dismissal completed through the fallback message path. |
| Final EXE overlay self-check | Exit **0**: four visible mode labels, placement above a competing topmost window, foreground-focus preservation, success/error visibility and automatic dismissal. |
| Native editing fixture | Three Unicode/multiline corrections passed, preserving surrounding text and undo. |
| Native input hooks | Three registration/shutdown cycles passed. |
| Rich clipboard fixture | Passed: three copy/paste/restore cycles; HTML, RTF, image, file-drop and registered formats; independent-process capture; a newer clipboard write survived cleanup. The original interactive clipboard was backed up and restored. |
| Edge physical shortcuts | Source listener with a fixed mock engine: standard input, multiline textarea and contenteditable passed. Unselected `Before`/`After` text and multiline layout survived. Grammar, Level 1, Level 2 and Level 3 each produced one successful operation. Browser undo was checked. No model requests were used for these browser tests. |
| Final EXE lifecycle | Two clean start/stop cycles passed, tray registration on each, duplicate rejection, hotkey release, TLS initialization and model-access check. |
| Temporary startup shortcut | EXE target, arguments, working directory and removal passed outside the real Windows Startup folder. |
| Archive/source verification | x64 GUI executable; all application modules match current source; original assets are byte-identical; font license bundled; preferences and credentials remain external. |

## Live packaged corrections

The **final executable itself**, running as one listener, corrected the same public sentence in a disposable native editor. A separate observer sampled the real status window every 50 ms. Each operation logged exactly one API request and finished successfully.

Input: `hey can u send me the files when ur free`

| Mode / physical shortcut | Actual corrected text | Visible samples | Above editing window | Dismissed automatically |
| --- | --- | ---: | --- | --- |
| Grammar / Ctrl+Win+Z | Hey, can you send me the files when you're free? | 168 | Yes | Yes |
| Level 1 / Ctrl+Win+Z+1 | Hi, could you please send me the files when you're free? | 126 | Yes | Yes |
| Level 2 / Ctrl+Win+Numpad 2+Z | Hello, could you please send me the files at your convenience? | 49 | Yes | Yes |
| Level 3 / Ctrl+Win+Z+3 | Hello, I would appreciate it if you could forward the files at your earliest convenience. | 83 | Yes | Yes |

The Level 2 case additionally verified **digit-before-Z order with a numpad digit**, with no digit inserted into the editor. Ctrl+Z restoration was visibly checked in the disposable editor for the professional corrections. The editor's own standard keyboard-message handling was corrected before accepting those undo results.

Evidence files: `tests/exe-overlay-{grammar,level1,level2,level3}.json`, `tests/ui-fix-exe-operations.log`, `tests/ui-fix-browser.log`, `ui-fix-release-metrics.json`.

The live tests used only public test text. No real message was sent. Native mock/fault tests made no API requests. Five small live requests were used during this repair: one pre-fix reproduction and four final packaged mode checks.

## Delivered executable

`dist/LunaGrammar.exe` — **28,911,904 bytes**.

SHA-256: `E0DED8725A4E524CB1550C333FCB5FF2EAC1E466F844B8E1003CF47A3ECCE2ED`.

The previous Round 5 executable and changed source files are preserved in `round5-ui-baseline/`. The older stable pre-Round-5 baseline remains in `round5-baseline/`. This report supersedes the executable checksum and incomplete UI-testing notes in the historical `ROUND5-REPORT.md`.

After testing, temporary editor/mock/server helpers were stopped and the repaired executable was restarted in normal mode. Existing preferences and API-key configuration were retained.

Existing conservative restrictions on protected or unsupported fields, elevated applications, changed selections and changed focus remain. Those guards protect text and were not removed to hide errors. WhatsApp-specific UI was not exercised in this repair; native editing, Edge fields and the actual executable were exercised as described above.
