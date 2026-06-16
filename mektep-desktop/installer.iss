; Inno Setup script for Mektep Desktop
; Version is passed at build time: ISCC /DAppVersion=1.2.2 installer.iss

#ifndef AppVersion
  #define AppVersion "1.2.1"
#endif

#define AppName "Mektep Desktop"
#define AppExe "Mektep Desktop.exe"
#define AppPublisher "Mektep"

[Setup]
; AppId must stay the same across all releases for in-place upgrades
AppId={{8F3A9C2E-1234-4ABC-9DEF-MEKTEP000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Mektep Desktop
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=MektepDesktopSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=yes
WizardStyle=modern
SetupIconFile=resources\icons\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "dist\Mektep Desktop\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent
