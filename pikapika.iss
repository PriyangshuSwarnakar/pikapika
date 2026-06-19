; Pikapika v1.2 — Inno Setup installer script
; ---------------------------------------------
; This script packages the PyInstaller-built Pikapika.exe into a proper
; Windows installer with a Start Menu shortcut, optional Desktop shortcut,
; and a clean uninstaller.
;
; BEFORE COMPILING THIS SCRIPT:
;   1. Run PyInstaller first to produce dist\Pikapika\Pikapika.exe
;      (see the BUILD_INSTRUCTIONS.txt file for the exact command)
;   2. Make sure pikapika.ico is in the same folder as this .iss file
;   3. Update the SourceDir path below to match where your dist folder is

#define MyAppName "Pikapika"
#define MyAppVersion "1.2"
#define MyAppPublisher "Priyangshu Swarnakar"
#define MyAppExeName "Pikapika.exe"

[Setup]
AppId={{8F3A2B1C-4D5E-4F6A-9B7C-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=Pikapika_Setup_v{#MyAppVersion}
SetupIconFile=pikapika.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; This pulls in EVERYTHING PyInstaller produced (the exe plus all its
; dependency files) from the dist\Pikapika folder. Adjust the source
; path if your dist folder ends up somewhere else.
Source: "dist\Pikapika\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The shortcuts below reference {app}\pikapika.ico, so the icon file
; itself must also be copied into the install folder — otherwise the
; shortcuts fall back to a generic blank-page icon.
Source: "pikapika.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pikapika.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pikapika.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
