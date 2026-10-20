param([switch]$NoPause)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
try {
    $cfgFile = Join-Path $here 'config.json'
    if (-not (Test-Path -LiteralPath $cfgFile)) { throw 'Run Setup.bat first for a new installation.' }
    $cfg = Get-Content -LiteralPath $cfgFile -Raw | ConvertFrom-Json
    $exe = Join-Path $cfg.game 'exe\roi.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw 'The configured game folder is missing; check config.json.' }
    if (@(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'roi.exe' -and $_.ExecutablePath -eq $exe }).Count) {
        throw 'Close this game client before applying the update.'
    }
    $python, $args = 'python', @('-I')
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $python, $args = 'py', @('-3','-I') }
    Push-Location $here
    try {
        & $python @args check_launch.py --package
        if ($LASTEXITCODE) { throw 'Client package verification failed. Extract the complete client ZIP again.' }
        & $python @args setup_library.py
        if ($LASTEXITCODE) { throw 'Library browser verification/repair failed.' }
        & $python @args customize_thumbs.py write
        if ($LASTEXITCODE) { throw 'Thumbnail metadata generation failed.' }
        & $python @args setup_customize_names.py
        if ($LASTEXITCODE) { throw 'Customization label installation failed.' }
        & $python @args setup_skills.py
        if ($LASTEXITCODE) { throw 'Skill-grid profile migration failed.' }
        & $python @args setup_commendations.py
        if ($LASTEXITCODE) { throw 'Commendation click-limit update failed.' }
    } finally { Pop-Location }
    Write-Host 'Metadata updated; skill profile migrated; commendation click limit removed with an executable backup. Config and credentials preserved.' -ForegroundColor Green
    Write-Host 'Start Steam, then Online - Steam.bat (or Online - Steam (LAN).bat on the server LAN). Read PUBLIC-LOBBY.txt.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
    exit 1
}
if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
