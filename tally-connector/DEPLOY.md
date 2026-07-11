# InvoSync Tally Connector — Deployment Guide

## Prerequisites

1. **Windows 10+** or Windows Server 2019+
2. **.NET 8 Runtime** — install from https://dotnet.microsoft.com/download/dotnet/8.0
3. **Tally Prime 3.0+** — running with HTTP enabled on port 9000
4. **InvoSync API key** — generated from Settings > API Keys in the web app

## Enable Tally HTTP Port

1. Open Tally Prime
2. Press F12 (Configuration) > Advanced Configuration
3. Set "Allow Internal HTTP/HTTPS Calls" to **Yes**
4. Set "Internal HTTP/HTTPS Port" to **9000**
5. Save and restart Tally

## Installation

### Option A: Manual (Console)

1. Copy `InvoSyncTallyConnector/` to the CA's machine
2. Edit `appsettings.json` — set `ApiKey` and `ApiBaseUrl`
3. Run: `dotnet InvoSyncTallyConnector.dll`
4. Confirm "PollingService started" in console output

### Option B: Windows Service

```powershell
# From an admin PowerShell prompt
sc.exe create InvoSyncTallyConnector binPath="C:\Program Files\InvoSync\TallyConnector\InvoSyncTallyConnector.exe"
sc.exe description InvoSyncTallyConnector "Pushes verified invoices from InvoSync into Tally Prime"
sc.exe start InvoSyncTallyConnector
```

### Option C: MSI Installer (future)

Use WiX Toolset to build an MSI:
```
candle.exe installer.wxs
light.exe installer.wixobj
```

## Configuration

Edit `appsettings.json` after install:

| Key | Default | Description |
|-----|---------|-------------|
| `InvoSync:ApiBaseUrl` | `https://api.invosync.com` | Your InvoSync deployment URL |
| `InvoSync:ApiKey` | `sk-...` | API key from Settings page |
| `InvoSync:PollIntervalSeconds` | `30` | How often to check for pending invoices |
| `Tally:Host` | `localhost` | Tally machine hostname |
| `Tally:Port` | `9000` | Tally HTTP port |
| `Tally:TimeoutSeconds` | `60` | HTTP timeout for Tally requests |

## Verifying It Works

1. Process an invoice in the InvoSync web app
2. Validate and generate XML — status should show "validated"
3. Click "Send to Tally" (or wait for auto-poll)
4. The C# connector will:
   - Poll `GET /api/v3/sync/pending`
   - Push XML to `http://localhost:9000`
   - Call `POST /api/v3/sync/confirm/{id}`
5. Dashboard status changes to **Synced**

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Connection refused" | Tally not running or port wrong | Check Tally is open on port 9000 |
| "LINEERROR" in logs | Tally rejected the voucher | Check financial period, duplicate voucher no. |
| "401 Unauthorized" | Wrong API key | Regenerate in Settings page |
| Service won't start | Wrong .NET version | Install .NET 8 Runtime |
