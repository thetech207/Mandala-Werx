; Inno Setup script for Mandala-Werx (Windows)
; Build: packaging\build-windows.ps1 <version>
;   or:  iscc packaging\mandalawerx.iss /DMyAppVersion=1.0.0

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{7A4C2E91-5B3D-4E8F-9A1C-2D6F8B3E5A47}
AppName=Mandala-Werx
AppVersion={#MyAppVersion}
AppPublisher=thetech207
AppPublisherURL=https://github.com/thetech207/Mandala-Werx
AppSupportURL=https://github.com/thetech207/Mandala-Werx/issues
DefaultDirName={autopf}\Mandala-Werx
DefaultGroupName=Mandala-Werx
OutputDir=..\dist
OutputBaseFilename=mandalawerx_{#MyAppVersion}_win64_setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
SetupIconFile=..\Images\mandalawerx-icon.ico
UninstallDisplayIcon={app}\mandalawerx.exe
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\mandalawerx\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Mandala-Werx"; Filename: "{app}\mandalawerx.exe"
Name: "{autodesktop}\Mandala-Werx"; Filename: "{app}\mandalawerx.exe"; Tasks: desktopicon

[Registry]
; .mwpx file association (per-user, merges into HKCR view)
Root: HKCU; Subkey: "Software\Classes\.mwpx"; ValueType: string; ValueData: "MandalaWerx.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\MandalaWerx.Project"; ValueType: string; ValueData: "Mandala-Werx Project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\MandalaWerx.Project\DefaultIcon"; ValueType: string; ValueData: "{app}\mandalawerx.exe,0"
Root: HKCU; Subkey: "Software\Classes\MandalaWerx.Project\shell\open\command"; ValueType: string; ValueData: """{app}\mandalawerx.exe"" ""%1"""

[Run]
Filename: "{app}\mandalawerx.exe"; Description: "Launch Mandala-Werx"; Flags: nowait postinstall skipifsilent
