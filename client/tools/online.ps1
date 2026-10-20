# Online lobby settings (saved in tools\config.json; takes effect the next time you start the game).
#   online.ps1 -Mode public/public-lan  pinned TLS shared directory (Online - Steam launchers)
#   online.ps1 -Mode steam           direct Steam directory (Online - Steam Discovery.bat)
#   online.ps1 -Mode host            one PC runs a shared lobby server for a LAN or VPN; friends use -Mode join
#   online.ps1 -Mode join [address]  use a friend's shared lobby server (their LAN/VPN or public IP)
#   online.ps1 -Mode off             nothing leaves this PC (custom lobbies are not published)
# Matches themselves always connect through Steam.
param([ValidateSet("steam", "host", "join", "off", "public", "public-lan")][string]$Mode = "steam", [string]$Address = "", [switch]$NoPause)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'deployment.ps1')
$file = Join-Path $here "config.json"
$cfg = [pscustomobject]@{}
if (Test-Path $file) { $cfg = Get-Content $file -Raw | ConvertFrom-Json }

function Set-Cfg($name, $value) { $cfg | Add-Member -NotePropertyName $name -NotePropertyValue $value -Force }
function Done { if (-not $NoPause) { Read-Host "Press Enter to close" | Out-Null } }

switch ($Mode) {
    {$_ -in @('public','public-lan')} {
        $public = (Read-RoiDeployment -Required).client
        if ($public.certificate_sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Public TLS server certificate has not been configured.' }
        Assert-RoiPort $public.port
        Set-Cfg 'lobby_mode' 'server'
        Set-Cfg 'lobby_transport' 'tls-public'
        Set-Cfg 'lobby_listen' $RoiLoopback
        Set-Cfg 'lobby_server' $RoiLocalLobby
        $target = if ($Mode -eq 'public-lan') { $public.lan_host } else { $public.internet_host }
        Assert-RoiHost $target
        Set-Cfg 'public_lobby_host' $target
        Write-Host ('Public lobby via pinned TLS: ' + $target + ':' + $public.port) -ForegroundColor Green
        Write-Host 'Open test service: no invitation or Steam-ID allowlist. Native matches still use Steam.'
    }
    "steam" {
        Set-Cfg 'lobby_transport' 'direct'
        Set-Cfg "lobby_mode" "steam"
        Set-Cfg "lobby_listen" $RoiLoopback
        Set-Cfg "lobby_server" $RoiLocalLobby
        Write-Host "Online through Steam: rooms you create are listed for other players via Steam," -ForegroundColor Green
        Write-Host "and Search Lobby > Advanced Search shows theirs. No address or port forwarding needed."
    }
    "host" {
        throw "Use the authenticated Rocky lobby server and Online - Join. External Windows hosting is disabled in this hardened build."
    }
    "join" {
        $expected = Get-RoiVpnEndpoint
        if (-not $Address) { $Address = $expected }
        $Address = $Address.Trim()
        if ($Address -notmatch ':\d+$') { $Address = "${Address}:$((Read-RoiDeployment -Required).client.vpn_lobby_port)" }
        if ($Address -cne $expected) { throw 'Endpoint must match vpn_lobby_host and vpn_lobby_port in deployment.local.json.' }
        if ($cfg.lobby_token -notmatch '^[0-9a-fA-F]{32}$') {
            throw "Import your individually provisioned lobby credential before joining. Do not reuse another player's token."
        }
        Set-Cfg 'lobby_transport' 'direct'
        Set-Cfg "lobby_mode" "server"
        Set-Cfg "lobby_listen" $RoiLoopback
        Set-Cfg "lobby_server" $Address
        $hostPart, $port = $Address -split ':(?=\d+$)'
        $ok = $false
        try { $c = New-Object Net.Sockets.TcpClient; $ok = $c.ConnectAsync($hostPart, [int]$port).Wait(3000) -and $c.Connected; $c.Close() } catch {}
        if ($ok) { Write-Host "Lobby server at $Address answers. Start the game and use Play > Custom Match." -ForegroundColor Green }
        else { Write-Host "Saved $Address, but it does not answer yet (host not running, firewall, or wrong address)." -ForegroundColor Yellow }
    }
    "off" {
        Set-Cfg 'lobby_transport' 'direct'
        Set-Cfg "lobby_mode" "server"
        Set-Cfg "lobby_listen" $RoiLoopback
        Set-Cfg "lobby_server" $RoiLocalLobby
        Write-Host "Lobby discovery is local-only. Steam and native game connections are not disabled." -ForegroundColor Green
    }
}
$cfg | ConvertTo-Json | Set-Content $file -Encoding utf8
Done
