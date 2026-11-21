# Changelog — Luna Grammar rebuild (2026-11-21)

This rebuild fixes the five known gaps from the function report, the two data-integrity risks found in audit, and the UI issues found in review. It was developed and tested on a Linux VM; **no Windows live testing was done** — see [WINDOWS_TEST_CHECKLIST.md](WINDOWS_TEST_CHECKLIST.md) for the steps to verify it on a real laptop. The previous release's reports (ROUND5-REPORT.md, TEST-REPORT.md, UI-FIX-REPORT.md, KEY-RELEASE-FIX.md) describe the old build and are kept for history.

## Fixed — the five known gaps

1. **Bare Ctrl+Win+Z always used mode 0; Settings default-mode was ignored.**
   Root cause: `ShortcutState` emitted `0` for "no digit", and the listener's `isinstance(level, int)` branch consumed `0` as an explicit mode 0 before the `default_mode` fallback could run. Fix: a bare chord now emits `None`, and the listener applies `settings.default_mode` (and per-app modes, below). An explicit Ctrl+Win+Z+0 still means mode 0.
2. **Bulletize mode almost always failed validation.**
   Root cause: `validate()` rejected any introduced list marker (`- `, `* `, `1. `) as "introduced Markdown" and required the corrected line count to equal the original — while mode 4's own instructions tell the model to emit bullets and group/synthesize. Fix: validation is now mode-aware — Bulletize allows introduced bullet markers, changed line counts, and summarisation shortening (with guards: at least one bullet, no empty bullets, no other Markdown, a 20% content floor, a line-count cap). Other modes still reject line-layout changes.
3. **Undo could restore the original text at the wrong location.**
   Root cause: the undo path popped the record before verifying anything, and never compared the live selection with the saved rewrite. Fix: the record is only peeked first; the live selection is captured and compared with `record.refined_text`; only after verification is the record popped and the original restored. If the text differs or capture fails, the pill says "Couldn't verify the corrected text", the record is kept, and nothing is overwritten. The undo record is also now created **after** a successful replacement, not before — a failed replacement no longer leaves a phantom undo record.
4. **Custom prompt, temperature, and sound were saved but never applied.**
   Root cause: `GrammarEngine.configure()` never read them, and no sound code existed anywhere. Fix: the custom prompt is appended to the request instructions; temperature is clamped 0.0–2.0 and sent for `gpt-4o` / `gpt-4o-mini` / `gpt-3.5-turbo` (while `gpt-6-luna` keeps `temperature: 0` + `reasoning.effort: "none"`); unknown/custom models get neither option, so the API cannot reject the request. The Settings toggle is renamed "Play a sound when a correction finishes" and now really plays the Windows completion sound (`winsound.MessageBeep`) on success/error/undo — the waveform animation stays governed by the motion setting, as before.
5. **Settings ran in a separate process; its cache counters / Clear Cache never reached the listener; cache keys omitted model + shorthand.**
   Root cause: the Settings process cleared its own always-empty cache, and the cache key was `(mode, text)` only. Fix: cache keys now include model, shorthand setting, temperature, and a hash of the custom prompt; `Clear Cache` in Settings now also posts `WM_CLEAR_CACHE` to the listener window, which clears the live engine cache on its message thread and reports whether the listener was reached.

## Fixed — audit findings

- **Clipboard data loss (P0):** `snapshot()` failing on an un-duplicable format used to fall back silently to a partial backup, destroying the rest of the user's clipboard. Now `clipboard_strict_preservation` (default on) fails closed with a clear refusal; the old best-effort behaviour is opt-in.
- **Double-paste race (P1):** after a 0.5 s render timeout, the paste fallback sent a second Ctrl+V that could duplicate text if the first read landed late. It now checks whether the first read already got the text before sending a second paste.
- **Model fallback was dead code (P1):** `MODEL_FALLBACKS` / `correct_with_fallback()` existed but nothing called them. The live path now passes `fallback_models=True`, so an unavailable primary model falls back instead of failing.
- **Validation rejections collapsed to one label (P1):** every rejection showed "Invalid correction". The specific reason is now preserved (e.g. "The correction changed a URL.") with code `api.validation_failed`.
- **`check_overlay()` inflated mode count (P1):** it iterated all ~30 mode aliases; it now iterates the 6 canonical modes.
- **Cache singleton races (P2):** double-checked locking on both singleton paths.
- **Diagnostics double-counting (P2):** the API path recorded tokens/chars twice (once via `record_tokens`/`record_characters`, once via `record_throughput`); it now records duration only there.
- **`executable()` process-list snapshot per call (P2):** now cached for 5 s per PID.
- **Settings `save()` startup gate discarded all changes (P2):** settings are now saved first; a startup failure only affects startup and says so.
- **`max_output_tokens` uncapped (P2):** capped at 8192.
- **`Settings.__post_init__` model inconsistency (P2):** when both `model` and `active_model` are set to different non-default values, `active_model` wins (it is what the engine reads).
- **`--check` ordering:** `--check` now runs before `load_settings()`, so a corrupt `settings.json` no longer aborts the diagnostic.
- **`build.ps1`:** now runs the test suite before PyInstaller; the build fails if tests fail.

## New features

- **Per-app default mode** (`per_app_modes`): `{"outlook.exe": 2}` makes a bare Ctrl+Win+Z use Executive Concise in Outlook. Editable in Settings → Exclusions → Per-App Default Mode. Explicit digits always win.
- **Copy-only safe mode** (`copy_only`): stages the correction on the clipboard for a manual Ctrl+V instead of pasting. Settings → General → Safety & Review.
- **Review before apply** (`review_before_apply`, off by default): the pill holds the corrected text with **Apply / Discard** buttons for up to 30 s; Apply pastes, Discard drops it with no undo record, and a timeout / focus change / overlay failure applies it — a correction is never stranded. Settings → General → Safety & Review.
- **Long-text chunking:** selections over the limit are corrected paragraph by paragraph (blank-line splits, separators preserved) instead of failing outright. A single paragraph over the limit keeps a clear error.
- **Offline fallback (Grammar mode only, clearly labelled):** when the API is unreachable (connection error / timeout) and the text has obvious typos or unambiguous contractions, Luna fixes them locally and shows **"Fixed offline"**. Other modes still raise the API error; offline results are never cached.
- **Elevation detection:** a target running as administrator is detected by integrity level and explained (`capture.elevated_target`) instead of failing silently.
- **Diagnostics panel:** the last failure (stage, code, app, field type, reason — metadata only, never text) is persisted to `%LOCALAPPDATA%\LunaGrammar\last-failure.json` and shown in Settings → Cache & Diagnostics.
- **Tray live status:** the tooltip now shows `Refining… · Level 2` / `Refined · +3 words` / `Paused` instead of a static label, and the tray falls back to the pill's drawn mark if `luna.ico` cannot load.

## UI changes

- **Pill:** the `⚡ Cached` badge used an emoji glyph Poppins does not contain — it is now a hand-drawn vector bolt. Long result labels are ellipsized and the capsule width is clamped (420 px, 560 px for review pills) so the close button can never be pushed off. The close hit-zone is now a full 44×44 px at 96 DPI (the drawn × stays small) with a hand cursor on hover.
- **Settings:** DPI-aware geometry (scaled by `winfo_fpixels("1i")/96`) and centred on the primary display; Ctrl+S saves; the sound toggle is honest (see above); new Safety & Review section and per-app mode editor; diagnostics shows the last failure from the listener. The cheatsheet description floor is 9 pt.
- **Palette:** the single lime is `#BFF549` (code) — the `#B4F044` in the old design-concept prompt in `design/README.md` was a copy error and has been corrected to `#BFF549`.

## Deliberately not done (follow-ups)

- Shared `ui_theme.py` token module + a "Follow Windows" appearance (registry `AppsUseLightTheme` + `WM_SETTINGCHANGE`); scrollable tab frames; full `ttk.Style` widget set; dirty-tracking with a "● Unsaved changes" indicator; a Test Connection spinner; a progress cue for long requests; tray balloon notifications; a recent-corrections history UI; DPAPI storage for the API key (the key in `HKCU\Environment` is the standard Windows user-env-var approach already documented in the README); `uiAccess="true"` packaging (needs a code-signing certificate + `%ProgramFiles%` install).
- Recent-corrections history and a Tk diff-preview window were reviewed and not built: the pill-based Apply/Discard review above covers the same need without a second window.

## Tests

- **185 tests pass, 69 skipped (Windows-only), 0 failures** — Linux VM, `python -m unittest discover -s tests`, proxy variables unset. The suite grew from 167 (after the first fixes) with 12 review/UI tests and 6 audit-fix tests.
- New coverage: default-mode mapping, bulletize validation, undo safety (wrong-location must not restore), cache keys including model/shorthand/temperature/prompt, prompt/temperature wiring, layered-fallback selection logic (mocked), clipboard preservation, long-text chunking, error-path diagnostics, review Apply/Discard/timeout/copy-only, pill review state and width clamp, vector bolt, sound no-op off Windows, phantom-undo ordering, model fallback in the live path, validation-error specificity, singleton locking, six-mode overlay count, diagnostics single-counting.
- Windows-only tests (69) are skipped on Linux because they need real Win32/UIA; they are not evidence of live behaviour.
