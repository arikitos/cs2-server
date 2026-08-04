$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example."
    Write-Host "Review the values in .env before exposing the server publicly."
}

$heroShiftPackages = @(Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter "HeroShift-v*.zip")
if ($heroShiftPackages.Count -gt 0) {
    & (Join-Path $PSScriptRoot "install-heroshift.ps1") -StageOnly
}

$releaseSetting = @(
    Get-Content -LiteralPath (Join-Path $PSScriptRoot ".env") |
        Where-Object { $_ -match '^HEROSHIFT_RELEASE_PATH=' }
) | Select-Object -Last 1

$releaseValue = "./manager/releases/heroshift/current"
if ($releaseSetting) {
    $configuredValue = ($releaseSetting -split '=', 2)[1].Trim()
    if (-not [string]::IsNullOrWhiteSpace($configuredValue)) {
        $releaseValue = $configuredValue
    }
}

if ([System.IO.Path]::IsPathRooted($releaseValue)) {
    $releaseRoot = $releaseValue
}
else {
    $normalizedRelease = $releaseValue.Replace('/', [System.IO.Path]::DirectorySeparatorChar).TrimStart('.', '\', '/')
    $releaseRoot = Join-Path $PSScriptRoot $normalizedRelease
}

$heroShiftMarker = Join-Path $releaseRoot "installed-release.json"
if (-not (Test-Path -LiteralPath $heroShiftMarker -PathType Leaf)) {
    throw "HeroShift is not installed. Place HeroShift-vX.Y.Z.zip in the repository root and run .\install-heroshift.ps1"
}

docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "compose.yml is invalid"
}

docker compose --profile maintenance build cs2-updater
if ($LASTEXITCODE -ne 0) {
    throw "Failed to build the local cs2-updater image"
}

docker image inspect cs2-manager-updater:pinned *> $null
if ($LASTEXITCODE -ne 0) {
    throw "The local cs2-manager-updater:pinned image was not created"
}

docker compose create --build cs2-game
if ($LASTEXITCODE -ne 0) {
    throw "Failed to build or create cs2-game"
}

docker compose up -d --build --no-deps panel
if ($LASTEXITCODE -ne 0) {
    throw "Failed to build or start the panel"
}

docker compose ps -a
if ($LASTEXITCODE -ne 0) {
    throw "Failed to read Docker Compose status"
}

Write-Host ""
Write-Host "Panel started."
Write-Host "cs2-game is created but not started."
Write-Host "cs2-manager-updater:pinned is built locally."
Write-Host "Open the panel, select a mode, and press Start."
