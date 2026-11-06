; BChat installer. Build with: ISCC /DMyVersion=0.1.0-TEST1 packaging\bchat.iss
#ifndef MyVersion
  #define MyVersion "0.1.0"
#endif

[Setup]
AppId={{7C1F3E52-9A44-4B6E-8D21-6B0C5A7E19D4}
AppName=BChat
AppVersion={#MyVersion}
AppPublisher=BajuBesi Labs
DefaultDirName={autopf}\BChat
DefaultGroupName=BChat
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=BChat-{#MyVersion}-setup
SetupIconFile=..\bchat\assets\bchat.ico
WizardImageFile=wizard-side.bmp,wizard-side-2x.bmp
WizardSmallImageFile=wizard-small.bmp,wizard-small-2x.bmp
UninstallDisplayIcon={app}\BChat.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\BChat\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\BChat"; Filename: "{app}\BChat.exe"
Name: "{autodesktop}\BChat"; Filename: "{app}\BChat.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BChat.exe"; Description: "Start BChat"; Flags: nowait postinstall skipifsilent
