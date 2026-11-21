param([switch] $SkipInstall)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python 3.12 build environment.' }
}
& $buildPython -c "import sys, sysconfig; sys.exit(sys.version_info[:2] != (3, 12) or sysconfig.get_platform() != 'win-amd64')"
if ($LASTEXITCODE -ne 0) { throw 'The release build requires Windows x64 Python 3.12.' }
if (-not $SkipInstall) {
    & $buildPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $buildPython -m PyInstaller --clean --noconfirm LunaGrammar.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
Write-Output (Join-Path $PSScriptRoot 'dist\LunaGrammar.exe')
