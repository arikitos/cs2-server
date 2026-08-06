$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example."
    Write-Host "Review the values in .env before exposing the server publicly."
}

$packageArchives = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "installs") -Filter "*.zip" -File -Recurse -ErrorAction SilentlyContinue)
if ($packageArchives.Count -gt 0) {
    & (Join-Path $PSScriptRoot "update.ps1") -NoRestart
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
