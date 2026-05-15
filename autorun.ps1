# TradeFarm — unattended auto-restart wrapper for `npm run dev`.
# Survives Tauri/desktop-sleep exits that would otherwise cascade-kill the rig.
# Ctrl+C breaks the loop cleanly. 5 crashes within 60s trips the circuit breaker.
Set-Location -LiteralPath $PSScriptRoot

$logDir = Join-Path $PSScriptRoot 'dev'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir 'autorun.log'

# Circuit breaker — bail if we restart 5 times within a 60-second window.
$restartWindow = New-Object System.Collections.Generic.Queue[datetime]
$maxRestarts   = 5
$windowSeconds = 60
$cooldown      = 5

function Write-Event {
    param([string]$Message, [string]$Color = 'Gray')
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line  = "[$stamp] $Message"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $logFile -Value $line
}

Write-Event "autorun starting — wrapping 'npm run dev' (Ctrl+C to stop)" 'Cyan'

try {
    while ($true) {
        Write-Event "starting npm run dev" 'Cyan'
        # Run in the foreground so child processes inherit our console and
        # Ctrl+C propagates. npm.cmd is the Windows shim; & invokes it.
        & npm.cmd run dev
        $code = $LASTEXITCODE

        $color = if ($code -eq 0) { 'Yellow' } else { 'Red' }
        Write-Event "exited code=$code — restarting in ${cooldown}s" $color

        # Track this restart event and prune anything older than the window.
        $now = Get-Date
        $restartWindow.Enqueue($now)
        while ($restartWindow.Count -gt 0 -and
               ($now - $restartWindow.Peek()).TotalSeconds -gt $windowSeconds) {
            [void]$restartWindow.Dequeue()
        }

        if ($restartWindow.Count -ge $maxRestarts) {
            Write-Event "CIRCUIT BREAKER: $maxRestarts restarts within ${windowSeconds}s — rig is flapping, exiting" 'Red'
            exit 1
        }

        Start-Sleep -Seconds $cooldown
        Write-Event "resuming" 'Green'
    }
}
finally {
    Write-Event "autorun stopped" 'Yellow'
}
