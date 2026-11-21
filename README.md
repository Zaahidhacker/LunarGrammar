# Luna Grammar

The current release fixes the stuck **Release shortcut** error; see [KEY-RELEASE-FIX.md](KEY-RELEASE-FIX.md) for the cause, checks and executable checksum.

The current repaired executable and its verification results are documented in [UI-FIX-REPORT.md](UI-FIX-REPORT.md). To exercise all four visible status labels without sending text to the API, run `.\dist\LunaGrammar.exe --check-overlay`.

Round 5 implementation, benchmarks, executable checksum and the remaining manual test checklist are in [ROUND5-REPORT.md](ROUND5-REPORT.md).

Select text in an editable Windows 11 field and use one of these shortcuts. Hold Ctrl and Win first, then press Z and optionally 1, 2 or 3 before releasing the chord. Keep the selection and focus in place until the correction appears. A small lime waveform shows that Luna is working. A checkmark appears briefly after the edit. You can turn off the overlay in Settings.

| Shortcut | Mode |
| --- | --- |
| Ctrl + Win + Z | Grammar, spelling, punctuation and clear shorthand; preserves casual tone |
| Ctrl + Win + Z + 1 | Friendly, lightly polished professionalism |
| Ctrl + Win + Z + 2 | Concise business professionalism |
| Ctrl + Win + Z + 3 | Refined formal professionalism, without unnecessary length |

Luna commits once when all chord keys are released. There is no fixed arbitration timer.
After Ctrl+Win are down, Z and the digit may arrive in either order, and release order does not matter.
Top-row and numpad 1–3 are supported, including non-extended numpad navigation with NumLock off.
The first level digit wins if more than one is pressed. Repeated/held keys never enqueue duplicate requests.
While enabled, Ctrl+Win+1/2/3 are reserved as potential chord prefixes; release without Z does nothing.
Press the modifiers first: a digit or Z delivered to an editor before Ctrl+Win cannot be retroactively suppressed.
Other editing keys or mouse actions during the chord cancel it. Release the full chord before starting another.

Luna Grammar sends the selected text to OpenAI's Responses API with `store=False`. Each request is independent and uses GPT-6 Luna by default. The app keeps request text, corrections, and credentials out of its local logs. OpenAI's API data handling is governed by your project's settings and [OpenAI's data controls](https://developers.openai.com/api/docs/guides/your-data).

## Run the Windows executable

Keep [LunaGrammar.exe](dist/LunaGrammar.exe) in a permanent folder and double-click it. It runs without a console. Use the notification-area icon to open Settings, pause the shortcut, or quit. Quit the Python listener before launching the executable.

The executable reads `OPENAI_API_KEY` from its environment. For Explorer launches, set a user environment variable as described under **Start at Windows sign-in**, then sign out and back in. The key is never bundled. You can launch from a PowerShell session that already has the key while setting up.

Packaged preferences are stored in `%LOCALAPPDATA%\LunaGrammar\settings.json`. To carry over preferences from the Python version, copy the project’s `settings.json` there before your first packaged launch. Keep your existing profile file if you already use the packaged version.

To build from source on Windows x64 with Python 3.12 and Tcl/Tk, run `.\build.ps1`. It installs the pinned build requirements and writes `dist\LunaGrammar.exe`. Run `.\tests\release_smoke.ps1` in an interactive Windows session after quitting Luna to check launch, duplicate rejection, tray registration, and restart.

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

The overlay uses Poppins and samples the lime accent from the reference. It follows the editing window’s monitor and Windows animation preferences. Choose **Reduced** for a static waveform, **Light** for a light capsule, or turn off **Show overlay feedback**. Clicking the capsule’s × dismisses it. While a correction is pending, that click also cancels the edit through the input guard.

For advanced configuration, edit the version’s `settings.json` and restart the app. `model` defaults to `gpt-6-luna` and can be overridden with `LUNA_GRAMMAR_MODEL`. `timeout_seconds` sets the SDK timeout. `max_selection_chars` bounds the text submitted per request. `excluded_apps` accepts case-insensitive executable names. To exclude a sensitive browser-based app, exclude its entire browser executable, such as `chrome.exe`.

- **Shortcut conflict.** If registration fails, check for a second instance or another app using Ctrl + Win + Z. Windows or local policy can reserve the chord. Luna Grammar reports the Windows error and exits.
- **Nothing changed.** Inspect the log in diagnostic mode. Keep the original field and selection active until the request finishes. Typing, clicking, scrolling, switching apps, changing focus, or altering the selection can cancel the edit. Ordinary pointer movement is allowed. Already-correct and empty selections are left alone.
- **Nothing copied.** Luna first looks for an editable UI Automation range. In recognized browsers and accessibility-identified edit controls, it can fall back to ordinary Ctrl+C even without a text or value pattern. The copy must produce fresh text from the target application. Luna re-copies and compares the selection before pasting. If a writable field value is available, the selection must also occur exactly once in that value.
- **Unsupported or protected field.** Detected passwords, read-only fields, disjoint selections, and classic edits that may truncate are skipped. Luna avoids sending Ctrl+C to unknown controls without evidence that they are editors. Canvas-based Google Docs, protected Word controls, custom editors, and elevated applications can limit capture or replacement. Run Luna Grammar as your normal user.
- **Clipboard issue.** Luna backs up named, registered Win32 formats, including HTML, RTF and application-specific data, along with common images and file drops. It also preserves the tested ownerless cached OLE image representation, including its stream metadata. Active OLE source references and owner-dependent formats use the clipboard-free native route where available and can cause a safe skip in clipboard-dependent editors. A newer clipboard write takes precedence when it can be distinguished from Luna’s copy.
- **Formatting and timing.** Replacements use plain text, and formatting inside the selection can change in rich editors. Luna checks focus and input before offering text through delayed clipboard rendering. Windows provides no atomic cross-app verify-and-paste operation. Editors that redirect paste or silently move to an identical selection without a detectable focus or input change can limit verification. The copy fallbacks can be visible to Windows clipboard history or third-party clipboard monitors.
- **Diagnosing a failure.** Launch with `--diagnostic` and use the `op=` field to correlate capture, clipboard, API and replacement events. `--inspect-clipboard` logs registered format names and the owner’s executable without reading the payload. The normal log also omits selected text and credentials.
- **OpenAI error.** Check that your project key is valid, its API billing is active, and the project can use `gpt-6-luna`. Requests time out and use zero automatic retries. Each new shortcut press after completion is a new request. The app validates the response before making any document edit.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The automated suite uses the real OpenAI SDK with mocked HTTP transport. It covers shorthand prompts and output checks, focus changes, repeated hotkeys, guarded clipboard transactions, overlay timing, reduced motion, and 150% scaling with a simulated secondary monitor. It uses a native Windows mutex for duplicate-instance prevention. It uses no API credits.

Run `.\.venv\Scripts\python.exe tests\windows_clipboard_integration.py` for native clipboard tests without API calls. It uses a private window station by default. If Windows denies creating one, the explicit `--interactive-clipboard` option temporarily seeds and restores the real clipboard when Luna can back it up safely. Avoid other clipboard activity during this short test. The [Round 4 test report](TEST-REPORT.md) distinguishes this fixture from editor compatibility tests.

To exercise the same editor transaction with a fixed response and no API calls, quit the regular listener and run `.\.venv\Scripts\python.exe tests\editor_harness.py`. In a scratch field select exactly `i has a luna test` and try each of the four **Ctrl+Win+Z** chords. Expect `I have a Luna test.` in every mode; this harness checks routing and editing, not model tone. Verify that surrounding text stays in place. Repeat after restarting the harness and leave test messages unsent. Use **Ctrl+C** in the harness console to stop it.

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
