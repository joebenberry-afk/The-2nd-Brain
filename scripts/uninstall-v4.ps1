<#
.SYNOPSIS
  Remove the Second Brain V4 OMP extension; with -Restore, bring back the most recently parked
  older extension (second-brain or second-brain-v3). Notes, kits and working state are untouched.
#>
[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SourceRoot,
    [switch]$Restore,
    [switch]$RemovePath
)
$ErrorActionPreference = "Stop"

if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".omp\agent\extensions" }

$Target = Join-Path $ExtensionsDir "second-brain-v4"
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target; Write-Host "Removed $Target" }

if ($Restore) {
    $Disabled = Join-Path (Split-Path $ExtensionsDir -Parent) "extensions-disabled"
    $latest = Get-ChildItem $Disabled -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^second-brain(-v3)?-\d{8}-\d{6}$' } |
        Sort-Object { $_.Name.Substring($_.Name.Length - 15) } | Select-Object -Last 1
    if ($latest) {
        $name = $latest.Name.Substring(0, $latest.Name.Length - 16)
        Move-Item $latest.FullName (Join-Path $ExtensionsDir $name)
        Write-Host "Restored $name"
    } else {
        Write-Warning "No parked extension found in $Disabled"
    }
}

if ($RemovePath) {
    $parts = @([Environment]::GetEnvironmentVariable("Path", "User") -split ";" | Where-Object { $_ -and $_ -ne $SourceRoot })
    [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
    Write-Host "Removed $SourceRoot from the user PATH"
}
Write-Host "Restart OMP."
