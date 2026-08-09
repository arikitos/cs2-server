[CmdletBinding()]
param([string]$Version = "0.1.0", [switch]$KeepPdb)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ModeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Join-Path $ModeRoot "src/SuperHeroMod/SuperHeroMod.csproj"
$Publish = Join-Path $ModeRoot ".build/SuperHeroMod"
$Release = Join-Path $ModeRoot "release/plugins/SuperHeroMod"

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw ".NET 10 SDK was not found." }
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') { throw "Version '$Version' is not a supported semantic version." }

Write-Host "[SuperHeroMod] Validating mode configuration"
Get-Content (Join-Path $ModeRoot "mode.json") -Raw | ConvertFrom-Json | Out-Null
$Heroes = @(Get-Content (Join-Path $ModeRoot "config/heroes.json") -Raw | ConvertFrom-Json)
if ($Heroes.Count -lt 25) { throw "SuperHero MVP requires at least 25 heroes." }
$Ids = @($Heroes | ForEach-Object { $_.Id })
if (($Ids | Sort-Object -Unique).Count -ne $Ids.Count) { throw "Duplicate hero Id detected." }

if (Test-Path $Publish) { Remove-Item $Publish -Recurse -Force }
if (Test-Path $Release) { Remove-Item $Release -Recurse -Force }
New-Item -ItemType Directory -Path $Publish -Force | Out-Null
New-Item -ItemType Directory -Path $Release -Force | Out-Null

& dotnet restore $Project
if ($LASTEXITCODE -ne 0) { throw "dotnet restore failed." }
& dotnet publish $Project -c Release -o $Publish --no-restore -p:Version=$Version
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed." }

foreach ($Name in @("SuperHeroMod.dll", "SuperHeroMod.deps.json")) {
    $Source = Join-Path $Publish $Name
    if (-not (Test-Path $Source)) { throw "Build output is missing $Name." }
    Copy-Item $Source $Release
}
$RuntimeConfig = Join-Path $Publish "SuperHeroMod.runtimeconfig.json"
if (Test-Path $RuntimeConfig) { Copy-Item $RuntimeConfig $Release }
$Pdb = Join-Path $Publish "SuperHeroMod.pdb"
if ($KeepPdb -and (Test-Path $Pdb)) { Copy-Item $Pdb $Release }

Write-Host "[SuperHeroMod] Release staged at $Release"
