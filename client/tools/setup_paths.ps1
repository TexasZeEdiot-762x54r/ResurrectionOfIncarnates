# Normalize pasted paths without evaluating them as PowerShell expressions.
function Resolve-RoiSteamRoot {
    param([AllowEmptyString()][string]$InputPath)
    if ([string]::IsNullOrWhiteSpace($InputPath)) { return $null }
    $value = $InputPath.Trim()
    if ($value.Length -ge 2) {
        $first = $value.Substring(0, 1)
        $last = $value.Substring($value.Length - 1, 1)
        if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
    }
    $value = [Environment]::ExpandEnvironmentVariables($value)
    try {
        $item = Get-Item -LiteralPath $value -ErrorAction Stop
        if ($item.PSProvider.Name -ne 'FileSystem') { return $null }
        if ($item.PSIsContainer) {
            $root = $item.FullName
            if ($root.Length -gt [IO.Path]::GetPathRoot($root).Length) {
                $root = $root.TrimEnd([char[]]'\/')
            }
            if (Test-Path -LiteralPath (Join-Path $root 'exe\roi.exe') -PathType Leaf) {
                return $root
            }
            if ($item.Name -eq 'exe' -and
                (Test-Path -LiteralPath (Join-Path $root 'roi.exe') -PathType Leaf)) {
                return $item.Parent.FullName
            }
        } elseif ($item.Name -eq 'roi.exe' -and $item.Directory.Name -eq 'exe') {
            return $item.Directory.Parent.FullName
        }
    } catch {
        return $null
    }
    return $null
}

function Get-RoiSourceValidation {
    param(
        [Parameter(Mandatory)][string]$SteamRoot,
        [string]$ExpectedSha256 = '34a46fbc9e2ea6c6c9eebfddd0d6e4bef388a3eea5088838dd134588225cedbb'
    )
    $exe = Join-Path $SteamRoot 'exe\roi.exe'
    $actual = (Get-FileHash -LiteralPath $exe -Algorithm SHA256 -ErrorAction Stop).Hash
    return [pscustomobject]@{
        Compatible = ($actual -eq $ExpectedSha256)
        Executable = $exe
        ExpectedSha256 = $ExpectedSha256
        ActualSha256 = $actual
    }
}
