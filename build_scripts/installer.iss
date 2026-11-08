[Setup]
AppName=dxf2PlasmaC
AppVersion=1.0.0
DefaultDirName={autopf}\dxf2PlasmaC
DefaultGroupName=dxf2PlasmaC
OutputDir=dist
OutputBaseFilename=dxf2PlasmaC-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\dxf2PlasmaC\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\dxf2PlasmaC"; Filename: "{app}\dxf2PlasmaC.exe"
Name: "{autodesktop}\dxf2PlasmaC"; Filename: "{app}\dxf2PlasmaC.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
