# InvoSync Tally Connector (C# / .NET)

Local Windows daemon that picks up generated XML files and pushes them into Tally Prime via Tally's HTTP interface.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  InvoSync Web App                │
│  (FastAPI + React, deployed on Railway/Vercel)   │
│                                                  │
│  Generates Tally XML → stores in MongoDB         │
│  Exposes REST endpoint: GET /api/v3/invoices/{id}/xml  │
└──────────────┬──────────────────────────────────┘
               │ HTTP (WAN)
               ▼
┌─────────────────────────────────────────────────┐
│          InvoSync Tally Connector (C#)           │
│  ┌───────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Polling   │  │ Queue    │  │ XML Pusher   │  │
│  │ Engine    │─▶│ Manager  │─▶│ (Tally Link) │  │
│  └───────────┘  └──────────┘  └──────┬───────┘  │
│  (Configurable interval)              │          │
└───────────────────────────────────────┼──────────┘
                                        │ HTTP (localhost:9000)
                                        ▼
                              ┌──────────────────┐
                              │   Tally Prime     │
                              │  (localhost:9000) │
                              └──────────────────┘
```

## How It Works

1. **Polling Engine** — On a configurable timer (default 30s), calls `GET /api/v3/invoices?status=validated` on the InvoSync API to fetch invoices ready for import.
2. **Queue Manager** — Maintains a local FIFO queue of pending imports. Ensures Tally isn't overwhelmed. Supports pause/resume.
3. **XML Pusher** — Sends XML to Tally via HTTP POST to `http://localhost:9000`. Tally's XML API accepts an `<ENVELOPE>` block and imports it. Response is parsed for success/failure.
4. **Status Callback** — On success, calls `PATCH /api/v3/invoices/{id}/status` to mark as `exported`. On failure, logs error and retries (max 3).

## Tally HTTP Interface

Tally listens on port 9000 by default. Send XML via:

```
POST http://localhost:9000
Content-Type: application/xml

<ENVELOPE>
  <HEADER><VERSION>1</VERSION><TALLYREQUEST>Import</TALLYREQUEST><TYPE>Data</TYPE></HEADER>
  <BODY>
    <DESC><TALLYREQUEST>Import</TALLYREQUEST></DESC>
    <DATA>
      <TALLYMESSAGE xmlns:UDF="TallyUDF">
        ... masters + voucher XML ...
      </TALLYMESSAGE>
    </DATA>
  </BODY>
</ENVELOPE>
```

Response contains `<LINEERROR>` tags if any entries fail.

## Project Structure (C#)

```
InvoSyncTallyConnector/
├── Program.cs                      # Entry point, service registration
├── appsettings.json                # Configuration (API URL, interval, Tally port)
├── Services/
│   ├── PollingService.cs           # BackgroundService, timer-based
│   ├── QueueManager.cs             # ConcurrentQueue<TallyImportJob>
│   └── TallyPusher.cs             # HTTP client to Tally, response parser
├── Models/
│   ├── InvoiceDto.cs               # InvoSync API response model
│   └── TallyImportResult.cs        # Success/failure from Tally
└── InvoSyncTallyConnector.csproj   # .NET 8, Worker Service template
```

## Configuration (`appsettings.json`)

```json
{
  "InvoSync": {
    "ApiBaseUrl": "https://api.invosync.com",
    "ApiKey": "sk-...",
    "PollIntervalSeconds": 30,
    "DefaultClientId": 1
  },
  "Tally": {
    "Host": "localhost",
    "Port": 9000,
    "TimeoutSeconds": 60
  }
}
```

## Deployment

- Install as a Windows Service: `sc create InvoSyncTallyConnector binPath=...`
- Or run as a console app for debugging
- Requires .NET 8 Runtime on the CA's Windows machine
- Must run on the same machine as Tally Prime (or same LAN)

## Future Enhancements

- **Watchdog mode** — Watch a local directory for XML files dropped by the web app
- **Import log** — Local SQLite database of all import attempts (success/failure/error)
- **Tray icon** — System tray app with status indicator and manual import button
- **Auto-update** — Check for connector updates on startup
