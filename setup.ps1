$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example."
    Write-Host "Review the values in .env before exposing the server publicly."
}

docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "compose.yml is invalid"
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
Write-Host "Open the panel, select a mode, and press Start."
