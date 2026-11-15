; Build with ISCC /DAppVersion=0.7.0b1 scripts/installer.iss
#ifndef AppVersion
  #error AppVersion must be supplied by the release builder
#endif
[Setup]
AppId={{B933267D-2826-4A11-B581-B074E27452C8}
AppName=Ren'Py Arabic Translator
AppVersion={#AppVersion}
AppVerName=Ren'Py Arabic Translator {#AppVersion} Beta
DefaultDirName={localappdata}\Programs\RenPyArabicTranslator
DefaultGroupName=RenPyArabicTranslator
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=RAT-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\RAT.exe
CloseApplications=yes
SetupLogging=no

[Files]
Source: "..\dist\RAT.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\licenses\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\RELEASE_NOTICE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\installation.md"; DestDir: "{app}"; DestName: "INSTALLATION.md"; Flags: ignoreversion

[Icons]
Name: "{group}\Ren'Py Arabic Translator"; Filename: "{app}\RAT.exe"

; No post-install auto-launch, network actions, user-data deletes or game changes.
