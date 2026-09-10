#ifndef MyAppVersion
  #define MyAppVersion "dev"
#endif

#define MyAppName "BWIH Dispatch"
#define MyAppExeName "BWIH Dispatch.exe"

[Setup]
AppId={{B4B12C2B-F0D9-4C40-91B2-B8F7446C567A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=BWIH
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=BWIH-Dispatch-Setup-Windows-x64
SetupIconFile=assets\bwih-dispatch.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\BWIH Dispatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "打开 BWIH 调度系统"; Flags: nowait postinstall skipifsilent
