# InvoSync Tally Connector — Client Deployment Guide

## Prerequisites (Client PC)
- Windows 10/11
- Tally Prime (any version) running on the same PC
- Tally Connectivity enabled: F1 → Settings → Connectivity → Port **9000**
- .NET 10 Runtime (if using framework-dependent build)
- OR nothing needed (if using self-contained .exe)

## Installation Steps

### 1. Download the Connector
Give the client one of these URLs (depends on how you host):

**Option A — GitHub Releases (recommended):**
```
https://github.com/Teja905/invosync/releases/latest/download/InvoSyncTallyConnector.exe
```

**Option B — Your own server/file share:**
Provide the `.exe` file directly.

### 2. Create `appsettings.json`
Place this file in the **same folder** as the `.exe`:

```json
{
  "InvoSync": {
    "ApiBaseUrl": "https://invosync-backend-yjfa.onrender.com",
    "ApiKey": "REPLACE_WITH_CLIENT_API_KEY",
    "PollIntervalSeconds": 30
  },
  "Tally": {
    "Host": "localhost",
    "Port": 9000,
    "TimeoutSeconds": 60
  },
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.Hosting.Lifetime": "Warning"
    }
  }
}
```

**Important:** Replace `ApiKey` with the client's unique API key (generated from your InvoSync admin panel → Clients → Generate Key).

### 3. Run the Connector
Double-click `InvoSyncTallyConnector.exe` — it runs silently in the system tray (near the clock).

**Tray icon right-click menu:**
- Shows live Tally connection status (updated every 30s)
- **Ping Tally** — manually check if Tally is reachable
- **Show Failed Imports** — view dead-letter queue count
- **Exit** — closes the connector

### 4. Verify it's Working
1. Open Tally Prime on the client PC
2. Ensure port 9000 is enabled (F1 → Settings → Connectivity)
3. The tray icon will show "Tally: Connected" within 30 seconds
4. The InvoSync backend will show the connector as online (green indicator in your dashboard)

## Troubleshooting

### Connector won't start
- Check Windows Defender didn't block the .exe
- Run from Command Prompt to see error output:
  ```
  InvoSyncTallyConnector.exe --verbose
  ```
- Check `appsettings.json` syntax (valid JSON)

### "Tally: Unreachable" in tray
- Is Tally Prime open and running?
- Is port 9000 enabled? (F1 → Settings → Connectivity → Port 9000)
- Is Tally's "Allow Remote" setting enabled?
- Run from CMD to see detailed logs:
  ```
  InvoSyncTallyConnector.exe
  ```

### Invoices not importing
1. Check the InvoSync web app → Dashboard — is the invoice status "Validated"?
2. Is the connector showing "Tally: Connected"?
3. Right-click tray → **Show Failed Imports** — any dead-letter items?
4. Check the connector's log output (run from CMD)

## Multi-Client Deployment Checklist

For each client PC:

- [ ] Download the .exe to a permanent folder (not Desktop or Downloads)
- [ ] Create `appsettings.json` with their unique `ApiKey`
- [ ] Verify Tally Prime is installed and port 9000 is open
- [ ] Run the connector once and confirm "Tally: Connected" in tray
- [ ] Create a scheduled task or Startup folder shortcut to auto-start the connector on boot:
  ```
  Windows Key + R → shell:startup
  → Create shortcut to InvoSyncTallyConnector.exe
  ```
- [ ] Test: create a test invoice in InvoSync web app, review & confirm, verify it appears in Tally within 60 seconds

## Architecture
```
[InvoSync Cloud Backend]  ←HTTPS→  [Connector on Client PC]  ←HTTP→  [Tally Prime:9000]
         │                              │
         │  Polls every 30s             │  Pushes XML to Tally
         │  GET /sync/pending           │  POST localhost:9000
         │  POST /sync/confirm/{id}     │
         │  POST /sync/error/{id}       │
         │  POST /sync/companies        │
         │  POST /sync/ledgers          │
```
