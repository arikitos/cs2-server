# Restores a backup created by migrate.ps1 and recreates the service topology
# described by that backup's compose.yml. This changes Docker container state.
param(
    [Parameter(Mandatory = $true)][string]$Backup
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "../..")

if (-not (Test-Path $Backup)) { throw "Backup folder not found: $Backup" }

# Stop the single runtime before touching its deployed mode layer. Clean only
# paths recorded in the manager inventory; removing cs2-game then discards the
# container-local absolute /addons path used by RayTrace.
docker container inspect cs2-game *> $null
if ($LASTEXITCODE -eq 0) {
    docker stop --time 20 cs2-game *> $null
    docker run --rm --volumes-from cs2-game `
        --entrypoint /usr/local/bin/mode-applier `
        cs2-manager-runtime:pinned `
        --server-root /home/steam/cs2-dedicated `
        --inventory /home/steam/cs2-dedicated/.cs2-manager/managed-files.json `
        cleanup
    if ($LASTEXITCODE -ne 0) {
        throw "Managed mode cleanup failed; refusing to restore the old topology"
    }
}

foreach ($name in @("cs2-game", "cs2-faceit", "cs2-retakes", "cs2-heroshift", "cs2-panel")) {
    docker container inspect $name *> $null
    if ($LASTEXITCODE -eq 0) {
        docker stop --time 20 $name *> $null
        docker rm $name *> $null
    }
}

foreach ($item in @("compose.yml", ".env", ".env.example", "CHANGELOG.md", "README.md", "versions.json")) {
    $src = Join-Path $Backup $item
    if (Test-Path $src) {
        $dest = if ($item -eq "versions.json") { "manager/versions.json" } else { $item }
        Copy-Item $src $dest -Force
        Write-Host "restored $dest"
    }
}
foreach ($dir in @("panel", "modes", "data", "runtime", "updater", "shared")) {
    $src = Join-Path $Backup $dir
    $dest = "manager/$dir"
    if (Test-Path $src) {
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Copy-Item $src $dest -Recurse -Force
        Write-Host "restored $dest/"
    }
}

docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Restored compose.yml is invalid" }
docker compose build
docker compose create
docker compose up -d panel
Write-Host "Rollback complete from $Backup. Start the restored game service from the panel." -ForegroundColor Green
