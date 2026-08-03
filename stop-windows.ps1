$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
docker compose stop cs2-faceit cs2-retakes cs2-superheroes cs2-gungame panel
