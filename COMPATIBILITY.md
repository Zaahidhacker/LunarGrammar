# Luna Grammar — Compatibility & Layered Engine

How Luna captures and replaces selected text on Windows 11, what works where, and what is impossible by design. This document is the honest version of the compatibility story: the research behind it is public-web research (Grammarly / LanguageTool / Microsoft Editor integration docs, Microsoft Learn UIA and Win32 docs, CapyBro / Dictatem / Retext engineering notes) — **not** live Windows testing of this build. Run [WINDOWS_TEST_CHECKLIST.md](WINDOWS_TEST_CHECKLIST.md) on a real laptop before treating the table as verified.

## The layered engine

No single API works everywhere, so Luna tries layers in a fixed order and records which one succeeded or failed. The order is: **UI Automation → native Win32 messages → clipboard Ctrl+C / Ctrl+V → copy-only fallback**.

### Capture (at the hotkey, before any API call)

1. **Snapshot focus** — `GetForegroundWindow` + `GetGUIThreadInfo.hwndFocus` (the actual focused *child* HWND, e.g. the Scintilla child inside Notepad++) + process name / PID / integrity level. Refused immediately with a specific message if: no focused element, the field is a password, it is not enabled, or the target runs at a higher integrity level than Luna (see "Impossible by design").
2. **UI Automation TextPattern `GetSelection()`** — the focused element's selected text. A degenerate (empty) range at the caret means "caret only", not "nothing selected".
3. **Win32 `EM_EXGETSEL` / `EM_GETSEL` + `WM_GETTEXT`** — only when the focused child is a real `Edit` / `RichEdit` class. Cheap, synchronous, no clipboard side effects. `EM_GETSEL` packs two 16-bit indexes and fails beyond the first 64 KB; RichEdit uses the `EM_EX*` pair.
4. **Clipboard Ctrl+C via SendInput** — the clipboard is saved first (all retrievable formats), Ctrl+C is sent, and the clipboard sequence number must change to prove the copy landed. If it did not, the field does not support copy (or nothing was selected) — Luna reports that and **does not call the API**.
5. **If all layers fail, Luna does not call OpenAI.** The pill shows the specific reason (e.g. "no UIA TextPattern / copy returned nothing / field is protected") instead of a generic "Couldn't refine text".

### Replace (after the API call, only after re-validating focus and selection)

6. **`EM_REPLACESEL`** — only if the Win32 capture path succeeded (same HWND, same control, selection still identical). Cleanest: preserves undo and formatting, no clipboard involved.
7. **Clipboard Ctrl+V via SendInput** — the general path. Focus is restored to the captured *child* HWND (AttachThreadInput sandwich), Ctrl+V is sent, the result is **verified by re-reading** the field, and only then is the user's clipboard restored. If verification fails, the corrected text stays on the clipboard and the pill says "Copied — press Ctrl+V".
8. **Copy-only fallback** — if replacement is impossible or the user enabled **Copy correction to clipboard instead of pasting** (Settings → General → Safety & Review), the corrected text is staged on the clipboard for a manual Ctrl+V. No undo record is created, because nothing was replaced.
9. **Give up gracefully** — the corrected text stays on the clipboard with a manual-paste message; Luna never pastes into an unverified window.

### What Luna does NOT rely on

- `keybd_event` / `SendKeys` / `pyautogui` — superseded by `SendInput` (atomic batches, layout-independent Unicode).
- `WM_PASTE` — many apps ignore it and it bypasses the app's paste/undo handling.
- `ValuePattern.SetValue()` for partial replacement — replaces the **whole** field and, in browsers, changes the DOM without firing `input` events, so React / Slack / Discord / Teams state never updates.
- `WM_SETTEXT` — whole-field replacement that clears undo.
- MSAA except as a Firefox fallback; direct DOM / CDP / browser extension — a separate product, out of scope for the tray app.

### Focus plumbing (the part that decides success)

The hotkey fires, the API call takes seconds, and the user may click elsewhere in between. Luna snapshots the focus at chord start, restores it with the AttachThreadInput sandwich (`AttachThreadInput → BringWindowToTop → SetForegroundWindow → SetFocus(child) → detach in a finally`), and re-validates focus + selection before pasting. If the target changed, the paste is aborted and the corrected text is offered for manual Ctrl+V instead.

### Per-field feasibility

| Field / app | Capture (best method) | Replace (best method) | Reliability | Notes |
|---|---|---|---|---|
| Classic Win32 EDIT (dialogs, old apps) | UIA TextPattern, or `EM_GETSEL`+`WM_GETTEXT` | `EM_REPLACESEL` | ★★★★★ | The easy case. |
| RichEdit (WordPad, classic Notepad) | UIA TextPattern; `EM_EXGETSEL` | `EM_REPLACESEL` | ★★★★★ | Use `EM_EX*` beyond 64 KB. |
| Windows 11 Notepad (WinUI 3) | UIA TextPattern (ControlType Document) | Clipboard Ctrl+V | ★★★★ | Not a classic `Edit` class — do not branch on class name; use UIA. |
| WPF `TextBox` / `RichTextBox` | UIA TextPattern / ValuePattern | Clipboard; ValuePattern whole-field only | ★★★★ | WPF implements UIA natively. |
| WinUI / UWP (`TextBox`, `RichEditBox`) | UIA TextPattern | Clipboard; `SetValue` whole-field only | ★★★★ | AppContainer targets may additionally block input without uiAccess. |
| Word (desktop) | UIA TextPattern; COM `Selection` | COM `Selection.TypeText` / clipboard | ★★★★ | IME: prefer clipboard over Unicode typing. |
| Outlook (compose) | UIA; COM via WordEditor | COM / clipboard | ★★★★ | New Outlook (WebView2) behaves like a browser field. |
| PowerPoint (text boxes) | UIA TextPattern | COM `TextRange` / clipboard | ★★★ | Per-shape; UIA selection is shape-scoped. |
| Excel cells | UIA ValuePattern | Clipboard / COM | ★★★ | In-cell edit vs formula bar are different elements. |
| Chrome / Edge — `<textarea>`, `contenteditable` | UIA TextPattern (tree built on demand); else Ctrl+C | Clipboard Ctrl+V | ★★★★ | `<input>` fields: UIA is thinner — clipboard is the reliable path. |
| Chrome / Edge — `<input>` (single-line) | Ctrl+C | Ctrl+V | ★★★ | UIA often exposes only the value, no selection. |
| Firefox — any field | Ctrl+C | Ctrl+V | ★★★ | UIA via a buggy MSAA proxy; `IAccessible2` is read-only for setting text. |
| Google Docs / Sheets (canvas) | Ctrl+C only | Ctrl+V only | ★★★ | No UIA text node — text is pixels. |
| VS Code / Monaco | Ctrl+C | Ctrl+V | ★★★ | UIA sees at most the hidden textarea, partial text only. |
| Teams / Slack / Discord / WhatsApp Desktop (Electron) | UIA TextPattern if the tree is built; else Ctrl+C | Clipboard Ctrl+V | ★★★ | Tree often empty without `--force-renderer-accessibility`; never walk the whole tree (hang risk). |
| Notepad++ (Scintilla child) | Ctrl+C; UIA partial | Clipboard after focusing the Scintilla child | ★★★★ | Top-level focus restore is insufficient — the child HWND must be focused. |
| Terminals / consoles | Not attempted | — | ★★ | Ctrl+C is Break. |
| Password / PIN fields | **Refuse** | **Refuse** | — | By design. |
| Read-only / disabled | Read OK | **Refuse** | — | `IsReadOnly` / `IsEnabled` / styles are checked first. |
| Elevated apps (admin anything) | **Blocked (UIPI)** | **Blocked (UIPI)** | — | Needs uiAccess / run-as-admin. Detect + explain. |
| UAC / login / secure desktop | **Impossible** | **Impossible** | — | Separate desktop. |

## Impossible by design

- **Elevated targets from a medium-integrity Luna.** UIPI silently drops `SendInput`, blocks most `SendMessage`, and returns an empty UIA tree — `SendInput` even returns success, so nothing reports the block. Luna detects the integrity mismatch (`capture.elevated_target`) and says: "The focused app is running as administrator. Restart Luna Grammar as administrator, or restart the app normally." The sanctioned bypass is `uiAccess="true"` in the manifest, which needs a code-signing certificate + install under `%ProgramFiles%` — a packaging/signing decision, not a code fix.
- **UAC / secure desktop / login screens.** No user app can reach them.
- **Password fields.** `IsPassword` / `ES_PASSWORD` is a hard refusal. Since Jan 2026 (KB5074109, CVE-2026-20824), Windows also blocks synthetic input into protected authentication dialogs.
- **DRM / Protected View** (Outlook DRM mail, Word Protected View). UIA/Win32 expose nothing by design; COM is blocked.
- **Canvas editors beyond clipboard** (Google Docs, Figma). Only Ctrl+C/Ctrl+V works system-wide without a browser extension.
- **IME composition active.** Do not inject while composing; clipboard paste is preferred over Unicode typing, which Word / Japanese editors can garble.

## Diagnostics — which layer failed and why

Every failure is recorded (metadata only — never selected or corrected text) with a stage, a code, the app, and the field class. The last failure is shown in **Settings → Cache & Diagnostics** and written to `%LOCALAPPDATA%\LunaGrammar\last-failure.json` so the Settings process can read what the listener saw.

| Stage | Example codes | Meaning |
|---|---|---|
| capture | `capture.no_fresh_text`, `capture.elevated_target`, `capture.selection_too_long`, `capture.protected_field` | No text could be obtained, target is elevated, selection is over the limit, or the field is protected |
| api | `api.timeout`, `api.connection_failed`, `api.validation_failed`, `api.invalid_response` | Network/timeout, or the model returned something validation rejected (the specific reason is now kept, e.g. "The correction changed a URL.") |
| clipboard | `clipboard.busy`, `clipboard.preservation_limited`, `clipboard.changed`, `clipboard.restore_failed` | Clipboard held by another app, formats Luna cannot back up (refused by default — see below), clipboard changed mid-operation, restore failed |
| replace | `replace.unsafe`, `replace.failed` | Focus/selection changed before pasting, or the paste could not be verified |
| correction | `correction.rejected` | The correction was rejected (e.g. by validation) |

### Clipboard preservation — the strict default

Luna backs up the clipboard before copying and restores it after a verified paste. Some formats cannot be duplicated (images with OLE data, owner-dependent formats, >64 MB totals). The old behaviour silently fell back to a partial backup and **destroyed the un-duplicable formats**. The new default (`clipboard_strict_preservation: true`) fails closed: the correction is refused with `clipboard.preservation_limited` and a clear message, and your clipboard is untouched. Turn the setting off (Settings → General → Safety & Review) only if you accept the old best-effort behaviour.

The paste path also had a double-paste race: a slow first Ctrl+V read could be followed by a second Ctrl+V, pasting twice. The fallback now checks whether the first read already landed before sending a second paste.

## Settings that affect compatibility

| Setting (settings.json key) | Default | Effect |
|---|---|---|
| `copy_only` | `false` | Stage the correction on the clipboard instead of pasting — the safe mode for fragile fields. |
| `review_before_apply` | `false` | Hold each correction in the pill with Apply / Discard (30 s, then applies automatically). |
| `clipboard_strict_preservation` | `true` | Refuse a correction rather than lose clipboard formats. |
| `per_app_modes` | `{}` | `{"outlook.exe": 2}` — bare Ctrl+Win+Z uses mode 2 in Outlook; explicit digits always win. |
| `excluded_apps` | password managers, … | Luna ignores the hotkey entirely in these apps. |
| `max_selection_chars` | `6000` | Long selections are corrected paragraph by paragraph; a single paragraph over the limit keeps a clear error. |
| `default_mode` | `0` | The mode a bare Ctrl+Win+Z uses (now actually honoured — it was ignored before). |

## Sources

- Microsoft Learn — Edit Control Text Operations; Interact with the Current Selection (RichEdit); UI Automation TextPattern Overview; `TextPattern.GetSelection`; `ValuePattern.SetValue`; UI Automation Support for the Edit Control Type; `IUIAutomation`.
- Microsoft Learn — UIPI issues (Power Automate); Windows Integrity Mechanism / UIAccess.
- Grammarly — integrating with a website/app; Grammarly for Windows user guide.
- LanguageTool — Windows app (Outlook + Notepad only at launch).
- CapyBro — Win32 paste-back (AttachThreadInput, clipboard retry); Dictatem ADR-0004 (SendInput typing vs clipboard race); Retext (SendInput-only clipboard); Windows Terminal clipboard retry.
- Chromium UIA docs; Firefox UIA (Bugzilla 1957255); Python `uiautomation` / `uiautomation-new`.
- KB5074109 / CVE-2026-20824 — synthetic-input block in protected authentication dialogs.
