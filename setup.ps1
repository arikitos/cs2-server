$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "compose.yml is invalid" }
docker compose create cs2-game
docker compose up -d --build panel
Write-Host "Panel started. Select a mode to deploy and start cs2-game."
