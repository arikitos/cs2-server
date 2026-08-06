# Safe migration from per-mode containers to one cs2-game runtime.
# This script changes Docker container state; run it only after reviewing the diff.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "../..")

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example; configure it before production use." -ForegroundColor Yellow
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "manager/backups/pre-single-runtime-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($item in @("compose.yml", ".env", ".env.example", "CHANGELOG.md", "README.md")) {
    if (Test-Path $item) { Copy-Item $item (Join-Path $backup (Split-Path $item -Leaf)) }
}
foreach ($dir in @("manager/panel", "manager/modes", "manager/data", "manager/runtime", "manager/shared")) {
    if (Test-Path $dir) { Copy-Item $dir (Join-Path $backup (Split-Path $dir -Leaf)) -Recurse }
}
Write-Host "Backup written to $backup" -ForegroundColor Green

docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "compose.yml is invalid" }

# The old service names are absent from the new compose file, so address their
# concrete containers directly. Stop gracefully, then remove only known game
# containers; the persistent CS2 bind mount is not deleted.
foreach ($name in @("cs2-faceit", "cs2-retakes", "cs2-heroshift", "cs2-game")) {
    docker container inspect $name *> $null
    if ($LASTEXITCODE -eq 0) {
        docker stop --time 20 $name *> $null
        docker rm $name *> $null
        Write-Host "removed old game container $name"
    }
}

docker compose build cs2-game panel
docker compose --profile maintenance build cs2-updater cs2-modinstaller
docker compose create cs2-game
docker compose up -d --force-recreate panel

Write-Host "Migration complete. One stopped cs2-game container is ready." -ForegroundColor Green
Write-Host "Open the panel, select a mode, then start it." -ForegroundColor Green
