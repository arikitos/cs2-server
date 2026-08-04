[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$PackagePath,

    [Parameter(Position = 1)]
    [string]$ProjectRoot,

    [switch]$StageOnly
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Installer = Join-Path $Root "install-heroshift.ps1"

$arguments = @{}
if (-not [string]::IsNullOrWhiteSpace($PackagePath)) {
    $arguments.PackagePath = $PackagePath
}
if ($StageOnly) {
    $arguments.StageOnly = $true
}

& $Installer @arguments
