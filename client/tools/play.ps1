# Starts the client-side processes and the patched Rise of Incarnates client. Steam must be running and logged in.
# Crash details and scene changes go to logs\play.log.
#   always:   server.py      on loopback port 52710 (this player's profile, outfits, master data)
#   usually:  nrt_server.py  on port 52711       (lobby server; not started when joining a shared one elsewhere)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'deployment.ps1')
Set-Location $here
New-Item -ItemType Directory -Force (Join-Path $here "logs") | Out-Null

# python.exe on PATH, else the py launcher
$pyExe, $pyArgs = "python", @("-I")
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $pyExe, $pyArgs = "py", @("-3", "-I") }

function Test-Port($port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return [bool]$c
}

# online settings (online.ps1): steam = local lobby server publishing via Steam; server = shared lobby server
$cfgFile = Join-Path $here "config.json"
$mode, $listen, $lobby = "steam", $RoiLoopback, $RoiLocalLobby
if (Test-Path $cfgFile) {
    $c = Get-Content $cfgFile -Raw | ConvertFrom-Json
    if ($c.lobby_mode) { $mode = $c.lobby_mode }
    if ($mode -eq "server") {
        if ($c.lobby_listen) { $listen = $c.lobby_listen }
        if ($c.lobby_server) { $lobby = $c.lobby_server }
    }
}
$lobbyHost = ($lobby -split ':(?=\d+$)')[0]
$localLobby = $mode -ne "server" -or $lobbyHost -in @($RoiLoopback, "localhost") -or $listen -ne $RoiLoopback
$publicTLS = $c -and $c.lobby_transport -eq 'tls-public'

$started = @()
try {
& $pyExe @pyArgs check_launch.py
if ($LASTEXITCODE) { throw 'Launcher dependencies are missing or invalid. Reapply the complete client update.' }
if ($c -and $c.game) {
    $gameExe = Join-Path $c.game 'exe\roi.exe'
    if (@(Get-CimInstance Win32_Process -Filter "Name = 'roi.exe'" | Where-Object { $_.ExecutablePath -eq $gameExe }).Count) {
        throw 'This game client is already running. Close it before switching lobby mode.'
    }
}
if ($publicTLS) {
    if ((Test-Port 52711) -or (Test-Port 52713)) { throw 'Local lobby ports are already in use. Close the old client/services before switching transport.' }
    & $pyExe @pyArgs public_tunnel.py --check
    if ($LASTEXITCODE) { throw 'Pinned public gateway check failed; client was not started.' }
    $tunnel = Start-Process $pyExe -ArgumentList ($pyArgs + 'public_tunnel.py') -WorkingDirectory $here -WindowStyle Hidden -RedirectStandardOutput (Join-Path $here 'logs\public-tunnel.out.log') -RedirectStandardError (Join-Path $here 'logs\public-tunnel.err.log') -PassThru
    $started += $tunnel
    $deadline = (Get-Date).AddSeconds(7)
    while (-not ((Test-Port 52711) -and (Test-Port 52713))) {
        if ($tunnel.HasExited -or (Get-Date) -ge $deadline) { throw 'Public tunnel startup failed.' }
        Start-Sleep -Milliseconds 200
    }
}
if (-not (Test-Port 52710)) {
    $started += Start-Process $pyExe -ArgumentList ($pyArgs + "server.py") -WorkingDirectory $here -WindowStyle Hidden -PassThru
}
if ($publicTLS) {
    Write-Host 'Using the shared public lobby through the local TLS tunnel.' -ForegroundColor Cyan
} elseif (-not $localLobby) {
    Write-Host "Using the shared lobby server at $lobby." -ForegroundColor Cyan
} elseif (-not (Test-Port 52711)) {
    $started += Start-Process $pyExe -ArgumentList ($pyArgs + "nrt_server.py") -WorkingDirectory $here -WindowStyle Hidden -PassThru
} elseif ($listen -ne $RoiLoopback) {
    # hosting (online.ps1 -Mode host) needs the lobby server open to other PCs, not a leftover local-only one
    $bound = @(Get-NetTCPConnection -LocalPort 52711 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.LocalAddress })
    if ($bound -notcontains $listen) {
        Write-Host "A lobby server is already running for this PC only ($($bound -join ', ')); friends cannot reach it." -ForegroundColor Yellow
        Write-Host "Close it (the minimized Python window) and start the game again to host." -ForegroundColor Yellow
    }
}
Start-Sleep -Seconds 1

Write-Host "Starting Rise of Incarnates (the logo takes about 40 seconds to appear)..."
& $pyExe @pyArgs dbg.py play --seconds 86400 --log (Join-Path $here "logs\play.log")
if ($LASTEXITCODE) { throw ('Game launcher exited with code ' + $LASTEXITCODE + '. See the message above and tools\logs\play.log.') }
} finally {
foreach ($p in $started) {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id }
}
}
