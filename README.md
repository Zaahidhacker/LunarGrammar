# Luna Grammar

A lightweight Windows 11 tray app: select text in almost any application, press a shortcut, and Luna corrects and refines the selection in place — without opening a window or touching your clipboard more than necessary.

> **What changed in this rebuild (2026-11-21):** the default mode, Bulletize mode, Undo, custom prompt / temperature / sound, and cache clearing were all broken in the previous release — see [CHANGELOG.md](CHANGELOG.md). The layered capture/replace engine and per-field compatibility are documented in [COMPATIBILITY.md](COMPATIBILITY.md), and the steps to verify the new build on a real Windows laptop are in [WINDOWS_TEST_CHECKLIST.md](WINDOWS_TEST_CHECKLIST.md).

## Shortcuts

Select text in an editable Windows 11 field first. Hold **Ctrl** and **Win**, then press **Z** and optionally a digit **before releasing the chord**. Keep the selection and focus in place until the correction appears. A small lime capsule shows that Luna is working; a checkmark appears briefly after the edit. You can turn off the overlay in Settings.

| Shortcut | Mode |
| --- | --- |
| Ctrl + Win + Z | Your default mode (set in Settings — **General → Default Refinement Mode**; Grammar & Spelling by default) |
| Ctrl + Win + Z + 0 | Grammar & Spelling — grammar, spelling, punctuation; expands clear shorthand; preserves casual tone |
| Ctrl + Win + Z + 1 | Casual Polish — friendly, lightly polished professionalism |
| Ctrl + Win + Z + 2 | Executive Concise — concise business professionalism |
| Ctrl + Win + Z + 3 | Academic & Formal — refined formal professionalism, without unnecessary length |
| Ctrl + Win + Z + 4 | Bulletize & Summarize — rewrites the selection as bullet points, grouping and shortening it |
| Ctrl + Win + Z + 5 | Translate to English — translates the selection into natural English |

An explicit digit always wins over the default mode. You can also set a **per-app default mode** (Settings → Exclusions → Per-App Default Mode): a bare Ctrl+Win+Z in that app uses its mode. **Ctrl + Win + U** (or Ctrl + Win + Backspace) undoes the last correction — but only after verifying the corrected text is still selected, so it can never restore the original over unrelated text.

Luna commits once when all chord keys are released. There is no fixed arbitration timer. After Ctrl+Win are down, Z and the digit may arrive in either order, and release order does not matter. Top-row and numpad 0–5 are supported, including non-extended numpad navigation with NumLock off. The first digit wins if more than one is pressed. Repeated/held keys never enqueue duplicate requests. While enabled, Ctrl+Win+0…5 are reserved as potential chord prefixes; release without Z does nothing. Press the modifiers first: a digit or Z delivered to an editor before Ctrl+Win cannot be retroactively suppressed. Other editing keys or mouse actions during the chord cancel it. Release the full chord before starting another.

Luna Grammar sends the selected text to OpenAI's Responses API with `store=False`. Each request is independent and uses GPT-6 Luna by default. The app keeps request text, corrections, and credentials out of its local logs. OpenAI's API data handling is governed by your project's settings and [OpenAI's data controls](https://developers.openai.com/api/docs/guides/your-data).

## Compatibility at a glance

No system-wide tool works in every field. Luna tries, in order: **UI Automation → native Win32 messages → clipboard Ctrl+C/Ctrl+V → (copy-only fallback)**. The honest per-field picture:

| Field / app | Capture | Replace | Reliability |
| --- | --- | --- | --- |
| Classic Win32 Edit / RichEdit (dialogs, WordPad, classic Notepad) | UIA / `EM_GETSEL` | `EM_REPLACESEL` | Supported |
| Windows 11 Notepad (WinUI) | UIA TextPattern | Clipboard Ctrl+V | Supported |
| WPF / WinUI / UWP text fields | UIA TextPattern | Clipboard Ctrl+V | Supported |
| Word / Outlook (desktop) | UIA / COM | COM / clipboard | Supported |
| PowerPoint / Excel | UIA | Clipboard / COM | Partial |
| Chrome / Edge — `<textarea>`, `contenteditable` | UIA / Ctrl+C | Clipboard Ctrl+V | Supported |
| Chrome / Edge — `<input>` | Ctrl+C | Ctrl+V | Partial |
| Firefox — any field | Ctrl+C | Ctrl+V | Partial |
| Google Docs / Sheets (canvas) | Ctrl+C only | Ctrl+V only | Partial |
| VS Code / Monaco | Ctrl+C | Ctrl+V | Partial |
| Teams / Slack / Discord / WhatsApp Desktop (Electron) | UIA if the tree is built, else Ctrl+C | Clipboard Ctrl+V | Partial |
| Notepad++ (Scintilla) | Ctrl+C | Clipboard Ctrl+V | Supported |
| Terminals / consoles | Not attempted (Ctrl+C is Break) | — | Not supported |
| Password / PIN fields | Refused | Refused | Not supported (by design) |
| Elevated apps (run as administrator) while Luna runs normally | Blocked by Windows (UIPI) | Blocked | Not supported — restart Luna as administrator, or restart the app normally |
| UAC / login / secure desktop, DRM / Protected View | — | — | Not supported |

If a correction cannot be pasted back safely, Luna copies the corrected text to the clipboard and shows **"Copied — press Ctrl+V"** instead of a bare error. Turn on **Copy correction to clipboard instead of pasting** (Settings → General → Safety & Review) to always use that safe mode. Turn on **Review each correction before applying** to hold every correction in the pill with **Apply / Discard** buttons (30 s, then it applies automatically — a correction is never stranded).

See [COMPATIBILITY.md](COMPATIBILITY.md) for the full layered engine, the failure codes, and what is impossible by design.

## Run the Windows executable

Keep [LunaGrammar.exe](dist/LunaGrammar.exe) in a permanent folder and double-click it. It runs without a console. Use the notification-area icon to open Settings, pause the shortcut, or quit. Quit the Python listener before launching the executable.

The executable reads `OPENAI_API_KEY` from its environment. For Explorer launches, set a user environment variable as described under **Start at Windows sign-in**, then sign out and back in. The key is never bundled. You can launch from a PowerShell session that already has the key while setting up.

Packaged preferences are stored in `%LOCALAPPDATA%\LunaGrammar\settings.json`. To carry over preferences from the Python version, copy the project’s `settings.json` there before your first packaged launch. Keep your existing profile file if you already use the packaged version.

To build from source on Windows x64 with Python 3.12 and Tcl/Tk, run `.\build.ps1`. It runs the test suite first (the build fails if tests fail), then installs the pinned build requirements and writes `dist\LunaGrammar.exe`. Run `.\tests\release_smoke.ps1` in an interactive Windows session after quitting Luna to check launch, duplicate rejection, tray registration, and restart.

## Run from Python

Open PowerShell in this folder. Use a 64-bit Python 3.10 or newer with Tcl/Tk for the settings window. If the existing `.venv` already works, skip the first command. Rerun the install command after upgrading so Pillow is available.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENAI_API_KEY = [pscredential]::new('OpenAI', (Read-Host 'OpenAI API key' -AsSecureString)).GetNetworkCredential().Password
.\.venv\Scripts\python.exe main.py --check
.\.venv\Scripts\python.exe main.py --diagnostic
```

Enter the key at the hidden prompt. The commands above set it for this PowerShell session and its child processes. Wait for **Luna Grammar is listening**, then select `i dont think she coming today becuz she is sick` in Notepad and press the shortcut. In a supported editor, **Ctrl + Z** should undo the correction.

`--check` probes the exact hotkey and editing-input monitor, initializes UI Automation and TLS, and checks the SDK and key presence without contacting OpenAI. Run it before starting the listener because an active listener already owns the shortcut.

To verify model access for the current PowerShell session, run `.\.venv\Scripts\python.exe main.py --check-api`. It requests model metadata and sends no selected text.

If PowerShell cannot find `.\.venv\Scripts\python.exe`, first check that you are in this project folder. If `python -m venv .venv` opened Microsoft Store or failed, use the full path to a working Python executable. On a machine with the Codex desktop Python runtime, you can create the environment with:

```powershell
$lunaPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $lunaPython -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run quietly and stop

Stop the diagnostic listener with **Ctrl + C**, or run the second command below from PowerShell. Start the background version from the same PowerShell session that has the key.

```powershell
$lunaScript = (Resolve-Path .\main.py).Path
Start-Process -FilePath .\.venv\Scripts\pythonw.exe -ArgumentList ('"{0}"' -f $lunaScript) -WindowStyle Hidden
```

```powershell
.\.venv\Scripts\python.exe main.py --stop
```

A stop request cancels pending replacements. A network request already in progress can take a moment to finish. For console use, `.\start.bat --diagnostic` also works. Use **Quit Luna Grammar** in the Windows notification area to stop it without opening PowerShell.

Logs rotate under `%LOCALAPPDATA%\LunaGrammar`. To inspect recent status messages, run:

```powershell
Get-Content "$env:LOCALAPPDATA\LunaGrammar\luna-grammar.log" -Tail 30
```

## Start at Windows sign-in

This is optional. After setting the key in PowerShell as shown above, save it as a user environment variable. Windows stores that variable in your user profile, where processes running as you can access it. Then turn on **Run at Windows sign-in** in Settings and save.

```powershell
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $env:OPENAI_API_KEY, 'User')
.\.venv\Scripts\python.exe main.py --settings
```

Sign out and back in to test. To disable automatic startup, turn the same setting off. To remove the persisted key, use `[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $null, 'User')`.

## Settings and troubleshooting

Open **Settings** from the notification-area icon or run `.\.venv\Scripts\python.exe main.py --settings`. The tray menu also lets you pause or resume the hotkey. Changes made in Settings apply to the running listener. Use **Check** beside the API status to verify your selected model. **Expand chat shorthand** is on by default and asks the model to expand clear conversational abbreviations such as `idk`, `hby`, and `tmrw`. It keeps natural expressions such as “gonna” where appropriate.

New settings in this rebuild (Settings → General → Safety & Review, and Exclusions):

- **Copy correction to clipboard instead of pasting** — safe mode for fragile fields; Luna stages the correction and you press Ctrl+V yourself.
- **Review each correction before applying (Apply / Discard)** — the pill holds the corrected text for up to 30 s; Apply pastes it, Discard drops it, and a timeout applies it (never stranded).
- **Refuse a correction rather than lose clipboard formats** (on by default) — if your clipboard holds formats Luna cannot back up (images with OLE data, etc.), Luna refuses the correction instead of silently destroying them. Turn it off only if you accept the old best-effort behaviour.
- **Per-App Default Mode** — a bare Ctrl+Win+Z uses a chosen mode in a chosen app; an explicit digit always wins.
- **Play a sound when a correction finishes** — the old toggle promised sound but nothing ever played; it now really does play the Windows completion sound (success / error).
- **Cache & Diagnostics → last failure** — shows the most recent failure's stage, app, field type, and reason (metadata only — never your text).

The overlay uses Poppins and the lime accent `#BFF549`. It follows the editing window’s monitor and Windows animation preferences. Choose **Reduced** for a static waveform, **Light** for a light capsule, or turn off **Show overlay feedback**. Clicking the capsule’s × dismisses it (the close hit-zone is now a full 44×44 px touch target). While a correction is pending, that click also cancels the edit through the input guard. The tray tooltip now shows live state (`Refining…`, `Refined · +3 words`, `Paused`, …).

Long selections are corrected paragraph by paragraph instead of failing outright; a single paragraph over the limit still reports a clear error. If the API is unreachable, obvious typos in Grammar mode are fixed locally on your machine and labelled **"Fixed offline"** — no other mode does this, and offline fixes are never cached. If the primary model is unavailable, Luna tries the configured fallback models before failing.

For advanced configuration, edit the version’s `settings.json` and restart the app. `model` defaults to `gpt-6-luna` and can be overridden with `LUNA_GRAMMAR_MODEL`. `timeout_seconds` sets the SDK timeout. `max_selection_chars` bounds the text submitted per request. `excluded_apps` accepts case-insensitive executable names. To exclude a sensitive browser-based app, exclude its entire browser executable, such as `chrome.exe`.

- **Shortcut conflict.** If registration fails, check for a second instance or another app using Ctrl + Win + Z. Windows or local policy can reserve the chord. Luna Grammar reports the Windows error and exits.
- **Nothing changed.** Inspect the log in diagnostic mode. Keep the original field and selection active until the request finishes. Typing, clicking, scrolling, switching apps, changing focus, or altering the selection can cancel the edit. Ordinary pointer movement is allowed. Already-correct and empty selections are left alone.
- **Nothing copied.** Luna first looks for an editable UI Automation range. In recognized browsers and accessibility-identified edit controls, it can fall back to ordinary Ctrl+C even without a text or value pattern. The copy must produce fresh text from the target application. Luna re-copies and compares the selection before pasting. If a writable field value is available, the selection must also occur exactly once in that value.
- **Unsupported or protected field.** Detected passwords, read-only fields, disjoint selections, and classic edits that may truncate are skipped. Luna avoids sending Ctrl+C to unknown controls without evidence that they are editors. Canvas-based Google Docs, protected Word controls, custom editors, and elevated applications can limit capture or replacement. Run Luna Grammar as your normal user — or as administrator if you need to correct text in elevated apps.
- **Clipboard issue.** Luna backs up named, registered Win32 formats, including HTML, RTF and application-specific data, along with common images and file drops. It also preserves the tested ownerless cached OLE image representation, including its stream metadata. Active OLE source references and owner-dependent formats use the clipboard-free native route where available and can cause a safe skip in clipboard-dependent editors. A newer clipboard write takes precedence when it can be distinguished from Luna’s copy. With strict clipboard preservation on (the default), an un-backup-able clipboard causes a clear refusal instead of silent data loss.
- **Formatting and timing.** Replacements use plain text, and formatting inside the selection can change in rich editors. Luna checks focus and input before offering text through delayed clipboard rendering. Windows provides no atomic cross-app verify-and-paste operation. Editors that redirect paste or silently move to an identical selection without a detectable focus or input change can limit verification. The copy fallbacks can be visible to Windows clipboard history or third-party clipboard monitors.
- **Diagnosing a failure.** Launch with `--diagnostic` and use the `op=` field to correlate capture, clipboard, API and replacement events. `--inspect-clipboard` logs registered format names and the owner’s executable without reading the payload. The normal log also omits selected text and credentials. The pill and the Settings → Cache & Diagnostics tab now show the specific failure reason (e.g. `capture.elevated_target`, `api.timeout`, `clipboard.preservation_limited`) instead of a generic "Couldn't refine text".
- **OpenAI error.** Check that your project key is valid, its API billing is active, and the project can use `gpt-6-luna`. Requests time out and use zero automatic retries. Each new shortcut press after completion is a new request. The app validates the response before making any document edit.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The automated suite uses the real OpenAI SDK with mocked HTTP transport. It covers shorthand prompts and output checks, focus changes, repeated hotkeys, guarded clipboard transactions, overlay timing, reduced motion, and 150% scaling with a simulated secondary monitor. It uses a native Windows mutex for duplicate-instance prevention. It uses no API credits. **185 tests pass on Linux (69 Windows-only tests skipped — they need real Win32/UIA). No Windows live testing was done for this rebuild; run [WINDOWS_TEST_CHECKLIST.md](WINDOWS_TEST_CHECKLIST.md) on a real laptop before trusting the compatibility table.**

Run `.\.venv\Scripts\python.exe tests\windows_clipboard_integration.py` for native clipboard tests without API calls. It uses a private window station by default. If Windows denies creating one, the explicit `--interactive-clipboard` option temporarily seeds and restores the real clipboard when Luna can back it up safely. Avoid other clipboard activity during this short test. The [Round 4 test report](TEST-REPORT.md) distinguishes this fixture from editor compatibility tests.

To exercise the same editor transaction with a fixed response and no API calls, quit the regular listener and run `.\.venv\Scripts\python.exe tests\editor_harness.py`. In a scratch field select exactly `i has a luna test` and try each of the six **Ctrl+Win+Z** chords. Expect `I have a Luna test.` in Grammar mode; this harness checks routing and editing, not model tone. Verify that surrounding text stays in place. Repeat after restarting the harness and leave test messages unsent. Use **Ctrl+C** in the harness console to stop it.

For an unsupported editor, run `.\.venv\Scripts\python.exe tests\inspect_focused_editor.py whatsapp.root.exe` and then focus its scratch composer. The probe reports only Windows classes, process relationships, and accessibility pattern metadata. Use the relevant executable name when inspecting another editor.

For interactive tests, use a scratch document or open [the local browser fixture](tests/browser_fields.html) in Chrome and Edge. It includes an input, a multiline textarea, a contenteditable composer, and a password field. Use non-sensitive text because a normal correction sends the selection to OpenAI.

| Test | Expected behavior |
| --- | --- |
| Select a misspelled sentence between two unselected words in Notepad | Only the selection changes. Ctrl + Z restores it. |
| Repeat in the browser fixture’s input, textarea, and composer in Chrome and Edge | Select only part of a sample and check that the surrounding text stays in place. The password field is skipped. |
| Try a scratch message in ChatGPT, WhatsApp Web, and Gmail without submitting it | Supported compose fields behave like the local composer. |
| Try a scratch document in Word and Google Docs | The selected text changes if the editor exposes a verifiable range. An unsupported field is skipped. |
| Select two paragraphs, including a blank line | Grammar changes while line breaks and paragraph layout remain. |
| Press the shortcut at a caret with no selected text | The document and clipboard stay as they were. A keyboard fallback may report **Nothing copied**. |
| Hold the chord or press it rapidly | Requests never overlap. Extra input may cancel the first edit. |
| Disconnect your internet and correct a selection | A connection error or timeout is logged and the text remains. |
| Start a correction and immediately switch apps | The correction is canceled and neither document changes. |
| Start a correction and immediately select another occurrence of the same text | The correction is canceled. |
| Copy a distinct text marker, correct in Chrome, and paste elsewhere | The original clipboard marker pastes. |
| Repeat with rich text and a copied image | Supported formats survive, or an unsupported format causes a safe skip. |
| Correct `i met Zoë at 3pm 😀` and a sentence in another language | Names, numeric details, emoji, and the language are preserved. |
| Correct `its gong fine for me hby` with shorthand enabled | The expected correction is “It's going fine for me. How about you?” |
| Try a correction on a secondary monitor with different scaling | The capsule stays on that monitor and preserves focus. |
| Enable **Reduced** animation and repeat | The waveform is static and result feedback still dismisses automatically. |
| Temporarily start from a shell with a deliberately invalid key | The log reports rejected credentials and the document remains. Restart with your valid key afterward. |
| Run `main.py --check` while the listener is running | The diagnostic reports the hotkey conflict. |
| Start a second copy while the first is running | The second copy reports that the listener is already running. |

The [generated design board](design/luna-grammar-concepts.png) shows six visual concepts. The live overlay is rendered from code, and the settings and tray controls are functional.

## Earlier reports

- [KEY-RELEASE-FIX.md](KEY-RELEASE-FIX.md) — the stuck Release-shortcut error and executable checksum.
- [UI-FIX-REPORT.md](UI-FIX-REPORT.md) — the repaired executable and its verification results.
- [ROUND5-REPORT.md](ROUND5-REPORT.md) — Round 5 implementation, benchmarks, and manual checklist.
- [TEST-REPORT.md](TEST-REPORT.md), [TEXT-BOX-COMPATIBILITY-REPORT.md](TEXT-BOX-COMPATIBILITY-REPORT.md), [UPGRADE-100X-REPORT.md](UPGRADE-100X-REPORT.md) — earlier test and compatibility reports (historical; the compatibility table above supersedes them where they disagree).
