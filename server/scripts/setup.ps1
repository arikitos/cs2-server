[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
Set-Location -LiteralPath $projectRoot

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

$projectPath = [IO.Path]::GetFullPath($projectRoot).Replace("\", "/")
$defaultDataPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "server/cs2")).Replace("\", "/")

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
    $dataPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $dataPath))
}
New-Item -ItemType Directory -Force -Path $dataPath, "server/state/runtime", "server/state/configs", "server/state/backups" | Out-Null

Write-Step "Validating Docker Compose configuration"
& docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "compose.yml or .env is invalid" }

Write-Step "Saving server configuration for installation from the panel"
$runtimeConfig = & docker compose --profile game --profile maintenance config --format json
if ($LASTEXITCODE -ne 0) { throw "Failed to resolve server configuration" }
Write-Utf8File "server/state/runtime/compose-runtime.json.tmp" ($runtimeConfig -join "`n")
Move-Item -Force "server/state/runtime/compose-runtime.json.tmp" "server/state/runtime/compose-runtime.json"

Write-Step "Preparing Python downloads using existing Windows HTTPS trust"
. (Join-Path $PSScriptRoot "prepare-panel-certificates.ps1")
Prepare-PanelCertificates -ProjectRoot $projectRoot | Out-Null

Write-Step "Building and starting only the panel (no game downloads)"
& docker compose up -d --build --no-deps panel
if ($LASTEXITCODE -ne 0) { throw "Failed to start the panel" }

$panelPort = Get-DotEnvValue "PANEL_PORT"
if (-not $panelPort) { $panelPort = "8080" }
$panelBind = Get-DotEnvValue "PANEL_BIND"
if (-not $panelBind -or $panelBind -eq "0.0.0.0") { $panelBind = "127.0.0.1" }
$panelUrl = "http://${panelBind}:${panelPort}"
Write-Step "Waiting for the panel"
$deadline = [DateTime]::UtcNow.AddSeconds(60)
$panelReady = $false
while ([DateTime]::UtcNow -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$panelUrl/healthz" -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $panelReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $panelReady) {
    throw "Panel did not become ready. Check: docker compose logs --tail 100 panel"
}

Write-Host ""
Write-Host "Panel ready. Install the server from Maintenance > Install server when you are ready." -ForegroundColor Green
Write-Host "Panel: $panelUrl"
Write-Host "Login with PANEL_USERNAME and PANEL_PASSWORD from .env."
Start-Process $panelUrl
