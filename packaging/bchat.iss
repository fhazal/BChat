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
; tell Windows icons changed at the end, so a new logo shows without a stale icon cache
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[InstallDelete]
; program files only (settings and logs live in AppData): clears icons and libraries an older build left behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\BChat\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\BChat"; Filename: "{app}\BChat.exe"; IconFilename: "{app}\BChat.exe"
Name: "{autodesktop}\BChat"; Filename: "{app}\BChat.exe"; IconFilename: "{app}\BChat.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BChat.exe"; Description: "Start BChat"; Flags: nowait postinstall skipifsilent
; BChat's Install Now runs this installer quietly with /RESTART: start BChat again afterwards
Filename: "{app}\BChat.exe"; Flags: nowait; Check: RestartAfterUpdate

[Code]
function RestartAfterUpdate: Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), '/RESTART') = 0 then
      Result := True;
end;
