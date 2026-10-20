# Dot-sourced by setup and launch tools. No deployment values belong in this file.
$RoiLoopback = [Net.IPAddress]::Loopback.ToString()
$RoiLocalLobby = "${RoiLoopback}:52711"
$script:RoiComponentRoot = Split-Path -Parent $PSScriptRoot

function Read-RoiDeployment([switch]$Required) {
    $choices = if ($env:ROI_DEPLOYMENT_FILE) { @($env:ROI_DEPLOYMENT_FILE) } else {
        @((Join-Path $script:RoiComponentRoot 'deployment.local.json'),
          (Join-Path (Split-Path -Parent $script:RoiComponentRoot) 'deployment.local.json'))
    }
    $file = $choices | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $file) {
        if ($Required -or $env:ROI_DEPLOYMENT_FILE) { throw 'Copy deployment.example.json to deployment.local.json and configure it first.' }
        return [pscustomobject]@{ version=1; client=[pscustomobject]@{}; server=[pscustomobject]@{} }
    }
    $item = Get-Item -LiteralPath $file
    if ($item.Length -gt 32768 -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe deployment settings file.' }
    $value = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
    if ($value.version -ne 1 -or -not $value.client) { throw 'Invalid deployment settings format.' }
    return $value
}

function Assert-RoiPort($Value) {
    if ($Value -isnot [int] -and $Value -isnot [long]) { throw 'Deployment port must be an integer.' }
    if ($Value -lt 1024 -or $Value -gt 65535) { throw 'Invalid deployment port.' }
}

function Assert-RoiHost([string]$Value) {
    if ($Value.Length -gt 253 -or $Value -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$') {
        throw 'Configure an IPv4 address or DNS hostname in deployment.local.json.'
    }
}

function Get-RoiVpnEndpoint {
    $client = (Read-RoiDeployment -Required).client
    Assert-RoiHost $client.vpn_lobby_host
    Assert-RoiPort $client.vpn_lobby_port
    return ('{0}:{1}' -f $client.vpn_lobby_host,$client.vpn_lobby_port)
}
