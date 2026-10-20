param([string]$AccessFile = "", [switch]$NoPause)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'deployment.ps1')
if (-not $AccessFile) { $AccessFile = Join-Path (Split-Path -Parent $here) 'lobby-access.json' }
$access = Get-Content -LiteralPath $AccessFile -Raw | ConvertFrom-Json
if ($access.lobby_token -notmatch '^[0-9a-fA-F]{32}$' -or
    ($access.lobby_steam_id -and $access.lobby_steam_id -notmatch '^7656119[0-9]{10}$') -or
    $access.lobby_server -cne (Get-RoiVpnEndpoint) -or
    $access.lobby_mode -ne 'server' -or $access.lobby_listen -ne $RoiLoopback) { throw 'Invalid lobby access file' }
$file = Join-Path $here 'config.json'
if (-not (Test-Path -LiteralPath $file)) { throw 'Run Setup.bat first.' }
$cfg = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
$backup = $file + '.before-lobby-access-' + (Get-Date -Format 'yyyyMMdd_HHmmss')
Copy-Item -LiteralPath $file -Destination $backup
foreach ($name in 'lobby_token','lobby_steam_id','lobby_mode','lobby_server','lobby_listen') {
    $cfg | Add-Member -NotePropertyName $name -NotePropertyValue $access.$name -Force
}
$cfg | ConvertTo-Json | Set-Content -LiteralPath $file -Encoding utf8
foreach ($privateFile in $file, $backup, $AccessFile) {
    & icacls.exe $privateFile /inheritance:r /grant:r "${env:USERNAME}:F" 'SYSTEM:F' | Out-Null
    if ($LASTEXITCODE) { throw 'Unable to restrict lobby credential file permissions' }
}
if ($access.lobby_steam_id) {
    Write-Host ('Lobby access installed for Steam ID ' + $access.lobby_steam_id + '. Keep this access file private.')
} else {
    Write-Host 'Lobby invitation installed; no Steam ID registration required. Keep this access file private.'
}
if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
