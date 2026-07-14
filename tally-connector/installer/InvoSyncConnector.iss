; InvoSync Connector — Inno Setup Installer
; Download Inno Setup from https://jrsoftware.org/isdl.php

[Setup]
AppName=InvoSync Connector
AppVersion=1.0.0
AppPublisher=InvoSync
DefaultDirName={autopf}\InvoSync Connector
DefaultGroupName=InvoSync
OutputBaseFilename=InvoSyncConnectorSetup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\InvoSyncTallyConnector.exe
PrivilegesRequired=admin

[Files]
Source: "..\InvoSyncTallyConnector\bin\Release\net10.0-windows\win-x64\publish\*"; \
  DestDir: "{app}"; Flags: ignoreversion recursesubdirs; \
  Check: Is64BitInstallMode
Source: "..\InvoSyncTallyConnector\bin\Release\net10.0-windows\win-x86\publish\*"; \
  DestDir: "{app}"; Flags: ignoreversion recursesubdirs; \
  Check: not Is64BitInstallMode

[Icons]
Name: "{group}\InvoSync Connector"; \
  Filename: "{app}\InvoSyncTallyConnector.exe"
Name: "{commondesktop}\InvoSync Connector"; \
  Filename: "{app}\InvoSyncTallyConnector.exe"; \
  Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\InvoSyncTallyConnector.exe"; \
  Description: "Launch InvoSync Connector"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\InvoSyncTallyConnector.exe"; Parameters: "--uninstall"
