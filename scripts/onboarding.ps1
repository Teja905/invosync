# ============================================================
# InvoSync Tally Connector Onboarding (Windows)
# Guides CA pilot firms through Tally HTTP + connector setup
# ============================================================

$ErrorActionPreference = "Stop"
$host.UI.RawUI.WindowTitle = "InvoSync Tally Connector Setup"

Write-Host "============================================================" -ForegroundColor Blue
Write-Host "  InvoSync Tally Connector Setup" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Blue
Write-Host ""

# Step 1 — Check Tally
Write-Host "[1/5] Checking Tally Prime..." -ForegroundColor Blue
$tallyPaths = @("C:\Program Files\TallyPrime", "C:\Program Files (x86)\TallyPrime", "$env:LOCALAPPDATA\TallyPrime")
$found = $false
foreach ($p in $tallyPaths) { if (Test-Path $p) { $found = $p; break } }
if (-not $found) {
    Write-Host "  Tally Prime not found at default locations." -ForegroundColor Yellow
    Write-Host "  Please ensure Tally Prime is installed, then continue." -ForegroundColor Yellow
} else {
    Write-Host "  Found: $found" -ForegroundColor Green
}

# Step 2 — Tally HTTP config
Write-Host ""
Write-Host "[2/5] Tally HTTP Server Configuration" -ForegroundColor Blue
Write-Host "  In Tally Prime, press F12 (Configure) > Advanced Configuration"
Write-Host "  Set 'Allow HTTP/S Requests' to Yes"
Write-Host "  Note the Port (default 9000)"
Write-Host "  IMPORTANT: Set a Password for security"
Write-Host ""
$tallyPort = Read-Host "  Tally HTTP Port (default 9000)"
if ([string]::IsNullOrEmpty($tallyPort)) { $tallyPort = "9000" }
$tallyPassword = Read-Host "  Tally HTTP Password (enter password set in Tally)" -AsSecureString
$tallyPasswordPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($tallyPassword)
)

# Step 3 — Validate connection
Write-Host ""
Write-Host "[3/5] Validating Tally connection..." -ForegroundColor Blue
try {
    $r = Invoke-WebRequest -Uri "http://localhost:$tallyPort" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "  Tally is reachable on port $tallyPort" -ForegroundColor Green
} catch {
    Write-Host "  Cannot reach Tally. Check: Tally running? HTTP enabled? Port correct?" -ForegroundColor Red
    Write-Host "  You can skip this check and configure later." -ForegroundColor Yellow
}

# Step 4 — Install connector service
Write-Host ""
Write-Host "[4/5] Installing Tally Connector..." -ForegroundColor Blue
$connectorDir = "C:\Program Files\InvoSync"
if (-not (Test-Path $connectorDir)) { New-Item -ItemType Directory -Path $connectorDir -Force | Out-Null }
$connectorExe = Join-Path $connectorDir "InvoSyncTallyConnector.exe"
$sourceExe = Join-Path $PSScriptRoot "..\tally-connector\InvoSyncTallyConnector\bin\Release\net10.0\win-x64\publish\InvoSyncTallyConnector.exe"
if (Test-Path $sourceExe) {
    Copy-Item -Path $sourceExe -Destination $connectorExe -Force
    Write-Host "  Copied connector to $connectorDir" -ForegroundColor Green
} else {
    Write-Host "  Connector binary not found at $sourceExe" -ForegroundColor Yellow
    Write-Host "  Build it first: dotnet publish tally-connector/InvoSyncTallyConnector" -ForegroundColor Yellow
}

# Check if service already exists
$svc = Get-Service -Name "InvoSyncConnector" -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "  Service already exists. Restarting..." -ForegroundColor Yellow
    Stop-Service -Name "InvoSyncConnector" -Force -ErrorAction SilentlyContinue
    Start-Sleep 2
    Start-Service -Name "InvoSyncConnector"
} elseif (Test-Path $connectorExe) {
    New-Service -Name "InvoSyncConnector" `
        -BinaryPathName "`"$connectorExe`"" `
        -DisplayName "InvoSync Tally Connector" `
        -StartupType Automatic
    Start-Service -Name "InvoSyncConnector"
    Write-Host "  Service installed and started" -ForegroundColor Green
}

# Step 5 — Save config
Write-Host ""
Write-Host "[5/5] Saving configuration..." -ForegroundColor Blue
$envContent = @"
TALLY_PORT=$tallyPort
TALLY_PASSWORD=$tallyPasswordPlain
"@
$envPath = Join-Path $connectorDir ".env"
$envContent | Out-File -FilePath $envPath -Encoding UTF8
Write-Host "  Config saved to $envPath" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Blue
Write-Host "  Setup complete" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Blue
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Open InvoSync dashboard and upload an invoice"
Write-Host "  2. Review extracted data, assign ledgers, confirm"
Write-Host "  3. Connector auto-pushes to Tally"
Write-Host ""
Write-Host "Test connection: curl http://localhost:$tallyPort" -ForegroundColor Gray
