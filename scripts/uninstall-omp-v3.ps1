<#
.SYNOPSIS
  Remove the standalone Second Brain V3 OMP extension; -RestoreLegacy moves the most recently
  parked legacy extension back (only when no `second-brain` extension is installed).
#>
[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [switch]$RestoreLegacy
)
$ErrorActionPreference = "Stop"

if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".omp\agent\extensions" }
$Target = Join-Path $ExtensionsDir "second-brain-v3"
if (Test-Path $Target) {
    Remove-Item -Recurse -Force $Target
    Write-Host "Removed $Target"
}
if ($RestoreLegacy) {
    $Legacy = Join-Path $ExtensionsDir "second-brain"
    if (Test-Path $Legacy) { throw "A second-brain extension is already installed at $Legacy" }
    $ParkedRoot = Join-Path (Split-Path $ExtensionsDir -Parent) "extensions-disabled"
    $Newest = Get-ChildItem -Path $ParkedRoot -Directory -Filter "second-brain-*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $Newest) { throw "No parked legacy extension under $ParkedRoot" }
    Move-Item $Newest.FullName $Legacy
    Write-Host "Restored legacy extension from $($Newest.FullName)"
}
Write-Host "Restart OMP to apply."
