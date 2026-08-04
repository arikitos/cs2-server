[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$PackagePath,

    [Parameter(Position = 1)]
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,

    [switch]$StageOnly
)

$ErrorActionPreference = "Stop"
$ExpectedZipSha256 = "42e4672e48e8b8b460180648a2f2508787b6f77896323cfe594661c692507c7b"
$ExpectedVersion = "v1.0.0"
$ReleaseRelative = "./manager/releases/heroshift/v1.0.0"

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path $Path) {
        foreach ($line in Get-Content -LiteralPath $Path) {
            $lines.Add($line)
        }
    }

    $replacement = "$Name=$Value"
    $replaced = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([regex]::Escape($Name))=") {
            $lines[$index] = $replacement
            $replaced = $true
        }
    }

    if (-not $replaced) {
        if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -ne "") {
            $lines.Add("")
        }
        $lines.Add($replacement)
    }

    [System.IO.File]::WriteAllText(
        $Path,
        (($lines -join "`n") + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Copy-ReleasePath {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Required package path is missing: $Source"
    }

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if (Test-Path -LiteralPath $Source -PathType Container) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    }
    else {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PackagePath = (Resolve-Path -LiteralPath $PackagePath).Path
$ComposePath = Join-Path $ProjectRoot "compose.yml"
$EnvPath = Join-Path $ProjectRoot ".env"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"
$ReleaseParent = Join-Path $ProjectRoot "manager\releases\heroshift"
$ReleaseRoot = Join-Path $ReleaseParent "v1.0.0"
$BackupParent = Join-Path $ProjectRoot "manager\backups"

if (-not (Test-Path -LiteralPath $ComposePath -PathType Leaf)) {
    throw "compose.yml was not found under $ProjectRoot"
}

$actualZipHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualZipHash -ne $ExpectedZipSha256) {
    throw "Unexpected package SHA256: $actualZipHash"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($PackagePath)
try {
    foreach ($entry in $archive.Entries) {
        $name = $entry.FullName.Replace("\", "/")
        if ($name.StartsWith("/") -or $name -match "(^|/)\.\.(/|$)") {
            throw "Unsafe ZIP path: $name"
        }
    }
}
finally {
    $archive.Dispose()
}

New-Item -ItemType Directory -Path $ReleaseParent -Force | Out-Null
New-Item -ItemType Directory -Path $BackupParent -Force | Out-Null
$tempRoot = Join-Path $ReleaseParent (".install-" + [guid]::NewGuid().ToString("N"))
$extractRoot = Join-Path $tempRoot "package"
$stagingRoot = Join-Path $tempRoot "release"
New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

try {
    Expand-Archive -LiteralPath $PackagePath -DestinationPath $extractRoot -Force

    $manifestPath = Join-Path $extractRoot "package-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "package-manifest.json is missing"
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.package -ne "HeroShift") {
        throw "Package manifest is not HeroShift"
    }
    if ($manifest.version -ne $ExpectedVersion) {
        throw "Expected $ExpectedVersion, got $($manifest.version)"
    }
    if (-not $manifest.files -or $manifest.files.Count -eq 0) {
        throw "Package manifest has no files"
    }

    foreach ($row in $manifest.files) {
        $relative = [string]$row.path
        $local = Join-Path $extractRoot ($relative.Replace("/", [System.IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $local -PathType Leaf)) {
            throw "Manifest file is missing: $relative"
        }
        $item = Get-Item -LiteralPath $local
        if ($item.Length -ne [int64]$row.size) {
            throw "Manifest size mismatch: $relative"
        }
        $hash = (Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$row.sha256).ToLowerInvariant()) {
            throw "Manifest SHA256 mismatch: $relative"
        }
    }

    Copy-ReleasePath `
        -Source (Join-Path $extractRoot "addons\counterstrikesharp\plugins\HeroShift") `
        -Destination (Join-Path $stagingRoot "plugins\HeroShift")
    Copy-ReleasePath `
        -Source (Join-Path $extractRoot "addons\counterstrikesharp\gamedata\HeroShift.gamedata.json") `
        -Destination (Join-Path $stagingRoot "gamedata\HeroShift.gamedata.json")
    Copy-ReleasePath `
        -Source (Join-Path $extractRoot "addons\metamod\RayTrace.vdf") `
        -Destination (Join-Path $stagingRoot "utils\RayTrace\addons\metamod\RayTrace.vdf")
    Copy-ReleasePath `
        -Source (Join-Path $extractRoot "addons\RayTrace") `
        -Destination (Join-Path $stagingRoot "utils\RayTrace\addons\RayTrace")
    Copy-ReleasePath `
        -Source (Join-Path $extractRoot "addons\counterstrikesharp\plugins\RayTraceImpl") `
        -Destination (Join-Path $stagingRoot "utils\RayTrace\addons\counterstrikesharp\plugins\RayTraceImpl")
    Copy-ReleasePath `
        -Source (Join-Path $extractRoot "addons\counterstrikesharp\shared\RayTraceApi") `
        -Destination (Join-Path $stagingRoot "utils\RayTrace\addons\counterstrikesharp\shared\RayTraceApi")

    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stagingRoot "package-manifest.json") -Force
    $notice = Join-Path $extractRoot "THIRD_PARTY_NOTICES.md"
    if (Test-Path -LiteralPath $notice -PathType Leaf) {
        Copy-Item -LiteralPath $notice -Destination (Join-Path $stagingRoot "THIRD_PARTY_NOTICES.md") -Force
    }
    $licenses = Join-Path $extractRoot "licenses"
    if (Test-Path -LiteralPath $licenses -PathType Container) {
        Copy-Item -LiteralPath $licenses -Destination (Join-Path $stagingRoot "licenses") -Recurse -Force
    }

    $marker = [ordered]@{
        package = "HeroShift"
        version = $ExpectedVersion
        archive_sha256 = $ExpectedZipSha256
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText(
        (Join-Path $stagingRoot "installed-release.json"),
        ($marker + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )

    $existingReleases = @(
        Get-ChildItem -LiteralPath $ReleaseParent -Directory |
            Where-Object { $_.Name -like "v*" }
    )
    if ($existingReleases.Count -gt 0) {
        $timestamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
        $backupPath = Join-Path $BackupParent "heroshift-release-$timestamp"
        New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
        foreach ($existing in $existingReleases) {
            Move-Item -LiteralPath $existing.FullName -Destination $backupPath
        }
        Write-Host "Previous release overlays backed up to $backupPath"
    }

    Move-Item -LiteralPath $stagingRoot -Destination $ReleaseRoot
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $EnvPath)) {
    Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
}
Set-DotEnvValue -Path $EnvPath -Name "HEROSHIFT_RELEASE_PATH" -Value $ReleaseRelative

if ($StageOnly) {
    Write-Host "HeroShift $ExpectedVersion is staged as the active release overlay."
    return
}

Push-Location $ProjectRoot
try {
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "compose.yml is invalid after setting HEROSHIFT_RELEASE_PATH"
    }

    $gameExists = $false
    $wasRunning = $false
    $state = docker inspect --format "{{.State.Running}}" cs2-game 2>$null
    if ($LASTEXITCODE -eq 0) {
        $gameExists = $true
        $wasRunning = ($state.Trim().ToLowerInvariant() -eq "true")
    }

    docker compose up -d --force-recreate --no-deps panel
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to recreate the panel with the HeroShift release overlay"
    }

    if ($wasRunning) {
        docker compose up -d --force-recreate --no-deps cs2-game
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to recreate the running game container"
        }
    }
    elseif ($gameExists) {
        docker compose create --force-recreate cs2-game
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to recreate the stopped game container"
        }
    }
    else {
        docker compose create cs2-game
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the game container"
        }
    }
}
finally {
    Pop-Location
}

Write-Host "HeroShift $ExpectedVersion is installed as the active release overlay."
if ($wasRunning) {
    Write-Host "The game container was recreated. Check panel health and game logs."
}
else {
    Write-Host "The game container remains stopped. Start or switch to HeroShift from the panel."
}
