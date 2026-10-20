# Rise of Incarnates offline revival: one-time setup on the player's own PC.
# Builds a playable game folder from the player's Steam install + the full asset depot, then patches roi.exe.
# Executable/archive assets are built locally; recovered Library page captures ship separately.
param([string]$Steam = "", [string]$Depot = "", [string]$Game = "", [switch]$NoPause)
$ErrorActionPreference = "Stop"
$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $tools 'setup_paths.ps1')
. (Join-Path $tools 'deployment.ps1')
$deployment = (Read-RoiDeployment).client
if (-not $Steam -and $deployment.steam_path) { $Steam = $deployment.steam_path }
if (-not $Depot -and $deployment.depot_path) { $Depot = $deployment.depot_path }
if (-not $Game -and $deployment.game_path) { $Game = $deployment.game_path }
$root = Split-Path -Parent $tools
if (-not $Game) { $Game = Join-Path $root "game" }
$Manifest = "1099989411347492672"

function Say($t) { Write-Host $t -ForegroundColor Cyan }
function Pause-End { if (-not $NoPause) { Read-Host "Press Enter to close" | Out-Null } }
function Fail($t) { Write-Host $t -ForegroundColor Red; Pause-End; exit 1 }

# --- Python ---------------------------------------------------------------------------------
$pyExe = $null
$pyPre = @()
foreach ($cand in @(@("python.exe"), @("py.exe", "-3"))) {
    $cmd = Get-Command $cand[0] -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { continue }
    $pre = @($cand | Select-Object -Skip 1)
    try { $v = & $cmd.Source @pre --version 2>&1 } catch { continue }
    if ("$v" -match "Python 3\.(\d+)" -and [int]$matches[1] -ge 10) { $pyExe = $cmd.Source; $pyPre = $pre; break }
}
if (-not $pyExe) { Fail "Python 3.10 or newer is needed: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." }
function Invoke-Tool([string[]]$a) { & $pyExe @pyPre -I @a; if ($LASTEXITCODE) { Fail "Step failed: $($a -join ' ')" } }
Say "Using $pyExe $pyPre"
Push-Location $tools
try { Invoke-Tool @('check_launch.py', '--package') } finally { Pop-Location }

# --- Steam install (shutdown build: provides roi.exe and the loose files) ---------------------
$steamRoot = (Get-ItemProperty -Path "HKCU:\Software\Valve\Steam" -Name SteamPath -ErrorAction SilentlyContinue).SteamPath
if (-not $Steam) {
    $libs = @()
    if ($steamRoot) {
        $libs += $steamRoot
        $vdf = Join-Path $steamRoot "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) { $libs += ([regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"') | ForEach-Object { $_.Groups[1].Value -replace '\\\\', '\' }) }
    }
    foreach ($l in $libs) {
        $found = Resolve-RoiSteamRoot (Join-Path $l 'steamapps\common\Rise_of_Incarnates')
        if ($found) { $Steam = $found; break }
    }
}
$resolvedSteam = Resolve-RoiSteamRoot $Steam
for ($attempt = 0; -not $resolvedSteam -and $attempt -lt 3; $attempt++) {
    if ($Steam) { Write-Host "No supported game layout found at: $Steam" -ForegroundColor Yellow }
    $Steam = Read-Host 'Game folder, exe folder, or full path to roi.exe (quotes are accepted)'
    $resolvedSteam = Resolve-RoiSteamRoot $Steam
}
if (-not $resolvedSteam) { Fail 'Could not find roi.exe. Select a game folder containing exe\roi.exe, its exe folder, or that roi.exe file.' }
$Steam = $resolvedSteam
Say "Steam install: $Steam"
$sourceCheck = Get-RoiSourceValidation -SteamRoot $Steam
if (-not $sourceCheck.Compatible) {
    Write-Host ('Selected executable: ' + $sourceCheck.Executable) -ForegroundColor Yellow
    Write-Host ('Actual SHA256: ' + $sourceCheck.ActualSha256) -ForegroundColor Yellow
    Write-Host ('Required SHA256: ' + $sourceCheck.ExpectedSha256) -ForegroundColor Yellow
    Fail @'
This is not the supported unmodified Steam executable. No game files have been copied or changed.
For the Steam install, select the normal game folder under steamapps\common\Rise_of_Incarnates,
NOT steamapps\content\app_258160\depot_258162. The content depot is used separately for assets.
Install the game normally in Steam first. Do not bypass the executable hash check.
'@
}

# --- Full asset depot (the Steam install only has stub archives) --------------------------------
if (-not $Depot -and $steamRoot) { $Depot = Join-Path $steamRoot "steamapps\content\app_258160\depot_258162" }
if (-not (Test-Path "$Depot\resource\masterWindows\GxArchivedFile001.dat") -or (Get-Item "$Depot\resource\masterWindows\GxArchivedFile001.dat").Length -lt 500MB) {
    Write-Host ""
    Write-Host "The full game assets are missing. Download them once with the Steam console:" -ForegroundColor Yellow
    Write-Host "  1. Press Win+R, enter  steam://open/console" -ForegroundColor Yellow
    Write-Host "  2. Type:  download_depot 258160 258162 $Manifest" -ForegroundColor Yellow
    Write-Host "  3. Wait until Steam says the depot download is complete (about 9 GB)," -ForegroundColor Yellow
    Write-Host "     then run Setup.bat again (or pass -Depot <folder> if it went elsewhere)." -ForegroundColor Yellow
    if ($Depot) { Write-Host "  Expected folder: $Depot" -ForegroundColor Yellow }
    Pause-End; exit 1
}
Say "Asset depot: $Depot"

# --- Game folder ----------------------------------------------------------------------------
Say "Copying game files into $Game (about 10 GB, a few minutes)..."
New-Item -ItemType Directory -Force $Game | Out-Null
robocopy "$Depot\resource" "$Game\resource" /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "Copying the depot failed (robocopy code $LASTEXITCODE)." }
robocopy "$Steam\exe" "$Game\exe" /E /NFL /NDL /NJH /NJS /NP /XF roi.exe | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "Copying the Steam exe folder failed (robocopy code $LASTEXITCODE)." }

# --- Python libraries for the patcher -------------------------------------------------------
$libs = Join-Path $tools "libs"
if (-not (Test-Path "$libs\pefile.py")) {
    Say "Installing pefile and capstone (patch tools) into $libs..."
    & $pyExe @pyPre -I -m pip --isolated install --quiet --disable-pip-version-check --index-url https://pypi.org/simple --only-binary=:all: --target $libs pefile==2024.8.26 capstone==5.0.9
    if ($LASTEXITCODE) { Fail "pip install failed (internet needed once)." }
}

# --- Config, scripts, data fix, patched exe -------------------------------------------------
$cfgFile = Join-Path $tools "config.json"
$cfg = @{ steam = $Steam; depot = $Depot; game = $Game; libs = $libs }
if (Test-Path $cfgFile) {  # keep the online lobby settings made with online.ps1
    $old = Get-Content $cfgFile -Raw | ConvertFrom-Json
    foreach ($k in 'lobby_mode', 'lobby_server', 'lobby_listen', 'lobby_token', 'lobby_steam_id', 'lobby_transport', 'public_lobby_host') { if ($old.$k) { $cfg[$k] = $old.$k } }
}
$cfg | ConvertTo-Json | Set-Content $cfgFile -Encoding utf8
Push-Location $tools
Say "Unpacking the script files the patched game loads..."
Invoke-Tool @("extract_scripts.py")
Say "Applying the sidekick-table fix from your Steam install..."
Invoke-Tool @("overlay.py", "apply")
Say 'Matching Customize items to their existing archive thumbnails...'
Invoke-Tool @('customize_thumbs.py', 'write')
Say 'Installing distinct customization labels (original cosmetic names are not yet mapped)...'
Invoke-Tool @('setup_customize_names.py')
Say 'Initializing backed-up skill loadouts and configurable revival unlock rules...'
Invoke-Tool @('setup_skills.py')
Say "Building the patched roi.exe..."
Invoke-Tool @("build.py", "--server")
Say 'Verifying the original Steam Library browser helper...'
Invoke-Tool @('setup_library.py')
Pop-Location
Write-Host ""
Write-Host "Done. Start Steam, then run 'Play Rise of Incarnates.bat'." -ForegroundColor Green
Pause-End
