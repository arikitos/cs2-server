[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string]$Mode,

    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string]$Component,

    [switch]$SharedOnly,
    [switch]$IncludeOptional,

    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string[]]$Source,

    [switch]$ForceDownload
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = $PSScriptRoot
$CatalogPath = Join-Path $ProjectRoot 'installs\sources.json'
$ModesRoot = Join-Path $ProjectRoot 'manager\modes'
$SharedRoot = Join-Path $ProjectRoot 'manager\shared'

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

function ConvertTo-VersionInfo {
    param([Parameter(Mandatory = $true)][string]$Value)

    $match = [regex]::Match($Value, '(?<!\d)(?<version>\d+\.\d+\.\d+)(?!\d)')
    if (-not $match.Success) {
        throw "Unable to extract an X.Y.Z version from '$Value'."
    }
    $text = $match.Groups['version'].Value
    return [pscustomobject]@{
        Text = $text
        Value = [version]$text
    }
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

function Get-GitHubHeaders {
    $headers = @{
        Accept = 'application/vnd.github+json'
        'User-Agent' = 'cs2-server-manager'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
    if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
        $headers.Authorization = "Bearer $($env:GITHUB_TOKEN)"
    }
    return $headers
}

function Invoke-GitHubLatestRelease {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $uri = "https://api.github.com/repos/$Repository/releases/latest"
    try {
        return Invoke-RestMethod -Uri $uri -Headers (Get-GitHubHeaders) -Method Get
    }
    catch {
        throw "Unable to resolve the latest GitHub release for $Repository. $($_.Exception.Message)"
    }
}

function Get-PackageMarkerPath {
    param([Parameter(Mandatory = $true)]$Package)

    $packageType = ([string]$Package.type).ToLowerInvariant()
    $id = ([string]$Package.id).ToLowerInvariant()
    $component = ([string]$Package.component).ToLowerInvariant()
    if ($packageType -eq 'mode') {
        return Join-Path (Join-Path (Join-Path $ModesRoot $id) 'packages') "$component.json"
    }
    if ($packageType -eq 'shared') {
        return Join-Path (Join-Path (Join-Path (Join-Path $SharedRoot 'components') $id) 'packages') "$component.json"
    }
    throw "Unsupported package type '$packageType'."
}

function Get-ArchiveManifestVersion {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$ArchiveFile)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchiveFile.FullName)
        try {
            $entry = $archive.Entries | Where-Object {
                $_.FullName.Replace('\', '/').TrimEnd('/') -eq 'package-manifest.json'
            } | Select-Object -First 1
            if ($null -eq $entry) { return $null }
            $stream = $entry.Open()
            $reader = [System.IO.StreamReader]::new($stream)
            try {
                $manifest = $reader.ReadToEnd() | ConvertFrom-Json
            }
            finally {
                $reader.Dispose()
                $stream.Dispose()
            }
            $versionText = Get-ObjectProperty -Object $manifest -Name 'version'
            if (-not $versionText) { return $null }
            return (ConvertTo-VersionInfo -Value ([string]$versionText)).Value
        }
        finally {
            $archive.Dispose()
        }
    }
    catch {
        return $null
    }
}

function Get-HighestKnownVersion {
    param(
        [Parameter(Mandatory = $true)]$SourceDefinition,
        [Parameter(Mandatory = $true)][string]$OutputDirectory
    )

    $versions = @()
    $markerPath = Get-PackageMarkerPath -Package $SourceDefinition.package
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        try {
            $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
            $markerVersion = Get-ObjectProperty -Object $marker -Name 'version'
            if ($markerVersion) {
                $versions += (ConvertTo-VersionInfo -Value ([string]$markerVersion)).Value
            }
        }
        catch {
            Write-Warning "Ignoring invalid package marker while resolving source $($SourceDefinition.id): $markerPath"
        }
    }

    if (Test-Path -LiteralPath $OutputDirectory -PathType Container) {
        foreach ($archive in (Get-ChildItem -LiteralPath $OutputDirectory -Filter '*.zip' -File)) {
            $archiveVersion = Get-ArchiveManifestVersion -ArchiveFile $archive
            if ($null -ne $archiveVersion) { $versions += $archiveVersion }
        }
    }

    if ($versions.Count -eq 0) { return $null }
    return $versions | Sort-Object -Descending | Select-Object -First 1
}

function Get-ZipEntries {
    param([Parameter(Mandatory = $true)]$Archive)

    $entries = @{}
    foreach ($entry in $Archive.Entries) {
        $normalized = $entry.FullName.Replace('\', '/')
        $key = $normalized.TrimEnd('/')
        if (-not $key) { continue }
        if (-not (Test-SafeArchivePath -Path $key)) {
            throw "Unsafe ZIP path: $($entry.FullName)"
        }
        if ($entries.ContainsKey($key)) {
            throw "Duplicate ZIP path: $key"
        }
        $entries[$key] = $entry
    }
    return $entries
}

function Test-ExcludedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter()][object[]]$Patterns = @()
    )

    foreach ($pattern in $Patterns) {
        if ($Path -match ([string]$pattern)) { return $true }
    }
    return $false
}

function Copy-MappedArchive {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)]$Adapter,
        [Parameter(Mandatory = $true)][string]$PayloadRoot
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entries = Get-ZipEntries -Archive $archive
        $patterns = @(Get-ObjectProperty -Object $Adapter -Name 'excludePatterns' -DefaultValue @())
        $written = @{}

        foreach ($mapping in @($Adapter.mappings)) {
            $targetRoot = ([string]$mapping.target).Replace('\', '/').Trim('/')
            if (-not (Test-SafeArchivePath -Path $targetRoot)) {
                throw "Unsafe target path in source catalog: $targetRoot"
            }

            $selectedPrefix = $null
            foreach ($candidateValue in @($mapping.sourceCandidates)) {
                $candidate = ([string]$candidateValue).Replace('\', '/').Trim('/')
                if (-not (Test-SafeArchivePath -Path $candidate)) {
                    throw "Unsafe source path in source catalog: $candidate"
                }
                $hasFiles = $false
                foreach ($entryKey in $entries.Keys) {
                    if ($entryKey.StartsWith("$candidate/") -and -not $entries[$entryKey].FullName.EndsWith('/')) {
                        $hasFiles = $true
                        break
                    }
                }
                if ($hasFiles) {
                    $selectedPrefix = $candidate
                    break
                }
            }

            if (-not $selectedPrefix) {
                throw "None of the expected source roots were found: $(@($mapping.sourceCandidates) -join ', ')"
            }

            $mappingFileCount = 0
            foreach ($entryKey in ($entries.Keys | Sort-Object)) {
                $entry = $entries[$entryKey]
                if ($entry.FullName.EndsWith('/')) { continue }
                if (-not $entryKey.StartsWith("$selectedPrefix/")) { continue }

                $relative = $entryKey.Substring($selectedPrefix.Length).TrimStart('/')
                if (-not $relative -or (Test-ExcludedPath -Path $relative -Patterns $patterns)) { continue }
                if (-not (Test-SafeArchivePath -Path $relative)) {
                    throw "Unsafe mapped file path: $relative"
                }

                $targetRelative = "$targetRoot/$relative"
                if ($written.ContainsKey($targetRelative)) {
                    throw "Multiple upstream files map to the same package path: $targetRelative"
                }
                $written[$targetRelative] = $true

                $target = Join-Path $PayloadRoot ($targetRelative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
                New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
                $input = $entry.Open()
                $output = [System.IO.File]::Open($target, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                try {
                    $input.CopyTo($output)
                }
                finally {
                    $output.Dispose()
                    $input.Dispose()
                }
                $mappingFileCount++
            }

            if ($mappingFileCount -eq 0) {
                throw "The selected source root produced no runtime files: $selectedPrefix"
            }
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Write-StandardPackage {
    param(
        [Parameter(Mandatory = $true)]$SourceDefinition,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$UpstreamArchive,
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)]$Asset,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$TemporaryRoot
    )

    $stageRoot = Join-Path $TemporaryRoot 'stage'
    $payloadRoot = Join-Path $stageRoot 'payload'
    New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null

    Copy-MappedArchive -ArchivePath $UpstreamArchive -Adapter $SourceDefinition.adapter -PayloadRoot $payloadRoot

    $files = @(Get-ChildItem -LiteralPath $payloadRoot -File -Recurse | Sort-Object FullName)
    if ($files.Count -eq 0) {
        throw "Source $($SourceDefinition.id) produced an empty package."
    }

    $manifestFiles = foreach ($file in $files) {
        $relative = [System.IO.Path]::GetRelativePath($stageRoot, $file.FullName).Replace([System.IO.Path]::DirectorySeparatorChar, '/')
        [ordered]@{
            path = $relative
            size = $file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }

    $package = $SourceDefinition.package
    $manifest = [ordered]@{
        schemaVersion = 2
        packageType = ([string]$package.type).ToLowerInvariant()
        id = ([string]$package.id).ToLowerInvariant()
        component = ([string]$package.component).ToLowerInvariant()
        name = [string]$package.name
        version = $Version
        payloadRoot = 'payload'
        installStrategy = [string]$package.installStrategy
        installRoots = @($package.installRoots)
        source = [ordered]@{
            provider = 'github-release'
            repository = [string]$SourceDefinition.github.repository
            tag = [string]$Release.tag_name
            asset = [string]$Asset.name
            publishedAt = [string]$Release.published_at
        }
        files = @($manifestFiles)
    }

    $manifestPath = Join-Path $stageRoot 'package-manifest.json'
    [System.IO.File]::WriteAllText(
        $manifestPath,
        (($manifest | ConvertTo-Json -Depth 12) + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $fixedTimestamp = [DateTimeOffset]::new(1980, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
    $allFiles = @(Get-ChildItem -LiteralPath $stageRoot -File -Recurse | Sort-Object FullName)
    $stream = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::CreateNew)
    try {
        $zip = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Create, $false)
        try {
            foreach ($file in $allFiles) {
                $relative = [System.IO.Path]::GetRelativePath($stageRoot, $file.FullName).Replace([System.IO.Path]::DirectorySeparatorChar, '/')
                $entry = $zip.CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime = $fixedTimestamp
                $entryStream = $entry.Open()
                $sourceStream = [System.IO.File]::OpenRead($file.FullName)
                try {
                    $sourceStream.CopyTo($entryStream)
                }
                finally {
                    $sourceStream.Dispose()
                    $entryStream.Dispose()
                }
            }
        }
        finally {
            $zip.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Assert-DownloadedDigest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Asset
    )

    $digest = Get-ObjectProperty -Object $Asset -Name 'digest'
    if (-not $digest) { return }
    $text = [string]$digest
    if (-not $text.StartsWith('sha256:', [System.StringComparison]::OrdinalIgnoreCase)) { return }
    $expected = $text.Substring(7).ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "GitHub release asset digest mismatch for $($Asset.name)."
    }
}

function Assert-PassthroughManifest {
    param([Parameter(Mandatory = $true)][string]$ArchivePath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entries = Get-ZipEntries -Archive $archive
        if (-not $entries.ContainsKey('package-manifest.json')) {
            throw 'A passthrough package must contain package-manifest.json.'
        }
    }
    finally {
        $archive.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $CatalogPath -PathType Leaf)) {
    throw "Source catalog is missing: $CatalogPath"
}
$catalog = Get-Content -LiteralPath $CatalogPath -Raw | ConvertFrom-Json
if ((Get-ObjectProperty -Object $catalog -Name 'schemaVersion') -ne 1) {
    throw "Unsupported source catalog schema in $CatalogPath"
}

$selectedSources = @()
foreach ($definition in @($catalog.sources)) {
    $sourceId = ([string]$definition.id).ToLowerInvariant()
    $packageType = ([string]$definition.package.type).ToLowerInvariant()
    $packageId = ([string]$definition.package.id).ToLowerInvariant()
    $componentId = ([string]$definition.package.component).ToLowerInvariant()
    $enabled = [bool](Get-ObjectProperty -Object $definition -Name 'enabledByDefault' -DefaultValue $false)

    if (-not $enabled -and -not $IncludeOptional) { continue }
    if ($Source -and $sourceId -notin @($Source | ForEach-Object { $_.ToLowerInvariant() })) { continue }
    if ($Mode -and ($packageType -ne 'mode' -or $packageId -ne $Mode.ToLowerInvariant())) { continue }
    if ($Component -and $componentId -ne $Component.ToLowerInvariant()) { continue }
    if ($SharedOnly -and $packageType -ne 'shared') { continue }
    $selectedSources += $definition
}

if ($selectedSources.Count -eq 0) {
    Write-Host 'No release sources matched the selected scope.'
    return
}

foreach ($definition in ($selectedSources | Sort-Object { [string]$_.id })) {
    $repository = [string]$definition.github.repository
    $release = Invoke-GitHubLatestRelease -Repository $repository
    $versionInfo = ConvertTo-VersionInfo -Value ([string]$release.tag_name)
    $assetPattern = [string]$definition.github.assetPattern
    $assets = @($release.assets | Where-Object { ([string]$_.name) -match $assetPattern })
    if ($assets.Count -ne 1) {
        $names = @($release.assets | ForEach-Object { [string]$_.name }) -join ', '
        throw "Expected exactly one release asset for $($definition.id) matching '$assetPattern', found $($assets.Count). Assets: $names"
    }
    $asset = $assets[0]

    $outputDirectory = Join-Path $ProjectRoot (([string]$definition.output.directory).Replace('/', [System.IO.Path]::DirectorySeparatorChar))
    $outputName = ([string]$definition.output.fileName).Replace('{version}', $versionInfo.Text)
    $outputPath = Join-Path $outputDirectory $outputName
    $knownVersion = Get-HighestKnownVersion -SourceDefinition $definition -OutputDirectory $outputDirectory

    if (-not $ForceDownload -and $null -ne $knownVersion -and $knownVersion -ge $versionInfo.Value) {
        Write-Host "Current $($definition.id): known=$($knownVersion.ToString(3)), upstream=$($versionInfo.Text)"
        continue
    }
    if (-not $ForceDownload -and (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
        Write-Host "Package already exists: $outputPath"
        continue
    }

    if (-not $PSCmdlet.ShouldProcess($outputPath, "Download and package $repository $($release.tag_name)")) {
        continue
    }

    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('cs2-source-' + [guid]::NewGuid().ToString('N'))
    $preparedPath = Join-Path $outputDirectory ('.' + $outputName + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    $downloadPath = Join-Path $temporaryRoot 'upstream.zip'
    try {
        Invoke-WebRequest -Uri ([string]$asset.browser_download_url) -Headers (Get-GitHubHeaders) -OutFile $downloadPath
        Assert-DownloadedDigest -Path $downloadPath -Asset $asset

        $adapterType = ([string]$definition.adapter.type).ToLowerInvariant()
        if ($adapterType -eq 'passthrough-manifest') {
            Assert-PassthroughManifest -ArchivePath $downloadPath
            Copy-Item -LiteralPath $downloadPath -Destination $preparedPath
        }
        elseif ($adapterType -eq 'mapped-zip') {
            Write-StandardPackage `
                -SourceDefinition $definition `
                -Version $versionInfo.Text `
                -UpstreamArchive $downloadPath `
                -Release $release `
                -Asset $asset `
                -OutputPath $preparedPath `
                -TemporaryRoot $temporaryRoot
        }
        else {
            throw "Unsupported source adapter '$adapterType' for $($definition.id)."
        }

        Move-Item -LiteralPath $preparedPath -Destination $outputPath -Force
        Write-Host "Prepared $($definition.id) $($versionInfo.Text): $outputPath"
    }
    finally {
        if (Test-Path -LiteralPath $preparedPath) {
            Remove-Item -LiteralPath $preparedPath -Force
        }
        if (Test-Path -LiteralPath $temporaryRoot) {
            Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
        }
    }
}
