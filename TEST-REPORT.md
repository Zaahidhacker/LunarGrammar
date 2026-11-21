# Luna Grammar Round 4

## A. Root cause

The three IDs in the supplied log were resolved with Windows `GetClipboardFormatNameW` on this desktop.

| Logged ID | Registered name | Meaning for Luna |
| --- | --- | --- |
| `0xC009` | `DataObject` | OLE bookkeeping associated with source data objects |
| `0xC231` | `ClipboardHistoryItemId` | A registered Win32 format that can be backed up when its handle is readable |
| `0xC013` | `Ole Private Data` | OLE bookkeeping that can describe storage media and depend on the source |

The previous snapshot rejected any registered name outside a fixed list before trying to back up the clipboard. The logged failure happened after selection capture and before replacement, even though UI Automation had verified the range. Notepad could succeed in the same situation because its native edit message bypassed the clipboard. Clipboard state and provider readiness can vary between launches. Leaked handles and stale COM state remain unproven.

Windows also advanced the sequence while closing the staged clipboard and synthesizing formats in the native regression test. A strict paste sequence comparison misidentified Luna’s own offer as a newer item. Paste now matches the owner HWND and a random per-offer marker. Copy still checks sequence and owner, plus recent input for keyboard copies. A temporary item is restored after a safely attributable copy even when focus has moved.

The follow-up copy check requires the window holding the open clipboard to match the observed writer before allowing its sequence to advance. A separate reader's clipboard lock cannot explain a newer sequence. The native OLE probe returned `CLIPBRD_E_CANT_OPEN` when calling `OleSetClipboard` with the Win32 clipboard locked. The outer lock stayed intact. Releasing it to publish an OLE object would create a race with newer clipboard writes. [OleSetClipboard](https://learn.microsoft.com/en-us/windows/win32/api/ole2/nf-ole2-olesetclipboard)

A separate WhatsApp Desktop failure was reproduced on the preceding executable. The listener stopped at `capture.unsupported_target`, before requesting a correction or writing to the clipboard. A read-only focus probe found `whatsapp.root.exe` hosting a focused `Chrome_WidgetWin_0` child inside a WinUI window. UI Automation reported Win32 wrapper elements without Text or Value patterns. The prior classifier recognized browser executables and `Chrome_RenderWidgetHostHWND`, so it rejected this focus window. The generic embedded Chromium rule now verifies that the focused child belongs to the active top-level window, then allows guarded copy and re-copy.

The first retest reached the copy path but reported `Nothing copied`. Windows identified the actual owner as a hidden Chromium window in `msedgewebview2.exe`, a direct child of the WhatsApp host. The write had occurred, but the clipboard previously accepted only the foreground and keyboard-focus processes. That failed attempt left the newly copied item in place because Luna could not safely attribute it. Copy and delayed paste now also accept the direct WebView2 child of the verified embedded host. A different host's WebView2 process remains outside that rule.

The subsequent packaged retest reproduced `Clipboard preservation limited` with a copied image. The item had no owner window, a zero `DataObject` marker, and fully materialized OLE backing data. The guard had classified this cached representation together with live OLE objects. A dedicated native fixture verified three backup/restore cycles of this image, comparing every native memory block and the data returned through OLE `IStream` and `HGLOBAL` media. Luna now backs up this checked cached representation when it is ownerless or is a cache Luna has just restored. Nonzero source references and other owning applications continue through the preservation guard. This support is scoped to the cached Windows representation verified here.

The user later reported a failed Bing search-field correction. The matching browser attempts logged input-change cancellations after capture and API completion. The guard used `GetLastInputInfo`, which also changes for mouse movement. Production now uses a dedicated editing-input monitor. It counts keystrokes, mouse-button actions and wheel actions, allows ordinary pointer movement, and excludes Luna's tagged synthetic copy/paste events. The callbacks retain an event counter and immediately continue the Windows hook chain. Focus and selection verification still run before replacement. The user confirmed that the Bing source retest corrected the selection, and the log recorded paste delivery and clipboard restoration.

## B. Fixes

- `clipboard_manager.py` updates `snapshot`, `cached_ole_item`, `copy`, `paste`, and `render`. It duplicates registered Win32 memory and uses handle-specific operations for bitmaps, palettes and metafiles. The checked cached-OLE route preserves the complete materialized backing data and its metadata. Active source references retain the preservation guard.
- `text_selection.py` and `win32.py` verify selection ranges or recopy when needed, read classic Unicode Edit selections directly when possible, check the foreground and actual focused child, and wait for the physical chord to be released. A verified native replacement is bounded to the original selection. A paste offers plain Unicode to the target, with no Enter key synthesized.
- `windows_hotkey.py` registers after worker readiness, handles out-of-order Windows focus notifications, keeps UI Automation on the worker’s MTA, and closes the worker and hotkey under a single-instance mutex. `diagnostics.py`, `main.py`, and `grammar_engine.py` correlate phases and classify errors without logging document text, API bodies, or credentials.
- `input_monitor.py` adds `InputMonitor.keyboard`, `mouse`, `stamp`, and its dedicated message loop. It counts editing actions, permits pointer movement, and identifies Luna's own tagged events. `win32.edit_shortcut` attaches the tag, and `Guard` uses the monitor's counter in the running listener.
- `LunaGrammar.spec`, `requirements-build.txt`, and `build.ps1` reproduce the Windows x64 build. The archive bundles the icon, Poppins and its license. The first packaged API test revealed that the build runtime expects a certificate distrust file alongside its SSL module. The spec now carries that file into the bundle when the runtime supplies it, and the local check initializes TLS. The executable loads profile preferences and takes the API key from the environment. Installation and preference migration are in the README.

Win32 registered format and OLE behavior are documented by Microsoft. [Registered formats](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerclipboardformatw) · [Clipboard formats and synthesis](https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats) · [OLE clipboard data objects](https://learn.microsoft.com/en-us/windows/win32/api/ole2/nf-ole2-olegetclipboard)

## C. Clipboard compatibility

`snapshot` uses Windows handle types for bitmap, palette and metafile objects, and duplicates bounded global-memory formats. `cached_ole_item` permits the tested serialized OLE cache when its source marker is zero and its owner is absent or is Luna's restore window. The image's original PNG stream metadata survives this route. Active source references and private owner-dependent formats retain the preservation guard. Registered IDs are resolved by name each session.

## D. Application compatibility

| Editor | Observed result |
| --- | --- |
| Windows Notepad | Source correction passed through UI Automation and the native replacement path. The user confirmed the final EXE correction and undo after restart. |
| Edge input, textarea and contenteditable fixture | The user confirmed all three fields with Python and an earlier packaged build. |
| WhatsApp Desktop | The user confirmed source and packaged corrections. The cached-OLE build preserved the image exactly during a monitored live correction. The user also confirmed correction and undo on the final input-monitor EXE. |
| ChatGPT.com | The user confirmed two scratch corrections after restarting the final EXE, including surrounding text and undo. Earlier browser logs recorded verified capture and paste restoration during the web checks. |
| WhatsApp Web | The user confirmed two scratch corrections after restarting the final EXE, including surrounding text and undo. |
| Bing search input | The source retest passed after editing-input tracking replaced the broad last-input timestamp guard. The user confirmed correction and undo on the final EXE. |
| Gmail and Microsoft Word | Direct editor tests remain open. The Computer Use Word launch approval timed out. |

## E. Stability

`Listener.worker` keeps its UI Automation references on its initialized COM worker and releases them during shutdown. Hotkey registration follows worker readiness. The message loop tracks focus changes, filters older queued events, and stops pending replacements on shutdown. The mutex, registered hotkey, focus hooks, editing-input hooks, tray icon, overlay and hidden window have explicit cleanup. The input hooks use their own message thread. The packaged smoke test exercised two complete restart cycles and duplicate rejection.

## F. Executable

Run `dist/LunaGrammar.exe` by double-clicking it. Use its notification-area menu to pause, open Settings or quit. The executable reads `OPENAI_API_KEY` from the environment, and its preferences live in `%LOCALAPPDATA%\LunaGrammar\settings.json`. The project preferences were copied into the new packaged profile and verified byte-for-byte. The README describes launch and environment setup. Run `build.ps1` to reproduce the Windows x64 build.

Release size is 28,898,213 bytes.
SHA-256 is `370CBED2D343A81CC3148C6FAF2BDD2E03F26DBCEA0CF06F2AA4054232C5D8E0`.

## G. Verification

| Check | Result |
| --- | --- |
| Automated selection, clipboard, hotkey, model and overlay suite | Pass. 69 tests on Windows, including editing-input classification, WinUI/Chromium layout, WebView2 clipboard ownership, cached OLE eligibility, and rejection of a live reference, unattached child or unrelated WebView2 process. OpenAI calls were mocked. |
| Native editing-input monitor | Pass. Three hook registration/shutdown cycles completed. Unit cases cover pointer movement, clicks, wheel actions, physical or externally injected keys, Luna's own tag, and a stopped monitor. |
| Real Windows clipboard fixture | Pass. Three copy/paste/restore cycles with Unicode and multiline text, HTML, RTF, DIB image, file drop and arbitrary registered data. The fixture simulated the editor’s shortcut dispatch while using real clipboard APIs and delayed rendering. |
| Native Win32 Edit fixture | Pass. Three corrections used a real hidden Edit control with a mocked correction engine. UTF-16 selection boundaries, emoji, multiline text, surrounding text and EM_UNDO were verified without clipboard access. |
| Cross-process clipboard fixture | Pass. An independent process supplied copied text and the original scratch formats were restored. When that process wrote a newer clipboard item during a separate paste, Luna left the newer item in place. |
| Cached OLE image fixture | Pass. Three restore cycles preserved the actual ownerless cached image, its native backing blocks, OLE format descriptors and data read through IStream/HGLOBAL. The fixture retries a transient OLE clipboard-busy status within one second. |
| Private test clipboard | Windows denied creating a private window station. The explicit interactive fixture ran with a verified backup and restored the original item. |
| Development build in Windows Notepad | Pass. A physical Ctrl+Win+Z captured the selected scratch text through UI Automation, GPT-6 Luna expanded the shorthand, and the native edit succeeded. |
| Development build in Microsoft Edge | Pass. Three physical shortcuts in a standard input, multiline textarea, and contenteditable composer. The logs show verified UI Automation capture, delayed paste delivery, and clipboard restoration for all three. |
| Development build in WhatsApp Desktop | Pass on the reported WinUI/WebView2 build. The user confirmed the scratch correction. The log shows copy, re-copy, live API completion, delayed paste, and restoration of the original HTML and Chromium formats. An attempt with intervening user input canceled before paste. |
| WhatsApp Desktop with a cached image on the clipboard | Pass on the source listener. The user confirmed the correction, and the log recorded cached OLE snapshot and restoration at capture, re-copy, and paste. |
| GPT-6 Luna model access | Pass. The project returned model metadata, and the Notepad correction completed through the live API. |
| Live OLE-backed clipboard when the editor needs Ctrl+C or Ctrl+V | Limited. Deliberately stops before changing the clipboard. |
| Packaged Windows binary | Pass. PE headers confirm x64 GUI mode. The archive contains the UI assets, font license, and TLS resources. Profile settings and credentials are external. |
| Packaged Settings and model access | Pass. The Settings window opened, and the bundled runtime retrieved the configured model metadata over verified TLS. |
| Packaged lifecycle | Pass on the current executable. Two start/stop cycles launched from outside the project directory. Both registered the tray icon, rejected a duplicate listener, stopped cleanly, and released Ctrl+Win+Z. The same executable also passed the live model check. |
| Packaged startup shortcut | Pass. A temporary link outside Windows Startup targeted the EXE with empty arguments and its own directory as the working directory. Creation and removal passed through the real Windows shortcut API. Windows sign-in remains unverified. |
| Existing preferences | Pass. The new packaged profile was initialized from the project settings and the two files matched byte-for-byte. |
| Packaged correction in Microsoft Edge | Pass on the preceding executable. The user confirmed all three fixture fields. Three operations logged a successful edit and clipboard restoration. Two additional attempts canceled when focus or input changed. The follow-up change affects keyboard copy attribution and was verified with the Windows clipboard fixture. |
| Monitored packaged correction in WhatsApp Desktop | Pass on the cached-OLE executable before the input-monitor addition. The user confirmed the correction with the cached image on the clipboard. The independent read-only monitor compared the native backing blocks and data returned through OLE media before and after the live correction and reported an exact match. |
| Final input-monitor EXE regression | The user confirmed that Bing, WhatsApp Desktop and Notepad all passed after restart, including Ctrl+Z undo. This final per-app result is based on the user's manual confirmation. |
| Web composer repeat tests | Pass by manual confirmation. The user reported that ChatGPT.com and WhatsApp Web each passed twice after the final restart, including surrounding-text and undo checks. |

The manual fixture in `tests/browser_fields.html` supplies synthetic selections surrounded by `Before [` and `] After`. Verify both markers, Ctrl+Z, repeated edits, and a repeat after restarting Luna. For ChatGPT, WhatsApp Web, WhatsApp desktop and Gmail, keep the test in an unsent scratch composer. In Word use a scratch document.

