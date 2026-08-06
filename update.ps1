[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string]$Mode,

    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string]$Component,

    [switch]$SharedOnly,
    [switch]$FetchLatest,
    [switch]$IncludeOptional,

    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string[]]$Source,

    [switch]$Force,
    [switch]$NoRestart,

    [ValidateRange(0, 20)]
    [int]$KeepBackups = 3
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = $PSScriptRoot
$InstallsRoot = Join-Path $ProjectRoot 'installs'
$ModesRoot = Join-Path $ProjectRoot 'manager\modes'
$SharedRoot = Join-Path $ProjectRoot 'manager\shared'
$BackupsRoot = Join-Path $ProjectRoot 'manager\backups\packages'
$DataRoot = Join-Path $ProjectRoot 'manager\data'
$LockPath = Join-Path $DataRoot 'package-update.lock'
$FetchScript = Join-Path $ProjectRoot 'fetch-releases.ps1'

if ($Mode -and $SharedOnly) {
    throw '-Mode and -SharedOnly cannot be used together.'
}

function Get-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $DefaultValue = $null
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $DefaultValue }
    return $property.Value
}

function ConvertTo-NormalizedVersion {
    param([Parameter(Mandatory = $true)][string]$Value)

    $normalized = $Value.Trim()
    if ($normalized.StartsWith('v', [System.StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring(1)
    }
    if ($normalized -notmatch '^\d+\.\d+\.\d+$') {
        throw "Unsupported package version '$Value'. Expected X.Y.Z or vX.Y.Z."
    }
    return [version]$normalized
}

function Test-SafeArchivePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    if ($Path.StartsWith('/') -or $Path.StartsWith('\')) { return $false }
    if ($Path.Contains('\')) { return $false }
    if ($Path -match '(^|/)\.\.(/|$)') { return $false }
    if ([System.IO.Path]::IsPathRooted($Path)) { return $false }

    $reservedNames = @('CON', 'PRN', 'AUX', 'NUL') +
        (1..9 | ForEach-Object { "COM$_" }) +
        (1..9 | ForEach-Object { "LPT$_" })
    foreach ($segment in ($Path -split '/')) {
        if (-not $segment -or $segment -in @('.', '..')) { return $false }
        if ($segment.EndsWith('.') -or $segment.EndsWith(' ')) { return $false }
        if ($segment.IndexOfAny([char[]]'<>:"|?*') -ge 0) { return $false }
        $deviceName = ($segment -split '\.', 2)[0].ToUpperInvariant()
        if ($deviceName -in $reservedNames) { return $false }
    }
    return $true
}

function Test-PathWithinInstallRoots {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Roots
    )

    foreach ($root in $Roots) {
        if ($Path -eq $root -or $Path.StartsWith("$root/")) { return $true }
    }
    return $false
}

function Assert-NonOverlappingRoots {
    param([Parameter(Mandatory = $true)][string[]]$Roots)

    for ($left = 0; $left -lt $Roots.Count; $left++) {
        for ($right = $left + 1; $right -lt $Roots.Count; $right++) {
            if (
                $Roots[$left] -eq $Roots[$right] -or
                $Roots[$left].StartsWith("$($Roots[$right])/") -or
                $Roots[$right].StartsWith("$($Roots[$left])/")
            ) {
                throw "Package install roots overlap: $($Roots[$left]) and $($Roots[$right])"
            }
        }
    }
}

function Get-ZipEntrySha256 {
    param([Parameter(Mandatory = $true)]$Entry)

    $stream = $Entry.Open()
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (($sha.ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }) -join '')
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Read-PackageCandidate {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$ArchiveFile)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchiveFile.FullName)
    try {
        $entries = @{}
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            $key = $name.TrimEnd('/')
            if (-not $key) { continue }
            if (-not (Test-SafeArchivePath -Path $key)) {
                throw "Unsafe ZIP path in $($ArchiveFile.Name): $($entry.FullName)"
            }
            if ($entries.ContainsKey($key)) {
                throw "Duplicate ZIP path in $($ArchiveFile.Name): $key"
            }
            $entries[$key] = $entry
        }

        if (-not $entries.ContainsKey('package-manifest.json')) {
            throw "package-manifest.json is missing from $($ArchiveFile.Name)"
        }

        $manifestStream = $entries['package-manifest.json'].Open()
        $reader = [System.IO.StreamReader]::new($manifestStream)
        try {
            $manifest = $reader.ReadToEnd() | ConvertFrom-Json
        }
        finally {
            $reader.Dispose()
            $manifestStream.Dispose()
        }

        $adapter = 'standard'
        $manifestPackageType = Get-ObjectProperty -Object $manifest -Name 'packageType'
        $manifestId = Get-ObjectProperty -Object $manifest -Name 'id'
        $manifestVersion = Get-ObjectProperty -Object $manifest -Name 'version'
        $manifestPackage = Get-ObjectProperty -Object $manifest -Name 'package'
        if ($manifestPackageType -and $manifestId -and $manifestVersion) {
            $packageType = ([string]$manifestPackageType).ToLowerInvariant()
            $id = ([string]$manifestId).ToLowerInvariant()
            $manifestComponent = Get-ObjectProperty -Object $manifest -Name 'component'
            $component = if ($manifestComponent) { ([string]$manifestComponent).ToLowerInvariant() } else { $id }
            $manifestName = Get-ObjectProperty -Object $manifest -Name 'name'
            $name = if ($manifestName) { [string]$manifestName } else { $component }
            $versionText = [string]$manifestVersion
            $manifestPayloadRoot = Get-ObjectProperty -Object $manifest -Name 'payloadRoot'
            $payloadRoot = if ($manifestPayloadRoot) {
                ([string]$manifestPayloadRoot).Replace('\', '/').Trim('/')
            }
            else {
                'payload'
            }
            $manifestInstallStrategy = Get-ObjectProperty -Object $manifest -Name 'installStrategy'
            $installStrategy = if ($manifestInstallStrategy) {
                ([string]$manifestInstallStrategy).ToLowerInvariant()
            }
            else {
                'replace-release'
            }
            $installRoots = @(
                Get-ObjectProperty -Object $manifest -Name 'installRoots' -DefaultValue @() |
                    ForEach-Object { ([string]$_).Replace('\', '/').Trim('/') }
            )
        }
        elseif ($manifestPackage -eq 'HeroShift' -and $manifestVersion) {
            $packageType = 'mode'
            $id = 'heroshift'
            $component = 'heroshift'
            $name = 'HeroShift'
            $versionText = [string]$manifestVersion
            $payloadRoot = ''
            $installStrategy = 'replace-release'
            $installRoots = @()
            $adapter = 'legacy-heroshift'
        }
        else {
            throw "Unsupported package manifest in $($ArchiveFile.Name)"
        }

        if ($packageType -notin @('mode', 'shared')) {
            throw "Unsupported packageType '$packageType' in $($ArchiveFile.Name)"
        }
        foreach ($identifier in @($id, $component)) {
            if ($identifier -notmatch '^[a-z0-9][a-z0-9-]*$') {
                throw "Unsafe package identifier '$identifier' in $($ArchiveFile.Name)"
            }
        }
        if ($installStrategy -notin @('replace-release', 'replace-roots')) {
            throw "Unsupported installStrategy '$installStrategy' in $($ArchiveFile.Name)"
        }
        if ($adapter -eq 'standard' -and (-not $payloadRoot -or -not (Test-SafeArchivePath -Path $payloadRoot))) {
            throw "Invalid payloadRoot in $($ArchiveFile.Name)"
        }
        if ($installStrategy -eq 'replace-roots') {
            if ($installRoots.Count -eq 0) {
                throw "replace-roots package has no installRoots in $($ArchiveFile.Name)"
            }
            foreach ($root in $installRoots) {
                if (-not (Test-SafeArchivePath -Path $root)) {
                    throw "Unsafe install root in $($ArchiveFile.Name): $root"
                }
            }
            Assert-NonOverlappingRoots -Roots $installRoots
        }
        elseif ($installRoots.Count -ne 0) {
            throw "replace-release package must not declare installRoots in $($ArchiveFile.Name)"
        }

        $version = ConvertTo-NormalizedVersion -Value $versionText
        $manifestFiles = Get-ObjectProperty -Object $manifest -Name 'files'
        if (-not $manifestFiles -or $manifestFiles.Count -eq 0) {
            throw "Package manifest has no files in $($ArchiveFile.Name)"
        }

        $seen = @{}
        foreach ($row in $manifestFiles) {
            $rowPath = Get-ObjectProperty -Object $row -Name 'path'
            $rowSize = Get-ObjectProperty -Object $row -Name 'size'
            $rowSha256 = Get-ObjectProperty -Object $row -Name 'sha256'
            if ($null -eq $rowPath -or $null -eq $rowSize -or $null -eq $rowSha256) {
                throw "Malformed manifest file entry in $($ArchiveFile.Name)"
            }
            $relative = ([string]$rowPath).Replace('\', '/')
            if (-not (Test-SafeArchivePath -Path $relative)) {
                throw "Unsafe manifest path in $($ArchiveFile.Name): $relative"
            }
            if ($seen.ContainsKey($relative)) {
                throw "Duplicate manifest path in $($ArchiveFile.Name): $relative"
            }
            $seen[$relative] = $true
            if (-not $entries.ContainsKey($relative)) {
                throw "Manifest file is missing from $($ArchiveFile.Name): $relative"
            }
            $entry = $entries[$relative]
            if ($entry.Length -ne [int64]$rowSize) {
                throw "Manifest size mismatch in $($ArchiveFile.Name): $relative"
            }
            $actualHash = Get-ZipEntrySha256 -Entry $entry
            if ($actualHash -ne ([string]$rowSha256).ToLowerInvariant()) {
                throw "Manifest SHA256 mismatch in $($ArchiveFile.Name): $relative"
            }
            if ($adapter -eq 'standard') {
                if (-not $relative.StartsWith("$payloadRoot/")) {
                    throw "Standard package file is outside payloadRoot in $($ArchiveFile.Name): $relative"
                }
                $payloadRelative = $relative.Substring($payloadRoot.Length).TrimStart('/')
                if (-not $payloadRelative) {
                    throw "Package file resolves to an empty payload path in $($ArchiveFile.Name)"
                }
                if (
                    $installStrategy -eq 'replace-roots' -and
                    -not (Test-PathWithinInstallRoots -Path $payloadRelative -Roots $installRoots)
                ) {
                    throw "Package file is outside installRoots in $($ArchiveFile.Name): $payloadRelative"
                }
            }
        }

        $undeclaredFiles = @(
            $entries.GetEnumerator() |
                Where-Object {
                    $_.Key -ne 'package-manifest.json' -and
                    -not $_.Value.FullName.EndsWith('/') -and
                    -not $seen.ContainsKey($_.Key)
                } |
                ForEach-Object { $_.Key }
        )
        if ($undeclaredFiles.Count -gt 0) {
            throw "Package contains files that are not declared in package-manifest.json in $($ArchiveFile.Name): $($undeclaredFiles -join ', ')"
        }

        if ($adapter -eq 'legacy-heroshift') {
            $required = @(
                'addons/counterstrikesharp/plugins/HeroShift/HeroShift.dll',
                'addons/counterstrikesharp/gamedata/HeroShift.gamedata.json',
                'addons/metamod/RayTrace.vdf',
                'addons/RayTrace/gamedata.json',
                'addons/counterstrikesharp/plugins/RayTraceImpl/RayTraceImpl.dll',
                'addons/counterstrikesharp/shared/RayTraceApi/RayTraceApi.dll'
            )
            foreach ($path in $required) {
                if (-not $entries.ContainsKey($path)) {
                    throw "Required HeroShift runtime path is missing from $($ArchiveFile.Name): $path"
                }
            }
        }

        return [pscustomobject]@{
            Archive = $ArchiveFile
            ArchiveSha256 = (Get-FileHash -LiteralPath $ArchiveFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            PackageType = $packageType
            Id = $id
            Component = $component
            Name = $name
            VersionText = $version.ToString(3)
            Version = $version
            Adapter = $adapter
            PayloadRoot = $payloadRoot
            InstallStrategy = $installStrategy
            InstallRoots = @($installRoots)
            Manifest = $manifest
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Get-InstallPaths {
    param([Parameter(Mandatory = $true)]$Candidate)

    if ($Candidate.PackageType -eq 'mode') {
        $componentRoot = Join-Path $ModesRoot $Candidate.Id
        if (-not (Test-Path -LiteralPath (Join-Path $componentRoot 'mode.json') -PathType Leaf)) {
            throw "Unknown mode package '$($Candidate.Id)'. Expected manager\modes\$($Candidate.Id)\mode.json"
        }
    }
    else {
        $componentRoot = Join-Path (Join-Path $SharedRoot 'components') $Candidate.Id
    }

    $markerDirectory = Join-Path $componentRoot 'packages'
    return [pscustomobject]@{
        ComponentRoot = $componentRoot
        ReleaseRoot = Join-Path $componentRoot 'release'
        MarkerDirectory = $markerDirectory
        MarkerPath = Join-Path $markerDirectory "$($Candidate.Component).json"
        BackupRoot = Join-Path (Join-Path (Join-Path $BackupsRoot $Candidate.PackageType) $Candidate.Id) $Candidate.Component
    }
}

function Convert-LegacyHeroShiftPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $prefixes = [ordered]@{
        'addons/counterstrikesharp/plugins/HeroShift/' = 'plugins/HeroShift/'
        'addons/counterstrikesharp/gamedata/HeroShift.gamedata.json' = 'gamedata/HeroShift.gamedata.json'
        'addons/metamod/RayTrace.vdf' = 'utils/RayTrace/addons/metamod/RayTrace.vdf'
        'addons/RayTrace/' = 'utils/RayTrace/addons/RayTrace/'
        'addons/counterstrikesharp/plugins/RayTraceImpl/' = 'utils/RayTrace/addons/counterstrikesharp/plugins/RayTraceImpl/'
        'addons/counterstrikesharp/shared/RayTraceApi/' = 'utils/RayTrace/addons/counterstrikesharp/shared/RayTraceApi/'
        'THIRD_PARTY_NOTICES.md' = '_meta/THIRD_PARTY_NOTICES.md'
        'licenses/' = '_meta/licenses/'
    }

    foreach ($entry in $prefixes.GetEnumerator()) {
        if ($Path -eq $entry.Key) { return $entry.Value }
        if ($entry.Key.EndsWith('/') -and $Path.StartsWith($entry.Key)) {
            return $entry.Value + $Path.Substring($entry.Key.Length)
        }
    }
    throw "Unsupported path in legacy HeroShift package: $Path"
}

function Expand-Candidate {
    param(
        [Parameter(Mandatory = $true)]$Candidate,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Candidate.Archive.FullName)
    try {
        $entries = @{}
        foreach ($entry in $archive.Entries) {
            $key = $entry.FullName.Replace('\', '/').TrimEnd('/')
            if ($key) { $entries[$key] = $entry }
        }

        $candidateFiles = Get-ObjectProperty -Object $Candidate.Manifest -Name 'files'
        foreach ($row in $candidateFiles) {
            $sourcePath = ([string](Get-ObjectProperty -Object $row -Name 'path')).Replace('\', '/')
            if ($Candidate.Adapter -eq 'standard') {
                $targetRelative = $sourcePath.Substring($Candidate.PayloadRoot.Length).TrimStart('/')
            }
            else {
                $targetRelative = Convert-LegacyHeroShiftPath -Path $sourcePath
            }
            if (-not (Test-SafeArchivePath -Path $targetRelative)) {
                throw "Unsafe extracted path: $targetRelative"
            }
            $target = Join-Path $Destination ($targetRelative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            $input = $entries[$sourcePath].Open()
            $output = [System.IO.File]::Open($target, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            try {
                $input.CopyTo($output)
            }
            finally {
                $output.Dispose()
                $input.Dispose()
            }
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Read-InstalledVersion {
    param([Parameter(Mandatory = $true)][string]$MarkerPath)

    if (-not (Test-Path -LiteralPath $MarkerPath -PathType Leaf)) { return $null }
    try {
        $marker = Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json
        $markerVersion = Get-ObjectProperty -Object $marker -Name 'version'
        if (-not $markerVersion) { return $null }
        return ConvertTo-NormalizedVersion -Value ([string]$markerVersion)
    }
    catch {
        throw "Invalid installed marker: $MarkerPath. $($_.Exception.Message)"
    }
}

function Write-InstalledMarker {
    param(
        [Parameter(Mandatory = $true)]$Candidate,
        [Parameter(Mandatory = $true)][string]$MarkerPath
    )

    $marker = [ordered]@{
        schemaVersion = 2
        packageType = $Candidate.PackageType
        id = $Candidate.Id
        component = $Candidate.Component
        name = $Candidate.Name
        version = $Candidate.VersionText
        managed = $true
        installStrategy = $Candidate.InstallStrategy
        installRoots = @($Candidate.InstallRoots)
        archiveSha256 = $Candidate.ArchiveSha256
        sourceArchive = $Candidate.Archive.Name
        installedAtUtc = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($MarkerPath, $marker + "`n", [System.Text.UTF8Encoding]::new($false))
}

function Remove-ExpiredBackups {
    param(
        [Parameter(Mandatory = $true)]$Candidate,
        [Parameter(Mandatory = $true)][int]$Keep
    )

    $paths = Get-InstallPaths -Candidate $Candidate
    if (-not (Test-Path -LiteralPath $paths.BackupRoot -PathType Container)) { return }

    try {
        $backups = @(Get-ChildItem -LiteralPath $paths.BackupRoot -Directory | Sort-Object LastWriteTimeUtc -Descending)
        $expired = if ($Keep -eq 0) { $backups } else { @($backups | Select-Object -Skip $Keep) }
        foreach ($backup in $expired) {
            Remove-Item -LiteralPath $backup.FullName -Recurse -Force
        }
    }
    catch {
        Write-Warning "Package update succeeded, but old backup cleanup failed for $($Candidate.PackageType)/$($Candidate.Id)/$($Candidate.Component): $($_.Exception.Message)"
    }
}

function Get-InstallTargets {
    param(
        [Parameter(Mandatory = $true)]$Candidate,
        [Parameter(Mandatory = $true)]$Paths,
        [Parameter(Mandatory = $true)][string]$StagedRelease
    )

    if ($Candidate.InstallStrategy -eq 'replace-release') {
        return @([pscustomobject]@{
            Relative = 'release'
            Staged = $StagedRelease
            Destination = $Paths.ReleaseRoot
        })
    }

    $targets = @()
    foreach ($root in $Candidate.InstallRoots) {
        $native = $root.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $staged = Join-Path $StagedRelease $native
        if (-not (Test-Path -LiteralPath $staged -PathType Container)) {
            throw "Package install root is missing after extraction: $root"
        }
        if (-not (Get-ChildItem -LiteralPath $staged -File -Recurse | Select-Object -First 1)) {
            throw "Package install root is empty after extraction: $root"
        }
        $targets += [pscustomobject]@{
            Relative = "release/$root"
            Staged = $staged
            Destination = Join-Path $Paths.ReleaseRoot $native
        }
    }
    return $targets
}

function Restore-Backup {
    param(
        [Parameter()][AllowEmptyCollection()][object[]]$BackedUpTargets = @(),
        [Parameter()][AllowEmptyCollection()][object[]]$InstallAttemptedTargets = @(),
        [Parameter()][string]$BackupPath,
        [Parameter(Mandatory = $true)][string]$MarkerPath,
        [Parameter(Mandatory = $true)][bool]$MarkerWriteAttempted,
        [Parameter(Mandatory = $true)][bool]$MarkerHadPrevious
    )

    foreach ($target in @($InstallAttemptedTargets)) {
        if (Test-Path -LiteralPath $target.Destination) {
            Remove-Item -LiteralPath $target.Destination -Recurse -Force
        }
    }

    if ($BackupPath) {
        foreach ($target in @($BackedUpTargets)) {
            $backupTarget = Join-Path $BackupPath ($target.Relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
            if (Test-Path -LiteralPath $backupTarget) {
                if (Test-Path -LiteralPath $target.Destination) {
                    Remove-Item -LiteralPath $target.Destination -Recurse -Force
                }
                New-Item -ItemType Directory -Path (Split-Path -Parent $target.Destination) -Force | Out-Null
                Move-Item -LiteralPath $backupTarget -Destination $target.Destination
            }
        }
    }

    if ($MarkerWriteAttempted) {
        $backupMarker = if ($BackupPath) { Join-Path $BackupPath 'installed.json' } else { $null }
        if ($MarkerHadPrevious -and $backupMarker -and (Test-Path -LiteralPath $backupMarker -PathType Leaf)) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $MarkerPath) -Force | Out-Null
            Copy-Item -LiteralPath $backupMarker -Destination $MarkerPath -Force
        }
        elseif (Test-Path -LiteralPath $MarkerPath -PathType Leaf) {
            Remove-Item -LiteralPath $MarkerPath -Force
        }
    }
}

function Install-Candidate {
    param([Parameter(Mandatory = $true)]$Candidate)

    $paths = Get-InstallPaths -Candidate $Candidate
    $installedVersion = Read-InstalledVersion -MarkerPath $paths.MarkerPath
    $comparison = if ($null -eq $installedVersion) { 1 } else { $Candidate.Version.CompareTo($installedVersion) }

    if (-not $Force -and $comparison -le 0) {
        $installedText = if ($null -eq $installedVersion) { 'unknown' } else { $installedVersion.ToString(3) }
        Write-Host "Skip $($Candidate.PackageType)/$($Candidate.Id)/$($Candidate.Component): installed=$installedText, available=$($Candidate.VersionText)"
        return $false
    }

    $action = if ($Force -and $comparison -le 0) { 'Reinstall' } else { 'Install' }
    $identity = "$($Candidate.PackageType)/$($Candidate.Id)/$($Candidate.Component)"
    if (-not $PSCmdlet.ShouldProcess($identity, "$action $($Candidate.VersionText)")) {
        return $false
    }

    New-Item -ItemType Directory -Path $DataRoot, $BackupsRoot, $paths.ComponentRoot, $paths.MarkerDirectory -Force | Out-Null
    $tempRoot = Join-Path $DataRoot ('.package-update-' + [guid]::NewGuid().ToString('N'))
    $stagedRelease = Join-Path $tempRoot 'release'
    New-Item -ItemType Directory -Path $stagedRelease -Force | Out-Null

    $backupPath = $null
    $targets = @()
    $backedUpTargets = @()
    $installAttemptedTargets = @()
    $markerHadPrevious = $false
    $markerWriteAttempted = $false
    try {
        Expand-Candidate -Candidate $Candidate -Destination $stagedRelease
        if (-not (Get-ChildItem -LiteralPath $stagedRelease -File -Recurse | Select-Object -First 1)) {
            throw "Package produced an empty release: $($Candidate.Archive.Name)"
        }
        $targets = @(Get-InstallTargets -Candidate $Candidate -Paths $paths -StagedRelease $stagedRelease)

        try {
            $markerHadPrevious = Test-Path -LiteralPath $paths.MarkerPath -PathType Leaf
            $hasExistingTarget = $false
            foreach ($target in $targets) {
                if (Test-Path -LiteralPath $target.Destination) {
                    $hasExistingTarget = $true
                    break
                }
            }
            if ($hasExistingTarget -or $markerHadPrevious) {
                $timestamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmssfff')
                $previous = if ($null -eq $installedVersion) { 'unknown' } else { $installedVersion.ToString(3) }
                $backupPath = Join-Path $paths.BackupRoot "$previous-$timestamp"
                New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
                foreach ($target in $targets) {
                    if (Test-Path -LiteralPath $target.Destination) {
                        $backupTarget = Join-Path $backupPath ($target.Relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
                        New-Item -ItemType Directory -Path (Split-Path -Parent $backupTarget) -Force | Out-Null
                        Move-Item -LiteralPath $target.Destination -Destination $backupTarget
                        $backedUpTargets += $target
                    }
                }
                if ($markerHadPrevious) {
                    Copy-Item -LiteralPath $paths.MarkerPath -Destination (Join-Path $backupPath 'installed.json') -Force
                }
            }

            foreach ($target in $targets) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $target.Destination) -Force | Out-Null
                $installAttemptedTargets += $target
                Move-Item -LiteralPath $target.Staged -Destination $target.Destination
            }
            $markerWriteAttempted = $true
            Write-InstalledMarker -Candidate $Candidate -MarkerPath $paths.MarkerPath
        }
        catch {
            Restore-Backup `
                -BackedUpTargets $backedUpTargets `
                -InstallAttemptedTargets $installAttemptedTargets `
                -BackupPath $backupPath `
                -MarkerPath $paths.MarkerPath `
                -MarkerWriteAttempted $markerWriteAttempted `
                -MarkerHadPrevious $markerHadPrevious
            throw
        }

        Write-Host "Installed $identity $($Candidate.VersionText) from $($Candidate.Archive.Name)"
        Remove-ExpiredBackups -Candidate $Candidate -Keep $KeepBackups
        return $true
    }
    finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

function Get-ActiveMode {
    $path = Join-Path $ProjectRoot 'manager\data\runtime\active-mode.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try {
        $state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $stateMode = Get-ObjectProperty -Object $state -Name 'mode'
        if ($stateMode) { return ([string]$stateMode).ToLowerInvariant() }
        return $null
    }
    catch { return $null }
}

function Restart-GameIfRequired {
    param(
        [Parameter()]
        [AllowEmptyCollection()]
        [object[]]$Updated = @()
    )

    if ($WhatIfPreference -or $NoRestart -or $Updated.Count -eq 0) { return }
    $activeMode = Get-ActiveMode
    $requiresRestart = $false
    foreach ($candidate in $Updated) {
        if ($candidate.PackageType -eq 'shared' -or ($candidate.PackageType -eq 'mode' -and $candidate.Id -eq $activeMode)) {
            $requiresRestart = $true
            break
        }
    }
    if (-not $requiresRestart) {
        Write-Host 'Updated packages do not affect the active mode. No restart is required.'
        return
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Warning 'Docker was not found. Restart cs2-game before using the updated package.'
        return
    }

    $running = docker inspect --format '{{.State.Running}}' cs2-game 2>$null
    if ($LASTEXITCODE -ne 0 -or $running.Trim().ToLowerInvariant() -ne 'true') {
        Write-Host 'cs2-game is stopped. The updated files will be deployed on the next start.'
        return
    }

    Push-Location $ProjectRoot
    try {
        docker compose up -d --force-recreate --no-deps cs2-game
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to recreate cs2-game after the package update.'
        }
    }
    finally {
        Pop-Location
    }
    Write-Host 'cs2-game was recreated because the active runtime changed.'
}

if ($FetchLatest) {
    if (-not (Test-Path -LiteralPath $FetchScript -PathType Leaf)) {
        throw "Release fetcher is missing: $FetchScript"
    }
    $fetchParameters = @{
        IncludeOptional = [bool]$IncludeOptional
        ForceDownload = [bool]$Force
        WhatIf = [bool]$WhatIfPreference
    }
    if ($Mode) { $fetchParameters.Mode = $Mode }
    if ($Component) { $fetchParameters.Component = $Component }
    if ($SharedOnly) { $fetchParameters.SharedOnly = $true }
    if ($Source) { $fetchParameters.Source = $Source }
    & $FetchScript @fetchParameters
}

$lockStream = $null
$lockAcquired = $false
try {
    if (-not $WhatIfPreference) {
        New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
        try {
            $lockStream = [System.IO.File]::Open(
                $LockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            $lockAcquired = $true
        }
        catch {
            throw 'Another package update is already running.'
        }
    }

    if (-not (Test-Path -LiteralPath $InstallsRoot -PathType Container)) {
        throw "Installs directory is missing: $InstallsRoot"
    }

    $archives = @(Get-ChildItem -LiteralPath $InstallsRoot -Filter '*.zip' -File -Recurse | Sort-Object FullName)
    if ($archives.Count -eq 0) {
        Write-Host 'No package archives were found under installs.'
        if ($WhatIfPreference) { Write-Host 'WhatIf completed. No package state was changed.' }
        return
    }

    $candidates = @()
    foreach ($archive in $archives) {
        $candidate = Read-PackageCandidate -ArchiveFile $archive
        if ($Mode -and ($candidate.PackageType -ne 'mode' -or $candidate.Id -ne $Mode.ToLowerInvariant())) { continue }
        if ($Component -and $candidate.Component -ne $Component.ToLowerInvariant()) { continue }
        if ($SharedOnly -and $candidate.PackageType -ne 'shared') { continue }
        if ($Source -and $candidate.Component -notin @($Source | ForEach-Object { $_.ToLowerInvariant() })) { continue }
        $candidates += $candidate
    }

    if ($candidates.Count -eq 0) {
        Write-Host 'No package archives matched the selected scope.'
        if ($WhatIfPreference) { Write-Host 'WhatIf completed. No package state was changed.' }
        return
    }

    $updated = @()
    foreach ($group in ($candidates | Group-Object { "$($_.PackageType)/$($_.Id)/$($_.Component)" } | Sort-Object Name)) {
        $sameVersions = $group.Group | Group-Object VersionText | Where-Object Count -gt 1
        if ($sameVersions) {
            throw "Multiple archives provide the same version for $($group.Name): $($sameVersions.Name -join ', ')"
        }
        $selected = $group.Group | Sort-Object Version -Descending | Select-Object -First 1
        if (Install-Candidate -Candidate $selected) {
            $updated += $selected
            foreach ($old in ($group.Group | Where-Object { $_.Version -lt $selected.Version })) {
                if ($PSCmdlet.ShouldProcess($old.Archive.FullName, 'Remove superseded package archive')) {
                    try {
                        Remove-Item -LiteralPath $old.Archive.FullName -Force
                        Write-Host "Removed superseded archive $($old.Archive.Name)"
                    }
                    catch {
                        Write-Warning "Package update succeeded, but superseded archive could not be removed: $($old.Archive.FullName). $($_.Exception.Message)"
                    }
                }
            }
        }
    }

    Restart-GameIfRequired -Updated $updated
    if ($WhatIfPreference) {
        Write-Host 'WhatIf completed. No package state was changed.'
    }
    elseif ($updated.Count -eq 0) {
        Write-Host 'All selected packages are already current.'
    }
}
finally {
    if ($lockStream) { $lockStream.Dispose() }
    if ($lockAcquired) {
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
    }
}
