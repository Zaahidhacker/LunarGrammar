# Luna Grammar — Round 5 delivery

**Historical report:** the current UI repair, executable checksum and additional completed Windows tests are in [UI-FIX-REPORT.md](UI-FIX-REPORT.md).

Delivered 13 November 2026 (Asia/Colombo). The original source, tests, configuration and working executable are retained in `round5-baseline/`. The original EXE SHA-256 remains `370CBED2D343A81CC3148C6FAF2BDD2E03F26DBCEA0CF06F2AA4054232C5D8E0`.

## A. Implementation

| File | Change |
| --- | --- |
| `shortcut_state.py` | Pure, release-based state machine; one committed mode per chord, repeat suppression, digit consumption, first-digit arbitration, cancellation, and numpad handling. |
| `input_monitor.py` | Reuses the existing dedicated keyboard-hook thread for chord events; retains editing-input tracking and Luna's synthetic-input tag. Hook callbacks queue events without clipboard, UIA, rendering or network work. |
| `windows_hotkey.py` | Keeps RegisterHotKey as the OS reservation/conflict check; only completed hook chords enqueue corrections. Captures the original target at chord start, preserves focus epoch and commit-time input stamp, retains the worker/mutex/tray lifecycle, and provides mode feedback. Empty selections dismiss the loading state. |
| `correction_modes.py` | Central grammar/light/business/formal hierarchy, per-mode examples, shared meaning-preservation rules and concise labels. |
| `grammar_engine.py` | Shared one-request engine, explicit mode parameter, prebuilt mode instructions, only relevant shorthand definitions, mode-aware length limits, and extra local Markdown rejection. Keeps GPT-6 Luna, persistent SDK/HTTP client, Responses API, `store=False`, no automatic retries, and the existing supported Luna options. |
| `diagnostics.py` | High-resolution monotonic stage timers. Logs fixed stage names, milliseconds, mode IDs and token counts; no selected text, generated text, request bodies or keys. |
| `text_selection.py` | Passes the chosen mode through the existing capture/verify/replace path, adds stage timings and rejects input arriving between chord commit and capture. Existing clipboard and selection protections remain. |
| `clipboard_manager.py` | Timing decorators only. Clipboard duplication, delayed rendering, attribution, newer-item preservation, settle interval and restoration behavior are unchanged. |
| `pill_art.py`, `overlay.py` | Mode label in the original 226 × 54 working pill; preserves logo, palette, waveform, font and animation behavior. |
| `settings_window.py` | Documents the additional level digits in the existing Shortcut section. |
| `README.md`, `tests/` | Shortcut instructions, 48-example suite, state-machine/regression tests, reproducible benchmarks and release verification. |

## B. Shortcuts

| Shortcut | Result |
| --- | --- |
| Ctrl + Win + Z | Grammar, spelling, punctuation, capitalization and clear shorthand; preserves casual tone. |
| Ctrl + Win + Z + 1 | Light, friendly, conversational polish. |
| Ctrl + Win + Z + 2 | Concise, respectful workplace wording. |
| Ctrl + Win + Z + 3 | Refined formal wording, proportionate to the original length. |

Hold Ctrl and Win first. Z and the level digit can then arrive in either order. Release all chord keys to commit. There is **no fixed arbitration timeout** and no grammar request issued before a professional request. All release orders and key repeat are covered by automated tests. The original capture path already required releasing editing modifiers; the new arbitration uses that release period rather than adding a separate timer.

Top-row and numpad 1–3 work; NumLock-off numpad End/Down/PageDown are recognized by non-extended scan codes. If multiple level digits are pressed, the first wins. While enabled, Ctrl+Win+1/2/3 are reserved as potential prefixes; releasing without Z does nothing. Other editing keys or mouse actions during an active chord cancel it. A new chord while correction is busy is not queued.

Windows cannot retroactively suppress a Z or digit already delivered before the modifiers were held. Use the modifier-first sequence. Release the complete chord between operations. Existing protected/elevated/custom-field restrictions still apply.

## C. Professionalism and quality

All modes use one shared API call and the same local validation. Prompts explicitly prohibit invented facts, added commitments/apologies, unsupported certainty, extra paragraphs and commentary. Local checks retain numbers, URLs, emojis and line layout, reject empty/truncated/disproportionate output, wrappers, commentary and added Markdown. Professional modes allow bounded wording expansion; grammar retains the original stricter length limits. These checks cannot prove semantic equivalence or identify every changed name; meaning preservation also depends on the model.

Four actual GPT-6 Luna results for `hey can u send me the files when ur free`:

| Mode | Actual response |
| --- | --- |
| Grammar | Hey, can you send me the files when you're free? |
| Level 1 | Hi, could you please send me the files when you're free? |
| Level 2 | Hello, could you please send me the files at your convenience? |
| Level 3 | Hello, I would appreciate it if you could forward the files at your earliest convenience. |

The dedicated 48-example suite covers twelve examples per mode: casual text, shorthand, already-correct text, long paragraphs, multiline layout, emojis, names, technical terms, numbers/dates, apologies, emotional nuance, academic requests and business messages. Mocked responses verify mode routing, one-request behavior and validation contracts; they are **not** evidence of live model quality across all 48 inputs. The four-response live evaluation above is small and controlled. See `live-mode-evaluation-round5.json`.

## D. Measured performance

All local timers use `perf_counter_ns`; values below are milliseconds. Function timings are inclusive and must not be summed. API timing includes SDK serialization, connection/transport, provider processing and response parsing; separate TCP/TLS/server timings were not exposed or inferred.

### Interleaved live API comparison

Same model, three identical non-sensitive grammar inputs, each repeated twice per version. Old/new order alternates; clients persist. Six requests per version are enough for a small comparison, **not reliable population p90/p95 estimates**.

| Measure | Baseline median / p90 / p95 | Round 5 median / p90 / p95 |
| --- | --- | --- |
| API request/response | 1394.890 / 2714.431 / 2978.640 | 1065.822 / 1470.559 / 1624.216 |
| Complete grammar engine call | 1395.077 / 2714.867 / 2979.092 | 1066.190 / 1470.916 / 1624.635 |
| Input tokens for the three inputs | 460 / 459 / 462 | 283 / 282 / 285 |

Median engine latency was **23.6% lower in this interleaved sample**. Input tokens fell about **38.4%** with identical output token counts. The change plausibly reduces provider work and consistently lowers input cost; this experiment does not isolate causation or guarantee a 24% speedup on other networks or texts.

The initial separate runs illustrate the variance: baseline live API median 1785.846 ms (n=3), first after-run 3597.711 ms (n=3), followed by the interleaved results above. A visible Notepad Level 1 request took 15145 ms. No sub-second guarantee is made. Raw results: `round5-baseline/benchmark.json`, `benchmark-round5.json`, `comparison-live-round5.json`.

### Local processing

Paired, interleaved native Edit transactions use the same hidden real Win32 control and mocked AI, 200 per version. This isolates local transaction work from network behavior; it does not represent browser UIA latency.

| Measure | Baseline median / p90 / p95 | Round 5 median / p90 / p95 |
| --- | --- | --- |
| Native capture → verified replacement, mocked AI | 1.604 / 2.487 / 2.595 | 1.628 / 2.397 / 2.562 |
| API preparation to an immediate mock response function (n=1000) | 0.007 / 0.019 / 0.022 | 0.026 / 0.059 / 0.067 |
| Entire engine with immediate mock response (n=1000) | 0.074 / 0.141 / 0.160 | 0.086 / 0.205 / 0.222 |

There is **no demonstrated local processing speedup**. The added safety, mode routing and instrumentation cost hundredths of a millisecond in these fixtures. See `comparison-local-round5.json`.

The original 100-transaction fixture measured capture 0.445 ms median (p90 0.771, p95 0.889), target verification 0.188 ms (0.435, 0.487), and replacement 0.318 ms (0.587, 0.647). The later separate run occurred under different host load and was slower; the paired comparison is preferable. Native fixture clipboard stages are not used. A real source Notepad transaction measured commit dispatch 0.810 ms, chord hold plus dispatch 5.655 ms, capture 139.364 ms, request preparation 0.116 ms, output validation 0.280 ms, target verification 50.915 ms and replacement 10.171 ms. First working-feedback rendering took 88.308 ms on the UI thread, independently of the hook thread; success feedback took 23.468 ms. These are single observations, not distributions. Baseline physical recognition/UI-render distributions were not captured.

### Clipboard fixture

Guarded, real interactive clipboard fixture with simulated editor shortcut dispatch. Includes HTML, RTF, DIB image, file drop, Unicode/multiline and arbitrary registered data, plus an independent clipboard writer.

| Measure | Baseline median / p90 / p95 | Round 5 median / p90 / p95 |
| --- | --- | --- |
| Snapshot (n=9) | 1.474 / 5.441 / 6.252 | 2.055 / 3.150 / 4.233 |
| Restore (n=8) | 0.775 / 5005.652 / 5007.596 | 1.510 / 5006.489 / 5008.326 |
| Copy, including cross-process case (n=4) | 20.329 / 3517.101 / 4265.912 | 7.766 / 3513.403 / 4264.596 |
| Paste plus restoration (n=4) | 196.127 / 199.553 / 200.058 | 197.665 / 201.071 / 201.686 |

Small counts and occasional approximately five-second Windows clipboard-observer stalls dominate tails in both versions. The clipboard algorithm was not changed; differences are not attributed to an optimization. The 180 ms asynchronous-paste settle protection remains. See the two clipboard benchmark JSON files.

### Executable resources and startup

Two observed launches per version, from outside the project directory, isolated temporary preferences. Includes one-file extraction, Windows/antivirus/cache behavior and readiness polling (150 ms resolution).

| Measure | Baseline cycles 1 / 2 | Final EXE cycles 1 / 2 |
| --- | --- | --- |
| Startup until listening | 17777 / 9828 ms | 6546 / 6349 ms |
| Combined working set, launcher plus runtime | 90.41 / 90.73 MiB | 90.80 / 90.50 MiB |
| Idle CPU, percent of one core over ~1.5 s | 0.000 / 0.000 | 0.000 / 0.000 |

Startup was faster in these observations, but two samples with different cache/host conditions do not establish a repeatable startup improvement. Zero means no measurable CPU-time increment during the short sample, not a claim of zero lifetime CPU consumption. The two PyInstaller processes are a launcher and one listener runtime, not two listening app instances.

### API cost and design decisions

Twenty-two token-measured generation requests used 7899 input and 299 output tokens, no cached tokens: approximately **US$0.0009394** at the checked standard GPT-6 Luna rates. The four-mode evaluation alone was about **US$0.0001561**. Three additional live Notepad source corrections ran; their usage was not captured, so the complete billed total is not known. Model metadata checks do not generate text. These estimates exclude project-specific billing adjustments; consult the API invoice for actual charges.

The existing persistent client, pooling, zero retries and Luna `reasoning.effort=none` configuration were already present and remain. No model change, classifier, additional verification request or multi-call rewriting was introduced. Streaming was considered and omitted: the editor must receive a complete validated result, and partial arrival does not by itself establish faster complete replacement. Clipboard settle waits, COM safety and selection checks were retained.

Official references checked during implementation: [GPT-6 Luna model, supported effort and standard token prices](https://developers.openai.com/api/docs/models/gpt-6-luna), [latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization).

## E. Executed checks and their limits

| Check | Round 5 result |
| --- | --- |
| Original automated baseline | 69 tests passed before changes. |
| Final automated suite | 83 tests passed. Includes 48 mocked examples, errors/refusals/timeouts, fact/layout/emoji/URL checks, capture/verify/replacement regression cases, mode routing, input changes, overlay rendering and clipboard ownership protections. |
| Chord state machine | 588 press/release sequences, each repeated twice with held-key repeat; both modifier orders, digit-before/after-Z, top row/numpad, all release orders. Additional cases cover cancellation, overlap/first-digit selection, NumLock-off navigation distinctions, suppressed events, busy listener and duplicate WM_HOTKEY messages. |
| Real Win32 Edit fixture | Three corrections passed, preserving Unicode/emoji, multiline selection boundaries, surrounding text and undo without clipboard access. |
| Real input hooks | Three registration/shutdown cycles passed. Automated callback tests cover editing events, pointer movement, own injection tags and consumption of reserved digits/Z. |
| Real clipboard fixture | Passed before/after comparison: three normal copy/paste/restore cycles, independent-process copy, and preservation of a newer clipboard write during paste cleanup. Original interactive clipboard was backed up and restored. |
| Cached OLE | Eligibility and live-reference rejection tests passed. Actual cached-OLE image fixture was not rerun in this round; the clipboard algorithm is unchanged. Do not treat the prior report's manual results as new Round 5 executions. |
| Visible Notepad, source listener | Grammar, Level 1 and Level 2 passed using the exact requested chords with live GPT-6 Luna. Visible output and Ctrl+Z restoration were checked. Each operation logged one request. Level 3 received live API and automated routing coverage, but no visible Notepad shortcut check. |
| Live all-mode engine quality | Four actual public-example responses passed local validation and showed the requested progression; outputs are recorded above. |
| Browser fixture | A standard input was prepared in Edge. Browser DOM key injection did not reach the Windows global hook, so no correction was claimed. Computer Use was then stopped by the physical Escape key; further visual tests stopped. |
| Final EXE archive | Passed: x64 Windows GUI subsystem, no console, assets/font license present, all original asset bytes preserved, no bundled preferences or `.env`, and every application module checked against current source. |
| Final EXE local/model setup | Passed from the executable: input hooks, UIA, SDK, verified TLS, font rendering, shortcut registration and actual model metadata access. |
| Final EXE lifecycle | Passed: two starts/stops, tray registration on each, duplicate listener rejected by mutex, clean exit and hotkey released after shutdown. |
| Startup shortcut | Passed with a temporary link outside Windows Startup: EXE target, arguments, working directory and removal. Windows sign-in was not tested. |

Real Chrome, ChatGPT composer, WhatsApp Web/Desktop, per-field packaged correction/undo, focus switches during a live request, and packaged visual transitions require the manual checks below. Their current Round 5 behavior is not represented as passed. Browser automation initially blocked a file URL; a loopback-only HTTP endpoint serving solely the public fixture was permitted instead. The temporary helper and mock listener were stopped after the interrupted visual testing.

## F. Executable

**`dist/LunaGrammar.exe`** — 28,906,341 bytes, Windows x64 GUI one-file application.

SHA-256: **`658DE900588C82BF9C8D6FB72D661E054FC93F0C9BE8387F506CFC219A181082`**.

The existing PyInstaller spec and pinned build environment were used. Run `build.ps1` to reproduce; `tests/inspect_release.py` verifies source freshness and original asset preservation. Profile preferences and `OPENAI_API_KEY` remain external. No credential was embedded or changed. The original executable remains in `round5-baseline/LunaGrammar.exe` for rollback.

After verification, the final executable was started in normal mode. Its log confirmed listening at 00:32:01 on 13 November 2026; only the final binary's launcher/runtime processes were present.

## G. Remaining manual checks

Use unsent scratch text, preserve surrounding markers, and verify Ctrl+Z. Do not send test messages. Quit any old listener before opening the new EXE; the mutex also rejects duplicates.

1. In Notepad, Chrome input/textarea/contenteditable, ChatGPT, WhatsApp Web and WhatsApp Desktop, select `hey i cant come today` between `Before [` and `] After`. Try all four shortcuts from the same original text and confirm increasing professionalism. Test top-row and numpad digits, both Z/digit orders after the modifiers, held keys, release orders, and repeated use after a full app restart. No number should appear in the editor.
2. Repeat with multiline/emoji/number/date text. Confirm exact surrounding text, paragraph layout, emojis and numeric details, then undo each edit.
3. Repeat with a supported rich/image clipboard item. Confirm the clipboard is preserved; an active owner-dependent OLE item may deliberately cause a safe refusal. Test a newer clipboard write while the request is pending and confirm it survives cleanup.
4. Switch apps or change the selection while the request is pending: the old target must not be overwritten. Try an empty selection, protected field and API failure; no replacement should occur and feedback should dismiss.
5. Verify the lime pill, logo, Poppins, waveform, mode labels, success/error dismissal, tray pause/resume/settings, clean exit and Windows sign-in startup.

The existing conservative field restrictions remain documented in `README.md`. The implementation improves measured prompt/network performance while preserving the Windows mechanisms; it does not guarantee every model output or every application-specific provider behavior.
