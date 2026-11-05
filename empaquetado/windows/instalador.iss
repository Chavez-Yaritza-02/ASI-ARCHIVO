#define AppVersion "0.7.0"
[Setup]
AppId={{B55FC21D-6755-44C2-8F62-5271859D0070}
AppName=ASI-ARCHIVO
AppVersion={#AppVersion}
AppPublisher=Jefatura de Electromecánica
DefaultDirName={localappdata}\Programs\ASI-ARCHIVO
DefaultGroupName=ASI-ARCHIVO
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=..\..\dist\instalador
OutputBaseFilename=ASI-ARCHIVO-{#AppVersion}-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ASI-ARCHIVO.exe
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\..\dist\ASI-ARCHIVO\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ASI-ARCHIVO"; Filename: "{app}\ASI-ARCHIVO.exe"
Name: "{group}\Configurar conexión"; Filename: "{app}\ASI-ARCHIVO.exe"; Parameters: "--configurar"

[Run]
Filename: "{app}\ASI-ARCHIVO.exe"; Description: "Abrir ASI-ARCHIVO"; Flags: nowait postinstall skipifsilent
