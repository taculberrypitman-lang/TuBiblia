#define MyAppVersion "0.1.0"

[Setup]
AppId={{A6F64443-B7AA-4D45-BD12-81F5BCA31668}
AppName=TuBiblia
AppVersion={#MyAppVersion}
AppPublisher=TuBiblia
DefaultDirName={autopf}\TuBiblia
DefaultGroupName=TuBiblia
UninstallDisplayIcon={app}\TuBiblia.exe
SetupIconFile=..\..\build\windows\tubiblia.ico
OutputDir=..\..\dist
OutputBaseFilename=TuBiblia-Setup-x64
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "..\..\build\windows\dist\TuBiblia\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TuBiblia"; Filename: "{app}\TuBiblia.exe"
Name: "{autodesktop}\TuBiblia"; Filename: "{app}\TuBiblia.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TuBiblia.exe"; Description: "Abrir TuBiblia"; Flags: postinstall nowait skipifsilent
