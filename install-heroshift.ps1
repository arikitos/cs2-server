[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$PackagePath,

    [switch]$StageOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$ReleaseRelative = "./manager/releases/heroshift/current"
$ReleaseParent = Join-Path $ProjectRoot "manager\releases\heroshift"
$ReleaseRoot = Join-Path $ReleaseParent "current"
$BackupParent = Join-Path $ProjectRoot "manager\backups"
$EnvPath = Join-Path $ProjectRoot ".env"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"

function Resolve-HeroShiftPackage {
    param([string]$RequestedPath)

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $candidate = $RequestedPath
        if (-not [System.IO.Path]::IsPathRooted($candidate)) {
            $candidate = Join-Path $ProjectRoot $candidate
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Package not found: $candidate"
        }
        return (Resolve-Path -LiteralPath $candidate).Path
    }

    $candidates = @(
        Get-ChildItem -LiteralPath $ProjectRoot -File -Filter "HeroShift-v*.zip" |
            ForEach-Object {
                if ($_.Name -match '^HeroShift-v(?<Version>\d+\.\d+\.\d+)\.zip$') {
                    [pscustomobject]@{
                        Path = $_.FullName
                        Version = [version]$Matches.Version
                    }
                }
            } |
            Sort-Object Version -Descending
    )

    if ($candidates.Count -eq 0) {
        throw "No HeroShift package found in the repository root. Expected HeroShift-vX.Y.Z.zip"
    }

    return $candidates[0].Path
}

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
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

function Get-ZipEntrySha256 {
    param([Parameter(Mandatory = $true)]$Entry)

    $stream = $Entry.Open()
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (($sha.ComputeHash($stream) | ForEach-Object { $_.ToString("x2") }) -join "")
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
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

$PackagePath = Resolve-HeroShiftPackage -RequestedPath $PackagePath
$PackageName = Split-Path -Leaf $PackagePath
$ArchiveSha256 = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($PackagePath)
try {
    $entries = @{}
    foreach ($entry in $archive.Entries) {
        $name = $entry.FullName.Replace("\", "/")
        if (
            $name.StartsWith("/") -or
            $name.StartsWith("\") -or
            $name -match '(^|/)\.\.(/|$)' -or
            $entry.FullName.Contains("\")
        ) {
            throw "Unsafe ZIP path: $($entry.FullName)"
        }
        $entries[$name.TrimEnd('/')] = $entry
    }

    if (-not $entries.ContainsKey("package-manifest.json")) {
        throw "package-manifest.json is missing"
    }

    $manifestStream = $entries["package-manifest.json"].Open()
    $reader = [System.IO.StreamReader]::new($manifestStream)
    try {
        $manifest = $reader.ReadToEnd() | ConvertFrom-Json
    }
    finally {
        $reader.Dispose()
        $manifestStream.Dispose()
    }

    if ($manifest.package -ne "HeroShift") {
        throw "Package manifest is not HeroShift"
    }

    $Version = [string]$manifest.version
    if ($Version -notmatch '^v\d+\.\d+\.\d+$') {
        throw "Unsupported HeroShift version: $Version"
    }

    $ExpectedPackageName = "HeroShift-$Version.zip"
    if ($PackageName -ne $ExpectedPackageName) {
        throw "Package filename must be $ExpectedPackageName, got $PackageName"
    }

    if (-not $manifest.files -or $manifest.files.Count -eq 0) {
        throw "Package manifest has no files"
    }

    $seen = @{}
    foreach ($row in $manifest.files) {
        $relative = ([string]$row.path).Replace("\", "/")
        if (
            [string]::IsNullOrWhiteSpace($relative) -or
            $relative.StartsWith("/") -or
            $relative -match '(^|/)\.\.(/|$)'
        ) {
            throw "Unsafe manifest path: $relative"
        }
        if ($seen.ContainsKey($relative)) {
            throw "Duplicate manifest path: $relative"
        }
        $seen[$relative] = $true

        if (-not $entries.ContainsKey($relative)) {
            throw "Manifest file is missing: $relative"
        }
        $entry = $entries[$relative]
        if ($entry.Length -ne [int64]$row.size) {
            throw "Manifest size mismatch: $relative"
        }
        $actualHash = Get-ZipEntrySha256 -Entry $entry
        if ($actualHash -ne ([string]$row.sha256).ToLowerInvariant()) {
            throw "Manifest SHA256 mismatch: $relative"
        }
    }

    $requiredPaths = @(
        "addons/counterstrikesharp/plugins/HeroShift",
        "addons/counterstrikesharp/gamedata/HeroShift.gamedata.json",
        "addons/metamod/RayTrace.vdf",
        "addons/RayTrace",
        "addons/counterstrikesharp/plugins/RayTraceImpl",
        "addons/counterstrikesharp/shared/RayTraceApi"
    )
    foreach ($required in $requiredPaths) {
        $found = $false
        foreach ($name in $entries.Keys) {
            if ($name -eq $required -or $name.StartsWith("$required/")) {
                $found = $true
                break
            }
        }
        if (-not $found) {
            throw "Required package path is missing: $required"
        }
    }
}
finally {
    $archive.Dispose()
}

$SkipPackageDeployment = $false
$MarkerPath = Join-Path $ReleaseRoot "installed-release.json"
if (Test-Path -LiteralPath $MarkerPath -PathType Leaf) {
    try {
        $marker = Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json
    }
    catch {
        $marker = $null
    }
    if (
        $null -ne $marker -and
        $marker.archive_sha256 -eq $ArchiveSha256 -and
        $marker.version -eq $Version
    ) {
        if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
            Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
        }
        Set-DotEnvValue -Path $EnvPath -Name "HEROSHIFT_RELEASE_PATH" -Value $ReleaseRelative
        Write-Host "HeroShift $Version is already installed from $PackageName"
        if ($StageOnly) {
            return
        }
        $SkipPackageDeployment = $true
    }
}

if (-not $SkipPackageDeployment) {
    New-Item -ItemType Directory -Path $ReleaseParent -Force | Out-Null
    New-Item -ItemType Directory -Path $BackupParent -Force | Out-Null
    $TempRoot = Join-Path $ReleaseParent (".install-" + [guid]::NewGuid().ToString("N"))
    $ExtractRoot = Join-Path $TempRoot "package"
    $StagingRoot = Join-Path $TempRoot "release"
    New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $StagingRoot -Force | Out-Null

    try {
        Expand-Archive -LiteralPath $PackagePath -DestinationPath $ExtractRoot -Force

        Copy-ReleasePath `
            -Source (Join-Path $ExtractRoot "addons\counterstrikesharp\plugins\HeroShift") `
            -Destination (Join-Path $StagingRoot "plugins\HeroShift")
        Copy-ReleasePath `
            -Source (Join-Path $ExtractRoot "addons\counterstrikesharp\gamedata\HeroShift.gamedata.json") `
            -Destination (Join-Path $StagingRoot "gamedata\HeroShift.gamedata.json")
        Copy-ReleasePath `
            -Source (Join-Path $ExtractRoot "addons\metamod\RayTrace.vdf") `
            -Destination (Join-Path $StagingRoot "utils\RayTrace\addons\metamod\RayTrace.vdf")
        Copy-ReleasePath `
            -Source (Join-Path $ExtractRoot "addons\RayTrace") `
            -Destination (Join-Path $StagingRoot "utils\RayTrace\addons\RayTrace")
        Copy-ReleasePath `
            -Source (Join-Path $ExtractRoot "addons\counterstrikesharp\plugins\RayTraceImpl") `
            -Destination (Join-Path $StagingRoot "utils\RayTrace\addons\counterstrikesharp\plugins\RayTraceImpl")
        Copy-ReleasePath `
            -Source (Join-Path $ExtractRoot "addons\counterstrikesharp\shared\RayTraceApi") `
            -Destination (Join-Path $StagingRoot "utils\RayTrace\addons\counterstrikesharp\shared\RayTraceApi")

        Copy-Item `
            -LiteralPath (Join-Path $ExtractRoot "package-manifest.json") `
            -Destination (Join-Path $StagingRoot "package-manifest.json") `
            -Force

        $notice = Join-Path $ExtractRoot "THIRD_PARTY_NOTICES.md"
        if (Test-Path -LiteralPath $notice -PathType Leaf) {
            Copy-Item -LiteralPath $notice -Destination (Join-Path $StagingRoot "THIRD_PARTY_NOTICES.md") -Force
        }
        $licenses = Join-Path $ExtractRoot "licenses"
        if (Test-Path -LiteralPath $licenses -PathType Container) {
            Copy-Item -LiteralPath $licenses -Destination (Join-Path $StagingRoot "licenses") -Recurse -Force
        }

        $installedMarker = [ordered]@{
            package = "HeroShift"
            version = $Version
            archive_sha256 = $ArchiveSha256
            source_archive = $PackageName
            installed_at_utc = [DateTime]::UtcNow.ToString("o")
        } | ConvertTo-Json
        [System.IO.File]::WriteAllText(
            (Join-Path $StagingRoot "installed-release.json"),
            ($installedMarker + "`n"),
            [System.Text.UTF8Encoding]::new($false)
        )

        if (Test-Path -LiteralPath $ReleaseRoot -PathType Container) {
            $PreviousVersion = "unknown"
            try {
                $previousMarker = Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json
                if ($previousMarker.version) {
                    $PreviousVersion = [string]$previousMarker.version
                }
            }
            catch {
            }

            $timestamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
            $backup = Join-Path $BackupParent "heroshift-$PreviousVersion-$timestamp"
            Move-Item -LiteralPath $ReleaseRoot -Destination $backup
            Write-Host "Previous HeroShift overlay backed up to $backup"
        }

        Move-Item -LiteralPath $StagingRoot -Destination $ReleaseRoot
    }
    finally {
        if (Test-Path -LiteralPath $TempRoot) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force
        }
    }

    if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $EnvExamplePath -PathType Leaf)) {
            throw "Missing $EnvExamplePath"
        }
        Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    }
    Set-DotEnvValue -Path $EnvPath -Name "HEROSHIFT_RELEASE_PATH" -Value $ReleaseRelative

    Write-Host "Installed verified HeroShift $Version from $PackageName"
    Write-Host "Active overlay: $ReleaseRoot"
}

if ($StageOnly) {
    Write-Host "HeroShift was staged. Docker containers were not changed."
    return
}

Push-Location $ProjectRoot
try {
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "compose.yml is invalid"
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
        throw "Failed to recreate the panel"
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

Write-Host "HeroShift is installed. No Docker image was rebuilt."
if ($wasRunning) {
    Write-Host "The game container was recreated so the new files are active."
}
else {
    Write-Host "The game container remains stopped. Start HeroShift from the panel."
}
