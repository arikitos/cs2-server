[CmdletBinding()]
param(
    [switch]$SkipGameInstall,
    [switch]$SkipFrameworkInstall
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function New-HexSecret {
    param([int]$Bytes = 24)
    $buffer = New-Object byte[] $Bytes
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    } finally {
        $generator.Dispose()
    }
    return (($buffer | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Set-DotEnvValue {
    param([string]$Text, [string]$Name, [string]$Value)
    $escaped = [Regex]::Escape($Name)
    if ($Text -match "(?m)^${escaped}=.*$") {
        return [Regex]::Replace($Text, "(?m)^${escaped}=.*$", "${Name}=${Value}")
    }
    return $Text.TrimEnd() + "`n${Name}=${Value}`n"
}

function Get-DotEnvValue {
    param([string]$Name)
    $escaped = [Regex]::Escape($Name)
    $line = Get-Content -LiteralPath ".env" | Where-Object { $_ -match "^${escaped}=" } | Select-Object -Last 1
    if (-not $line) { return "" }
    return ($line -split "=", 2)[1].Trim()
}

function Write-Utf8File {
    param([string]$Path, [string]$Text)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($Path), $Text, $encoding)
}

function Test-DockerEngine {
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Start-DockerDesktop {
    if (Test-DockerEngine) { return }

    $candidatePaths = @()
    if ($env:ProgramFiles) {
        $candidatePaths += (Join-Path $env:ProgramFiles "Docker/Docker/Docker Desktop.exe")
    }
    if (${env:ProgramFiles(x86)}) {
        $candidatePaths += (Join-Path ${env:ProgramFiles(x86)} "Docker/Docker/Docker Desktop.exe")
    }
    if ($env:LOCALAPPDATA) {
        $candidatePaths += (Join-Path $env:LOCALAPPDATA "Docker/Docker Desktop.exe")
    }

    $desktopPath = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $desktopPath) {
        throw "Docker Desktop is installed but its engine is not running. Start Docker Desktop and run the installer again."
    }

    Write-Step "Starting Docker Desktop"
    Start-Process -FilePath $desktopPath | Out-Null
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine) { return }
    }

    throw "Docker Desktop did not become ready within three minutes. Open Docker Desktop, resolve the reported problem, and run the installer again."
}

function Assert-WindowsDocker {
    if ($env:OS -ne "Windows_NT") {
        throw "This installer supports Windows only."
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is required but the docker command was not found in PATH."
    }

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose is required. Update Docker Desktop and run the installer again."
    }

    Start-DockerDesktop

    $dockerOs = [string](& docker info --format '{{.OSType}}' 2>$null | Select-Object -First 1)
    $dockerArchitecture = [string](& docker info --format '{{.Architecture}}' 2>$null | Select-Object -First 1)
    $dockerOs = $dockerOs.Trim().ToLowerInvariant()
    $dockerArchitecture = $dockerArchitecture.Trim().ToLowerInvariant()

    if ($dockerOs -ne "linux") {
        throw "Docker Desktop must use Linux containers. Switch to Linux containers and run the installer again."
    }
    if (@("amd64", "x86_64") -notcontains $dockerArchitecture) {
        throw "The CS2 runtime requires an amd64 Docker engine. Detected architecture: $dockerArchitecture"
    }
}

Write-Step "Checking Windows and Docker Desktop"
Assert-WindowsDocker

$projectPath = [IO.Path]::GetFullPath($PSScriptRoot).Replace("\", "/")
$defaultDataPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "server/cs2")).Replace("\", "/")

Write-Step "Preparing local configuration"
if (-not (Test-Path -LiteralPath ".env")) {
    $envText = Get-Content -LiteralPath ".env.example" -Raw
    $envText = Set-DotEnvValue $envText "PROJECT_PATH" $projectPath
    $envText = Set-DotEnvValue $envText "CS2_DATA_PATH" $defaultDataPath
    $envText = Set-DotEnvValue $envText "PANEL_PASSWORD" (New-HexSecret 18)
    $envText = Set-DotEnvValue $envText "CS2_RCON_PASSWORD" (New-HexSecret 18)
    Write-Utf8File ".env" $envText
    Write-Host "Created .env with generated panel and RCON passwords."
} else {
    $envText = Get-Content -LiteralPath ".env" -Raw
    if ($envText -match "(?m)^MANAGER_PATH=") {
        $envText = [Regex]::Replace($envText, "(?m)^MANAGER_PATH=.*\r?\n?", "")
    }
    $envText = Set-DotEnvValue $envText "PROJECT_PATH" $projectPath
    if (-not (Get-DotEnvValue "CS2_DATA_PATH")) {
        $envText = Set-DotEnvValue $envText "CS2_DATA_PATH" $defaultDataPath
    }
    if (-not (Get-DotEnvValue "PANEL_PASSWORD")) {
        $envText = Set-DotEnvValue $envText "PANEL_PASSWORD" (New-HexSecret 18)
    }
    if (-not (Get-DotEnvValue "CS2_RCON_PASSWORD")) {
        $envText = Set-DotEnvValue $envText "CS2_RCON_PASSWORD" (New-HexSecret 18)
    }
    Write-Utf8File ".env" $envText
}

$dataPath = Get-DotEnvValue "CS2_DATA_PATH"
if (-not [IO.Path]::IsPathRooted($dataPath)) {
    $dataPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $dataPath))
}
New-Item -ItemType Directory -Force -Path $dataPath, "server/state/runtime", "server/state/configs", "server/state/backups" | Out-Null

Write-Step "Validating Docker Compose configuration"
& docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "compose.yml or .env is invalid" }

Write-Step "Building maintenance images"
& docker compose --profile maintenance build cs2-updater cs2-modinstaller
if ($LASTEXITCODE -ne 0) { throw "Failed to build maintenance images" }

$gameBinary = Join-Path $dataPath "game/bin/linuxsteamrt64/cs2"
if (-not $SkipGameInstall -and -not (Test-Path -LiteralPath $gameBinary)) {
    Write-Step "Installing the CS2 dedicated server with SteamCMD"
    & docker compose --profile maintenance run --rm -e CS2_UPDATER_MODE=update -e "CS2_UPDATER_CONFIRM=UPDATE CS2" cs2-updater
    if ($LASTEXITCODE -ne 0) { throw "SteamCMD installation failed" }
}
if (-not (Test-Path -LiteralPath $gameBinary)) {
    throw "CS2 is not installed at $dataPath. Run setup-on-windows.ps1 without -SkipGameInstall."
}

if (-not $SkipFrameworkInstall) {
    Write-Step "Installing Metamod and CounterStrikeSharp"
    & docker compose --profile maintenance run --rm cs2-modinstaller
    if ($LASTEXITCODE -ne 0) { throw "Metamod or CounterStrikeSharp installation failed" }
    & docker compose --profile maintenance run --rm -e CS2_UPDATER_MODE=repair-metamod -e "CS2_UPDATER_CONFIRM=UPDATE CS2" cs2-updater
    if ($LASTEXITCODE -ne 0) { throw "Metamod activation failed" }
}

Write-Step "Building the game runtime and starting the panel"
& docker compose create --build cs2-game
if ($LASTEXITCODE -ne 0) { throw "Failed to create cs2-game" }
& docker compose up -d --build --no-deps panel
if ($LASTEXITCODE -ne 0) { throw "Failed to start the panel" }

& docker compose ps -a
Write-Host ""
Write-Host "Setup complete. The panel is running and cs2-game is stopped until a mode is selected." -ForegroundColor Green
Write-Host "Panel: http://127.0.0.1:$(Get-DotEnvValue 'PANEL_PORT')"
