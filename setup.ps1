[CmdletBinding()]
param(
    [switch]$SkipGameInstall,
    [switch]$SkipFrameworkInstall
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function New-HexSecret {
    param([int]$Bytes = 24)
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToHexString($buffer).ToLowerInvariant()
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

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required but was not found in PATH"
}

$projectPath = [IO.Path]::GetFullPath($PSScriptRoot).Replace("\", "/")
$defaultDataPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "server/cs2")).Replace("\", "/")

if (-not (Test-Path ".env")) {
    $envText = Get-Content -LiteralPath ".env.example" -Raw
    $envText = Set-DotEnvValue $envText "PROJECT_PATH" $projectPath
    $envText = Set-DotEnvValue $envText "CS2_DATA_PATH" $defaultDataPath
    $envText = Set-DotEnvValue $envText "PANEL_PASSWORD" (New-HexSecret 18)
    $envText = Set-DotEnvValue $envText "CS2_RCON_PASSWORD" (New-HexSecret 18)
    Set-Content -LiteralPath ".env" -Value $envText -NoNewline
    Write-Host "Created .env with generated panel and RCON passwords."
} else {
    $envText = Get-Content -LiteralPath ".env" -Raw
    if ($envText -match "(?m)^MANAGER_PATH=") {
        $legacyPath = Get-DotEnvValue "MANAGER_PATH"
        $envText = [Regex]::Replace($envText, "(?m)^MANAGER_PATH=.*\r?\n?", "")
        $newProjectPath = if ($legacyPath) { (Split-Path $legacyPath -Parent).Replace("\", "/") } else { $projectPath }
        $envText = Set-DotEnvValue $envText "PROJECT_PATH" $newProjectPath
    }
    if (-not (Get-DotEnvValue "PROJECT_PATH")) {
        $envText = Set-DotEnvValue $envText "PROJECT_PATH" $projectPath
    }
    if (-not (Get-DotEnvValue "CS2_DATA_PATH")) {
        $envText = Set-DotEnvValue $envText "CS2_DATA_PATH" $defaultDataPath
    }
    if (-not (Get-DotEnvValue "PANEL_PASSWORD")) {
        $envText = Set-DotEnvValue $envText "PANEL_PASSWORD" (New-HexSecret 18)
    }
    if (-not (Get-DotEnvValue "CS2_RCON_PASSWORD")) {
        $envText = Set-DotEnvValue $envText "CS2_RCON_PASSWORD" (New-HexSecret 18)
    }
    Set-Content -LiteralPath ".env" -Value $envText -NoNewline
}

$dataPath = Get-DotEnvValue "CS2_DATA_PATH"
if (-not [IO.Path]::IsPathRooted($dataPath)) {
    $dataPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $dataPath))
}
New-Item -ItemType Directory -Force -Path $dataPath, "server/state/runtime", "server/state/configs", "server/state/backups" | Out-Null

docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "compose.yml or .env is invalid" }

docker compose --profile maintenance build cs2-updater cs2-modinstaller
if ($LASTEXITCODE -ne 0) { throw "Failed to build maintenance images" }

$gameBinary = Join-Path $dataPath "game/bin/linuxsteamrt64/cs2"
if (-not $SkipGameInstall -and -not (Test-Path $gameBinary)) {
    docker compose --profile maintenance run --rm -e CS2_UPDATER_MODE=update -e "CS2_UPDATER_CONFIRM=UPDATE CS2" cs2-updater
    if ($LASTEXITCODE -ne 0) { throw "SteamCMD installation failed" }
}
if (-not (Test-Path $gameBinary)) {
    throw "CS2 is not installed at $dataPath. Run setup.ps1 without -SkipGameInstall."
}

if (-not $SkipFrameworkInstall) {
    docker compose --profile maintenance run --rm cs2-modinstaller
    if ($LASTEXITCODE -ne 0) { throw "Metamod or CounterStrikeSharp installation failed" }
    docker compose --profile maintenance run --rm -e CS2_UPDATER_MODE=repair-metamod -e "CS2_UPDATER_CONFIRM=UPDATE CS2" cs2-updater
    if ($LASTEXITCODE -ne 0) { throw "Metamod activation failed" }
}

docker compose create --build cs2-game
if ($LASTEXITCODE -ne 0) { throw "Failed to create cs2-game" }
docker compose up -d --build --no-deps panel
if ($LASTEXITCODE -ne 0) { throw "Failed to start the panel" }

docker compose ps -a
Write-Host ""
Write-Host "Setup complete. The panel is running and cs2-game is stopped until a mode is selected."
Write-Host "Panel: http://127.0.0.1:$(Get-DotEnvValue 'PANEL_PORT')"
