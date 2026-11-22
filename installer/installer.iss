; LunaGrammar — Inno Setup installer
; Per-user install, no admin / no UAC prompt.
; Installs the one-file PyInstaller build dist\LunaGrammar.exe into %LOCALAPPDATA%\LunaGrammar.
; Version is passed in as /DAppVersion=... by the GitHub Actions workflow
; (it reads the VERSION file at the repo root). Build by hand on Windows:
;   1. .\build.ps1            (tests first, then PyInstaller -> dist\LunaGrammar.exe)
;   2. iscc /DAppVersion=1.1.0 installer\installer.iss
;      (Inno Setup 6; on GitHub Actions the workflow installs it via Chocolatey)
; Output: installer\Output\LunaGrammar-Setup-<version>.exe
;
; Notes:
; - Per-user is the right default. Per-machine (%ProgramFiles%) is required
;   ONLY if uiAccess="true" is ever wanted, and that also needs a trusted
;   code-signing certificate — a separate, costed decision, not this installer.
; - Do NOT put an API key in the installer. First run asks for it in Settings
;   (or reads OPENAI_API_KEY); the key is stored via DPAPI, not plaintext.
; - Ship unsigned for now; document the SmartScreen "More info -> Run anyway"
;   step in the README. A self-signed cert behaves like no signature.
; - Uninstall removes program files but LEAVES user settings/data in
;   %LOCALAPPDATA%\LunaGrammar unless the user deletes them manually.

#define AppName "LunaGrammar"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppPublisher "Zaahid Zaman"
#define AppURL "https://github.com/Zaahidhacker/LunarGrammar"
#define AppExeName "LunaGrammar.exe"

[Setup]
AppId={{3F7A1C2E-9B4D-4A6E-8C1F-5D2E7A9B0C4D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=LunaGrammar-Setup-{#AppVersion}
SetupIconFile=..\assets\luna.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start LunaGrammar when I sign in to Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\WINDOWS_TEST_CHECKLIST.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LunaGrammar"; ValueData: """{app}\{#AppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
Type: files; Name: "{app}\{#AppExeName}"
