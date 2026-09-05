# Remove the Second Brain OMP extension (historically named prime-extension)
# and restore its installer-owned backup. Defaults to OMP's real
# auto-discovery directory (~/.omp/agent/extensions); pass -ExtensionsDir to
# target a different install.

[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SettingsFile,
    [string]$SourceRoot,
    [string]$BackupDir
)

$ErrorActionPreference = "Stop"

if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".omp\agent\extensions" }
if (-not $SettingsFile) { $SettingsFile = Join-Path $env:USERPROFILE ".omp\agent\settings.json" }

$Target = Join-Path $ExtensionsDir "second-brain"
if (-not $BackupDir) {
    $BackupDir = Get-ChildItem -Path (Join-Path $SourceRoot "backups") -Directory `
        -Filter "*-prime-extension-pre-install" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if (Test-Path $Target) {
    Remove-Item -Recurse -Force $Target
    Write-Host "Removed $Target"
}

if ($BackupDir) {
    $Previous = Join-Path $BackupDir "extensions\second-brain"
    if (Test-Path $Previous -PathType Container) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Target) | Out-Null
        Copy-Item -Recurse -Force $Previous $Target
        Write-Host "Restored previous extension from $Previous"
    }
    $PreviousSettings = Join-Path $BackupDir "settings\settings.json"
    if (Test-Path $PreviousSettings -PathType Leaf) {
        Write-Host "settings.json backup retained at $PreviousSettings"
    }
} else {
    Write-Host "No pre-install backup found."
}
exit 0
