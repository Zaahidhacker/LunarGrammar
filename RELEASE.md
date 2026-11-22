# Getting LunaGrammar — installer

## How to install (the supported way)

1. Go to the **Releases** page of `Zaahidhacker/LunarGrammar` on GitHub.
2. Download `LunaGrammar-Setup-<version>.exe` from the latest release.
3. Run it. It installs per-user to `%LOCALAPPDATA%\LunaGrammar` — **no admin
   prompt, no manual configuration**.
4. On first run, LunaGrammar asks for your OpenAI API key once, in Settings
   (or it reads `OPENAI_API_KEY` if that is already set). The key is stored
   with Windows DPAPI, never in the installer or in the repo.
5. Optional: tick "Start LunaGrammar when I sign in" during install, or turn
   it on later in Settings.

## SmartScreen

The installer is currently unsigned, so Windows SmartScreen may show
"Windows protected your PC". That is expected for a new, unsigned publisher:
click **More info → Run anyway**. A code-signing certificate (and the
`uiAccess` packaging that would also need it) is a separate, costed decision.

## How a release is made (for the maintainer)

```text
.\build.ps1            # runs tests first, then builds dist\LunaGrammar.exe
git tag v1.1.0
git push origin v1.1.0
```

Tagging triggers the GitHub Actions workflow (`.github/workflows/build-windows.yml`):
`windows-latest` runner → Python 3.12 → install `requirements-build.txt` →
run the test suite → PyInstaller build → Inno Setup compile → the installer
and the exe are attached to the GitHub Release as assets, with SHA-256 hashes
in the workflow log.

## What is NOT in the repo

The `.exe` and the installer are **not** committed to git. They are release
assets only. The text-only GitHub snapshot push cannot carry binaries, and
binaries in git would bloat the repo for every clone.

## If there is no Release yet

The installer files (`installer/installer.iss`, `.github/workflows/build-windows.yml`,
`VERSION`) are in the repo; until a tag is pushed, build locally on Windows
with `.\build.ps1` and then `iscc /DAppVersion=<version> installer\installer.iss`.
