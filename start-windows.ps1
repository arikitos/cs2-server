$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
# Create the four game services (stopped) from the pinned runtime image, then
# launch the panel. The updater stays in the "maintenance" profile (not started).
docker compose create cs2-faceit cs2-retakes cs2-superheroes cs2-gungame
docker compose up -d --build panel
Write-Host "Panel started. Check PANEL_BIND and PANEL_PORT in .env"
