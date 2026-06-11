#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

#ifndef SourceDir
#define SourceDir "..\dist"
#endif

#ifndef RepoDir
#define RepoDir ".."
#endif

[Setup]
AppId={{D75C49F3-AF13-4F1E-AC11-6FA662A61D10}
AppName=CardProof
AppVersion={#AppVersion}
AppPublisher=CardProof
DefaultDirName={localappdata}\Programs\CardProof
DefaultGroupName=CardProof
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=CardProof-Setup-v{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\CardProof.exe

[Files]
Source: "{#SourceDir}\CardProof.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoDir}\app_config.example.json"; DestDir: "{app}"; DestName: "app_config.example.json"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\CardProof"; Filename: "{app}\CardProof.exe"
Name: "{autodesktop}\CardProof"; Filename: "{app}\CardProof.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\CardProof.exe"; Description: "Launch CardProof"; Flags: nowait postinstall skipifsilent
