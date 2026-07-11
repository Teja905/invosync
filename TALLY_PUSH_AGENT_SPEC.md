# Tally Desktop Push Agent — Build Spec

## What It Does
A tiny tray app on the CA's Windows machine that pulls pending XML from the backend API and pushes it directly into Tally Prime via HTTP.

## Architecture
```
Backend (Railway)  ←→  Desktop Agent (Windows tray)  → POST XML → Tally Prime
                               |                            (http://localhost:9000)
                        Polls GET /pending-pushes
                        Marks complete on success
```

## Requirements
- Python 3.12+ (or Node.js, whichever is easier)
- Single-file script or PyInstaller .exe
- Runs in system tray (background, no console window)
- Config: API URL + API token (set once, saved to config file)

## Endpoints the Backend Must Expose

### `GET /api/v3/pushes/pending?user_id={user_id}`
Returns list of {(invoice_id, xml_str, invoice_number)} that user approved but not yet pushed.

### `POST /api/v3/pushes/{invoice_id}/complete`
Agent calls after Tally confirms import. Backend marks as pushed.

## Desktop Agent Flow

```
1. Agent starts → reads config (api_url, token)
2. Every 30 seconds: GET /pending-pushes
3. If items found:
   a. POST XML to http://localhost:9000 (Tally)
   b. Parse Tally response for <LINE.ERROR> or <LINE.CREATED>
   c. POST /complete to mark done
   d. Show Windows notification: "Invoice INV-001 imported"
   e. On error: retry 3x, then log to file
4. System tray icon with right-click menu:
   - Show recent activity
   - Open config
   - Force push now
   - Exit
```

## Implementation Options

### Option A: Python + PyInstaller (Recommended)
- `psutil` to check if Tally.exe is running before pushing
- `pystray` for system tray icon
- `requests` for HTTP
- `schedule` for polling loop
- Build: `pyinstaller --onefile --noconsole tally_agent.py`

### Option B: Node.js + Electron (Heavier but cross-platform)
- Same logic, bundles Chromium
- Better UI for config/settings
- But 50MB+ vs Python's 8MB

## Tally HTTP Import Details
- URL: `http://localhost:9000`
- Method: POST
- Headers: `Content-Type: application/xml`
- Body: the XML string (same as what `/generate-xml` returns now)
- Tally must have Gateway of Tally enabled (F12 → Tally.NET Features)
- Company must be open in Tally
- Response contains `<LINE.CREATED>` on success, `<LINE.ERROR>` on failure

## Config File (JSON, saved to %APPDATA%/tally-agent/config.json)
```json
{
  "api_url": "https://your-backend.railway.app",
  "api_token": "jwt-token-here",
  "user_id": "mongo-object-id",
  "poll_interval_seconds": 30,
  "tally_url": "http://localhost:9000",
  "retry_count": 3
}
```

## Build & Distribution
```bash
pip install requests pystray schedule pillow psutil pyinstaller
pyinstaller --onefile --noconsole --icon=tally.ico tally_agent.py
# Distribute the .exe to CA uncle's desktop
```

## MVP Scope (Skip for V1)
- ❌ Auto-update
- ❌ Multi-company support
- ❌ Push history UI
- ❌ Error recovery beyond retry

## Success Criteria
1. User approves invoice in web app
2. Within 30 seconds, XML appears in Tally
3. Zero clicks from user after approval
4. Notification confirms import
5. Error logged if Tally not running or company not open

## Prompt to give opencode later
```
Build a Windows system tray agent in Python that polls a backend API for pending Tally XML pushes and sends them to Tally Prime via HTTP POST to localhost:9000. Single file, PyInstaller build, saves config to %APPDATA%. Include requirements.txt and build instructions.
Backend endpoints needed: GET /pending-pushes, POST /complete.
Tally response parsing: check for <LINE.CREATED>.
```
