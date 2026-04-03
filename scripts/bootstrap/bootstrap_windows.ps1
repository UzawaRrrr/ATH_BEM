param(
    [string]$PythonExe = "",
    [string]$VenvDir = ".venv",
    [string]$Requirements = "requirements-win.txt",
    [switch]$InitLocalConfig,
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
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

function Read-JsonConfig {
    param([string]$ConfigPath)

    if (-not (Test-Path $ConfigPath)) {
        return $null
    }
    return Get-Content $ConfigPath -Raw | ConvertFrom-Json
}

function Resolve-BootstrapPython {
    param([string]$RequestedPythonExe)

    if ($RequestedPythonExe) {
        if (-not (Test-Path $RequestedPythonExe)) {
            throw "Specified Python executable does not exist: $RequestedPythonExe"
        }
        return @($RequestedPythonExe)
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @($pyCmd.Source, "-3.12")
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @($pythonCmd.Source)
    }

    throw "No usable Python launcher was found. Install Python 3.12+ or pass -PythonExe."
}

$repoRoot = Resolve-RepoRoot
$envExample = Join-Path $repoRoot ".env.example"
$envLocal = Join-Path $repoRoot ".env"
$configExample = Join-Path $repoRoot "config\toolchain.local.json.example"
$configLocal = Join-Path $repoRoot "config\toolchain.local.json"
$legacyConfigLocal = Join-Path $repoRoot "config\machine.local.json"
$configuredConfigPath = Read-DotEnvValue -EnvFile $envLocal -Key "ATH_TOOLCHAIN_CONFIG"
if (-not $configuredConfigPath) {
    $configuredConfigPath = Read-DotEnvValue -EnvFile $envLocal -Key "ATH_MACHINE_CONFIG"
}
$activeConfigPath = if ($configuredConfigPath) {
    if ([System.IO.Path]::IsPathRooted($configuredConfigPath)) { $configuredConfigPath } else { Join-Path $repoRoot $configuredConfigPath }
}
elseif (Test-Path $configLocal) { $configLocal }
elseif (Test-Path $legacyConfigLocal) { $legacyConfigLocal }
else { $configLocal }
$toolchainConfig = Read-JsonConfig -ConfigPath $activeConfigPath
$configuredVenv = Read-DotEnvValue -EnvFile $envLocal -Key "ATH_WINDOWS_VENV"
if (-not $configuredVenv -and $toolchainConfig -and $toolchainConfig.windows_venv) {
    $configuredVenv = [string]$toolchainConfig.windows_venv
}
if (-not $PythonExe -and $configuredVenv -and $VenvDir -eq ".venv") {
    $VenvDir = $configuredVenv
}
$venvPath = if ([System.IO.Path]::IsPathRooted($VenvDir)) { $VenvDir } else { Join-Path $repoRoot $VenvDir }
$requirementsPath = Join-Path $repoRoot $Requirements

if (-not (Test-Path $requirementsPath)) {
    throw "Requirements file not found: $requirementsPath"
}

if ($InitLocalConfig -and -not (Test-Path $configLocal) -and (Test-Path $configExample)) {
    Copy-Item $configExample $configLocal
    Write-Host "Created local toolchain config template: $configLocal"
}
if ($InitLocalConfig -and -not (Test-Path $envLocal) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envLocal
    Write-Host "Created local env template: $envLocal"
}
if (-not $InitLocalConfig -and -not (Test-Path $configLocal) -and -not (Test-Path $legacyConfigLocal)) {
    Write-Host "No local toolchain config found. Repo-safe defaults will be used." -ForegroundColor Yellow
    Write-Host "Tip: rerun with -InitLocalConfig if you want editable local templates." -ForegroundColor Yellow
}
if (-not $InitLocalConfig -and -not (Test-Path $envLocal)) {
    Write-Host "No .env file found. Launcher/runtime will use env vars, local JSON, and built-in defaults." -ForegroundColor Yellow
}

$bootstrapPython = Resolve-BootstrapPython -RequestedPythonExe $PythonExe
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating venv at $venvPath"
    $bootstrapCommand = @($bootstrapPython)
    if ($bootstrapCommand.Length -gt 1) {
        & $bootstrapCommand[0] @($bootstrapCommand[1..($bootstrapCommand.Length - 1)]) -m venv $venvPath
    }
    else {
        & $bootstrapCommand[0] -m venv $venvPath
    }
}

$pythonExePath = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $pythonExePath)) {
    throw "Python executable not found in venv: $pythonExePath"
}

Write-Host "Using venv Python: $pythonExePath"
& $pythonExePath -m pip install --upgrade pip setuptools wheel
& $pythonExePath -m pip install -r $requirementsPath

if (-not $SkipChecks) {
    Write-Host ""
    Write-Host "Running runtime doctor..."
    Push-Location $repoRoot
    try {
        & $pythonExePath -m ath_bem doctor runtime

        Write-Host ""
        Write-Host "Running Windows environment doctor..."
        & $pythonExePath -m ath_bem doctor windows --run-self-test
    }
    finally {
        Pop-Location
    }

}

Write-Host ""
Write-Host "Windows bootstrap complete."
Write-Host "Venv: $venvPath"
Write-Host "Requirements: $requirementsPath"
Write-Host "Default external workspace (if not overridden): %LOCALAPPDATA%\\ATH_BEM\\workspace"
Write-Host "Next:"
Write-Host "  1. Edit config\toolchain.local.json and/or .env if you need machine-specific overrides"
Write-Host "  2. Bootstrap WSL with: bash scripts/bootstrap/bootstrap_wsl.sh"
Write-Host "  3. Verify again with the Python inside your configured venv"
Write-Host "  4. After WSL bootstrap, optional hybrid check: python -m ath_bem doctor optimizer"
Write-Host "  5. Launch: python -m ath_bem gui"
