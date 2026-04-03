param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Read-DotEnvValue {
    param(
        [string]$EnvFile,
        [string]$Key
    )

    if (-not (Test-Path $EnvFile)) {
        return ""
    }
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts[0].Trim() -ne $Key) {
            continue
        }
        return $parts[1].Trim().Trim('"').Trim("'")
    }
    return ""
}

function Resolve-LauncherPython {
    param(
        [string]$RepoRoot
    )

    $envLocal = Join-Path $RepoRoot ".env"
    $configuredPython = Read-DotEnvValue -EnvFile $envLocal -Key "ATH_PYTHON"
    if ($configuredPython) {
        if ([System.IO.Path]::IsPathRooted($configuredPython) -and (Test-Path $configuredPython)) {
            return $configuredPython
        }
        $candidate = Join-Path $RepoRoot $configuredPython
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $configuredVenv = Read-DotEnvValue -EnvFile $envLocal -Key "ATH_WINDOWS_VENV"
    if ($configuredVenv) {
        foreach ($candidateRoot in @($configuredVenv, (Join-Path $RepoRoot $configuredVenv))) {
            $candidate = Join-Path $candidateRoot "Scripts\python.exe"
            if (Test-Path $candidate) {
                return $candidate
            }
        }
    }

    $repoVenv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $repoVenv) {
        return $repoVenv
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @($pyCmd.Source, "-3")
    }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return $pythonCmd.Source
    }

    return $null
}

$repoRoot = Resolve-RepoRoot
$launcher = Resolve-LauncherPython -RepoRoot $repoRoot
if (-not $launcher) {
    Write-Host "Python launcher not found for ATH_BEM."
    Write-Host "Please run:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\bootstrap\bootstrap_windows.ps1 -InitLocalConfig"
    exit 1
}

Push-Location $repoRoot
try {
    if ($launcher -is [System.Array]) {
        & $launcher[0] $launcher[1] -m ath_bem gui @Args
    }
    else {
        & $launcher -m ath_bem gui @Args
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

