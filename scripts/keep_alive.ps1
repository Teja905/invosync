# InvoSync Keep-Alive — pings Render backend every 5 min to prevent cold starts
# Usage: PowerShell -WindowStyle Hidden -File scripts\keep_alive.ps1
# Or add to Task Scheduler to run on login

$url = "https://invosync-backend-yjfa.onrender.com/health"
$logFile = Join-Path $PSScriptRoot "..\keep_alive.log"

while ($true) {
    try {
        $r = Invoke-WebRequest -Uri $url -TimeoutSec 10 -UseBasicParsing
        $msg = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') — $($r.StatusCode) OK"
    } catch {
        $msg = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') — FAILED: $_"
    }
    Write-Output $msg | Out-File -FilePath $logFile -Append
    Start-Sleep -Seconds 300
}
