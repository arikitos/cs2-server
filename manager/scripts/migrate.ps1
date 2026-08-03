# CS2 Manager V3 — migration script (Windows / Docker Desktop)
# ============================================================
# Safe, idempotent migration to the V3 runtime/updater architecture.
#  1. Backs up config (NOT the 69GB install).
#  2. Builds the pinned runtime image + updater image + panel.
#  3. Creates the four game services (stopped) and starts the panel.
# The updater stays in the "maintenance" profile and is never started here.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "../..")

if (-not (Test-Path ".env")) {
    Write-Host "No .env found; copying from .env.example. Edit it before continuing." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

# --- 1. Backup ---
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "manager/backups/pre-v3-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($item in @("compose.yml", ".env", ".env.example")) {
    if (Test-Path $item) { Copy-Item $item (Join-Path $backup $item) }
}
foreach ($dir in @("manager/panel", "manager/modes", "manager/data")) {
    if (Test-Path $dir) { Copy-Item $dir (Join-Path $backup (Split-Path $dir -Leaf)) -Recurse }
}
$gameinfo = Join-Path ([Environment]::GetEnvironmentVariable("CS2_DATA_PATH")) "game/csgo/gameinfo.gi"
New-Item -ItemType Directory -Force -Path (Join-Path $backup "server-critical") | Out-Null
Write-Host "Backup written to $backup" -ForegroundColor Green

# --- 2. Validate compose ---
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "compose.yml is invalid" }

# --- 3. Build images (runtime is shared by all game services) ---
Write-Host "Building runtime + updater + panel images..." -ForegroundColor Cyan
docker compose build
docker compose --profile maintenance build cs2-updater

# --- 4. Create game services (stopped), start the panel ---
docker compose create cs2-faceit cs2-retakes cs2-superheroes cs2-gungame
docker compose up -d panel

Write-Host "Migration complete. Panel at http://127.0.0.1:$((Get-Content .env | Select-String '^PANEL_PORT=' ) -replace 'PANEL_PORT=','')" -ForegroundColor Green
Write-Host "Game services are created but stopped. Start a mode from the panel." -ForegroundColor Green
Write-Host "The updater is in the 'maintenance' profile and is NOT running (correct)." -ForegroundColor Green
