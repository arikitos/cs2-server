# CS2 Manager V3 — rollback script (Windows / Docker Desktop)
# ==========================================================
# Restores compose.yml / .env / panel / modes / data from a backup folder
# created by migrate.ps1, then rebuilds and restarts the panel. Because the
# persistent game install and plugin mounts are untouched, rollback is config-only.
#
# Usage:  .\manager\scripts\rollback.ps1 -Backup manager\backups\pre-v3-YYYYMMDD-HHMMSS

param(
    [Parameter(Mandatory = $true)][string]$Backup
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "../..")

if (-not (Test-Path $Backup)) { throw "Backup folder not found: $Backup" }

Write-Host "Stopping game services and panel..." -ForegroundColor Yellow
docker compose stop cs2-faceit cs2-retakes cs2-heroshift panel 2>$null

foreach ($item in @("compose.yml", ".env")) {
    $src = Join-Path $Backup $item
    if (Test-Path $src) { Copy-Item $src $item -Force; Write-Host "restored $item" }
}
foreach ($dir in @("panel", "modes", "data")) {
    $src = Join-Path $Backup $dir
    $dest = "manager/$dir"
    if (Test-Path $src) {
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Copy-Item $src $dest -Recurse -Force
        Write-Host "restored $dest/"
    }
}

Write-Host "Rebuilding panel and recreating game services from restored config..." -ForegroundColor Cyan
docker compose build panel
docker compose create cs2-faceit cs2-retakes 2>$null
docker compose up -d panel
Write-Host "Rollback complete from $Backup" -ForegroundColor Green
