# The Second Brain — uninstall the Google Antigravity harness adapter.
# Removes ~/.gemini/config/plugins/second-brain-adapter/ or restores the last backup.

[CmdletBinding()]
param(
    [string]$PluginsDir,
    [switch]$RestoreBackup
)

$ErrorActionPreference = "Stop"

if ($env:SECOND_BRAIN_HOME) { $Brain = $env:SECOND_BRAIN_HOME }
else { $Brain = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$Brain = [System.IO.Path]::GetFullPath($Brain)

if (-not $PluginsDir) { $PluginsDir = Join-Path $env:USERPROFILE ".gemini\config\plugins" }
$Target = Join-Path $PluginsDir "second-brain-adapter"

if ($RestoreBackup) {
    $backups = Get-ChildItem (Join-Path $Brain "backups") -Directory -Filter "*antigravity-adapter-pre-install" | Sort-Object CreationTime -Descending
    if ($backups.Count -eq 0) {
        Write-Warning "No pre-install backups found."
        exit 1
    }
    $latest = $backups[0].FullName
    $backupTarget = Join-Path $latest "plugins\second-brain-adapter"
    if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
    if (Test-Path $backupTarget) {
        Copy-Item -Recurse -Force $backupTarget $Target
        Write-Host "Restored Antigravity adapter from $latest"
    } else {
        Write-Host "Prior state was uninstalled; removed $Target"
    }
    exit 0
}

if (Test-Path $Target) {
    Remove-Item -Recurse -Force $Target
    Write-Host "Uninstalled Second Brain Antigravity adapter from $Target"
} else {
    Write-Host "Antigravity adapter not installed at $Target"
}
exit 0
