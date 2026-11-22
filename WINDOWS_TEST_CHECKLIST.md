# Windows Test Checklist — Luna Grammar rebuild (2026-11-21, round 2: 2026-11-22)

**Why this exists:** this rebuild was developed and tested on a Linux VM. The automated suite (209 tests pass, 70 Windows-only skipped) uses mocks — it cannot prove anything about real Word, Chrome, or Outlook fields. **Nothing in this rebuild has been live-tested on Windows 11.** Run this checklist on your laptop before trusting the new build, and report back which rows pass or fail (the app, the field, and the exact pill message). You can also run the guided harness: `python tests\windows_smoke.py` — it runs the unit suite, prints the last-failure diagnostics, then walks the fields below and saves your answers to `%LOCALAPPDATA%\LunaGrammar\smoke-results.txt`.

**Setup first**
1. Build from source: `.\build.ps1` (it runs the tests first, then writes `dist\LunaGrammar.exe`), or run from Python: `.\.venv\Scripts\python.exe main.py --check` (expect "Luna Grammar is listening"), then `main.py --diagnostic` in a second window to watch the log.
2. Use scratch text only — never test in a real document, email, or chat you care about. Do not submit test messages.
3. Keep `%LOCALAPPDATA%\LunaGrammar\luna-grammar.log` open in a tail window (`Get-Content … -Tail 30 -Wait`) so you can see the failure code when something goes wrong.

## A. The five fixed gaps (must all pass)

| # | Steps | Expected |
|---|---|---|
| A1 | Settings → General → Default Refinement Mode → **Executive Concise (2)** → Save. Select `i will send the report tomorow` in Notepad. Press bare **Ctrl+Win+Z** (no digit). | The correction is concise/executive, **not** plain grammar mode. (Before: always grammar.) Set the default back to Grammar afterwards. |
| A2 | Select two sloppy sentences in Notepad, e.g. `we met with the client today and they want the design by friday and also need the budget sheet updated and the contract signed`. Press **Ctrl+Win+Z+4**. | A bullet list appears (`- …` lines), grouped and shortened. (Before: "Invalid correction".) |
| A3 | Correct a sentence in Notepad. Then click elsewhere and select **different** text. Press **Ctrl+Win+U**. | Pill says **"Couldn't verify the corrected text"** and the different text is **untouched**. (Before: the original text could be pasted over the wrong text.) Now re-select the corrected text and press Ctrl+Win+U — it reverts correctly. |
| A4 | Settings → AI Engine → set Temperature **0.7** and Custom instructions e.g. `Always use British spelling.` Save. Correct `i will organize the color scheme` in Notepad. | Correction uses British spelling (`organise`, `colour`). Set temperature back to 0.0 and clear the custom prompt afterwards. |
| A5 | Settings → General → enable **Play a sound when a correction finishes**. Correct a sentence. | A short Windows sound plays on completion; an error (e.g. no internet, A9) plays the error sound. Disable it again if you prefer silence. |
| A6 | Correct something (so the cache has an entry). Settings → Cache & Diagnostics → **Clear Cache**. Correct the **same** text again after changing the model or toggling shorthand. | The second correction reflects the new setting (no stale cached rewrite), and the Clear Cache message says the listener cache was cleared too. |

## B. New features

| # | Steps | Expected |
|---|---|---|
| B1 | Settings → Exclusions → Per-App Default Mode → add `notepad.exe` → **Casual Polish (1)** → Save. In Notepad, bare Ctrl+Win+Z. | Casual Polish is used. Press **Ctrl+Win+Z+2** in Notepad — Executive wins over the per-app mode. Remove the entry afterwards. |
| B2 | Settings → General → Safety & Review → enable **Copy correction to clipboard instead of pasting**. Correct text in Notepad. | Nothing changes in Notepad; the pill says **"Copied — press Ctrl+V"**. Press Ctrl+V — the correction lands. Your original clipboard is restored afterwards (paste it somewhere to check). Disable copy-only. |
| B3 | Enable **Review each correction before applying**. Correct a sentence in Notepad. | The pill shows the corrected text with **[Discard] [Apply]**. Click **Apply** — it pastes. Correct another sentence and click **Discard** — nothing changes and no undo is recorded. Correct a third and wait 30 s without clicking — it applies by itself. Disable review mode. |
| B4 | Copy an image (e.g. a screenshot) to the clipboard. With strict preservation **on** (default), correct text in Notepad. | The correction works and the image is still on the clipboard afterwards (paste it into Paint to check). |
| B5 | Select a long passage (two or three paragraphs, ~2,000+ characters, over the 6,000 limit if you can) and correct it. | It is corrected paragraph by paragraph instead of failing with "Selection too long". |
| B6 | Disconnect from the internet (or turn on flight mode). Select `i dont no where teh keys are` in Notepad, Ctrl+Win+Z. | Pill says **"Fixed offline"** and the obvious typos are fixed locally (`I don't know where the keys are`). Reconnect. Try the same in Casual Polish mode (Ctrl+Win+Z+1) offline — it should show the connection error, not an offline fix. |
| B7 | Open Notepad **as administrator** (right-click → Run as administrator). Select text and press Ctrl+Win+Z. | Pill explains the app is running as administrator and suggests restarting Luna as administrator (or the app normally) — **not** a generic "Couldn't refine text". |

## C. Fields and apps (one row per field — the compatibility table)

Use the local fixture `tests/browser_fields.html` for the browser rows, and scratch documents/messages elsewhere. For each: select a misspelled sentence, correct it, check only the selection changed, then undo with Ctrl+Win+U.

| # | App / field | Expected |
|---|---|---|
| C1 | Notepad (Windows 11) — body text | Supported. Correction lands; Ctrl+Z also works. |
| C2 | Word — a scratch document | Supported (UIA/COM). Formatting inside the selection may change (plain-text replace). |
| C3 | Outlook — a scratch compose window (do not send) | Supported. New Outlook (WebView2) behaves like a browser field. |
| C4 | Chrome — fixture `<textarea>` | Supported. |
| C5 | Chrome — fixture `contenteditable` composer | Supported. |
| C6 | Chrome — fixture `<input>` (single line) | Partial — clipboard path; check the selection is replaced, not the whole field. |
| C7 | Edge — fixture textarea and composer | Same as C4/C5. |
| C8 | Firefox — fixture textarea | Partial — clipboard path. |
| C9 | Google Docs — a scratch document | Partial — clipboard only. If it fails, the pill should say why, and copy-only mode should still work. |
| C10 | VS Code — a scratch file | Partial — clipboard path. |
| C11 | WhatsApp Desktop / Teams / Slack / Discord — a scratch message (do not send) | Partial — clipboard path (UIA if the app built its accessibility tree). |
| C12 | Notepad++ — a scratch file | Supported. |
| C13 | Browser fixture **password field** | Refused — the pill says the field is protected; nothing is sent to the API. |
| C14 | A read-only field (e.g. a read-only Word document, or a disabled field) | Read may work; replacement is refused with a clear message. |

## D. UI checks

| # | Steps | Expected |
|---|---|---|
| D1 | Correct a sentence twice in a row (second time is a cache hit). | The pill shows the **Cached** badge with a small lightning bolt — no tofu/missing-glyph box. |
| D2 | Make a correction fail (e.g. invalid API key, or offline in a non-grammar mode) and read the pill. | The error message is specific ("Connection issue", "The correction changed a URL.", …), not just "Couldn't refine text". Long errors are ellipsized and the × is still visible. |
| D3 | Hover the pill's ×. | The cursor turns into a hand; the click target is generous (44×44 px) even though the × glyph is small. |
| D4 | Settings window on a 150% scaled display (or a second monitor with different scaling). | The window is centred, sized for the DPI, and no tab overflows. Press **Ctrl+S** — it saves. |
| D5 | Watch the tray icon while correcting. | Tooltip shows `Refining… · <mode>` during the request and `Refined · +N words` afterwards; `Paused` when paused. |
| D6 | Settings → Cache & Diagnostics after a failure (e.g. B7). | **Last failure** shows the stage, code, app, and reason (e.g. `capture/capture.elevated_target in notepad.exe`). No selected text appears anywhere. |

## E. Regression (things that must still work)

| # | Steps | Expected |
|---|---|---|
| E1 | All six modes (Ctrl+Win+Z+0…5) on `i dont think she coming today becuz she is sick` in Notepad. | Each mode's tone is visibly different; mode 5 translates (test with a non-English sentence, e.g. French). |
| E2 | Press Ctrl+Win+Z with no selection (caret only). | Pill says "Select some text"; document and clipboard unchanged. |
| E3 | Start a correction, then immediately switch to another app. | The correction is cancelled; neither document changes. |
| E4 | Correct text, then Ctrl+Win+U immediately (corrected text still selected). | Reverts cleanly. |
| E5 | `.\dist\LunaGrammar.exe --check-overlay` | All six modes verify (the count should be **6**, not ~30). |
| E6 | `.\.venv\Scripts\python.exe -m unittest discover -s tests` | 209 pass, 70 skipped (Windows-only tests that need a real desktop are expected to skip on some machines — note any that *fail*). |

## F. Round 2 (new in v1.1.0)

| # | Steps | Expected |
|---|---|---|
| F1 | Correct text in VS Code, then immediately click into another app while it is working. | The correction lands in VS Code only (focus is restored to the captured field before pasting); nothing is pasted into the other app. |
| F2 | In WordPad / a RichEdit field, select a passage past 64K into a very long document and correct it. | The selection is read and replaced correctly (EM_EX range, no -1 / empty selection). |
| F3 | Select text in Firefox, Ctrl+Win+Z. | It works via the clipboard path (no long hang from UIA). |
| F4 | Select text in Windows Terminal / cmd / PowerShell, Ctrl+Win+Z. | Pill clearly refuses terminals and explains why; nothing is pasted or executed. |
| F5 | Start typing with an IME (e.g. Sinhala / Japanese input) so a composition is active, then press Ctrl+Win+Z mid-composition. | Pill says to finish the composition first; the composition is not corrupted. |
| F6 | With a slow/flaky connection, correct a sentence (timeout case). | It retries up to twice with back-off and then succeeds or shows the specific timeout error — it does not fail instantly on a single blip. A 429 rate-limit error is attempted once only. |
| F7 | Correct a sentence, then correct another, then look at the recent-corrections history (Settings). | Both corrections are listed (original → corrected, mode, app); history is in-memory only. |
| F8 | Settings → save the API key via DPAPI (Windows). Restart Luna, correct a sentence without OPENAI_API_KEY set. | It works from the stored key. (Off-Windows this row does not apply.) |
| F9 | Settings → Test Connection (model check). | Success message on a good key; a specific error (not a crash) on a bad key. |
| F10 | Install from the Release installer (`LunaGrammar-Setup-1.1.0.exe`): run it, no admin prompt. | Installs to `%LOCALAPPDATA%\LunaGrammar`, Start Menu shortcut appears, app starts, first run asks for the API key once. Uninstall leaves settings in place. |
| F11 | Emoji / Sinhala / Arabic text: correct `i ❤️ colombo, teh city is beautifull` in Notepad. | Emojis and non-Latin text survive unchanged; only the typos are fixed. |
| F12 | Multi-monitor / different DPI: correct text on the second monitor. | The pill appears near the caret on the right monitor, fully visible. |

## Reporting back

For each failed row, note: the row number, the app + field, the exact pill message, and the matching lines from `luna-grammar.log` (the `op=` and `category=` fields). That is what turns a failure into a fixable bug.
