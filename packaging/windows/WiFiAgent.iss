#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#ifndef BuildRoot
  #define BuildRoot "..\..\build\windows"
#endif
#ifndef OutputDir
  #define OutputDir BuildRoot + "\installer"
#endif

#define AppName "WiFi Agent"
#define AppPublisher "Akshaj Tiwari"
#define AppUrl "https://github.com/akshajtiwari/Wifi-Agent"
#define AppExeName "WiFiAgent.exe"

[Setup]
AppId={{ed7dcd9e-1974-51c4-861d-a7ea7e62cb45}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=WiFiAgent-{#AppVersion}-Windows-x64-Setup
SetupIconFile={#BuildRoot}\assets\wifi-agent.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#BuildRoot}\dist\WiFiAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Parameters: "setup"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Parameters: "setup"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Parameters: "setup"; Description: "Open {#AppName} settings"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#AppExeName}"; Parameters: "uninstall"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated skipifdoesntexist

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { Stop an existing scheduled instance before replacing its executable. }
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN WiFiAgent', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
