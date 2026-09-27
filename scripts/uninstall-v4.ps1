<#
.SYNOPSIS
  Remove the Second Brain V4 OMP extension; with -Restore, bring back the most recently parked
  older extension (second-brain or second-brain-v3). -RemovePath takes the checkout off the user
  PATH. Notes, kits and working state are untouched. Works with Windows PowerShell 5.1 and 7.
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
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path (Join-Path $HOME ".omp") "agent/extensions" }
$ExtensionsDir = [System.IO.Path]::GetFullPath($ExtensionsDir)

$Target = Join-Path $ExtensionsDir "second-brain-v4"
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target; Write-Host "Removed $Target" }

if ($Restore) {
    # Everything the last install parked shares its timestamp: restore all of it.
    $Disabled = Join-Path (Split-Path $ExtensionsDir -Parent) "extensions-disabled"
    $parked = @(Get-ChildItem $Disabled -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^second-brain(-v3)?-\d{8}-\d{6}$' })
    if ($parked.Count -gt 0) {
        $stamp = ($parked | ForEach-Object { $_.Name.Substring($_.Name.Length - 15) } | Sort-Object | Select-Object -Last 1)
        foreach ($dir in ($parked | Where-Object { $_.Name.EndsWith($stamp) })) {
            $name = $dir.Name.Substring(0, $dir.Name.Length - 16)
            $dest = Join-Path $ExtensionsDir $name
            if (Test-Path $dest) { throw "$dest already exists; not overwriting it." }
            Move-Item $dir.FullName $dest
            Write-Host "Restored $name"
        }
    } else {
        Write-Warning "No parked extension found in $Disabled"
    }
}

if ($RemovePath) {
    $parts = @(([Environment]::GetEnvironmentVariable("Path", "User") -split ";") | Where-Object { $_ -and $_ -ne $SourceRoot })
    [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
    Write-Host "Removed $SourceRoot from the user PATH"
}
Write-Host "Restart OMP."
