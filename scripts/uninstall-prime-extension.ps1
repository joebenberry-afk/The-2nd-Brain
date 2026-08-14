# The Second Brain — uninstall the Prime Agent measurement extension.
# Removes ~/.prime/agent/extensions/second-brain/ and, when a pre-install
# backup exists, restores the previous extension directory from the newest
# backup. settings.json is NEVER restored automatically (user config);
# the script prints where its backup copy lives.

[CmdletBinding()]
param(
    [string]$ExtensionsDir,   # defaults to ~/.prime/agent/extensions
    [string]$SettingsFile     # defaults to ~/.prime/agent/settings.json (not restored)
)

$ErrorActionPreference = "Stop"

if ($env:SECOND_BRAIN_HOME) { $Brain = $env:SECOND_BRAIN_HOME }
else { $Brain = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$Brain = [System.IO.Path]::GetFullPath($Brain)

if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".prime\agent\extensions" }
if (-not $SettingsFile) { $SettingsFile = Join-Path $env:USERPROFILE ".prime\agent\settings.json" }

$Target = Join-Path $ExtensionsDir "second-brain"

if (Test-Path $Target) {
    Remove-Item -Recurse -Force $Target
    Write-Host "Removed $Target"
} else {
    Write-Host "Extension not installed ($Target missing); nothing to remove."
}

# Restore previous extension dir from newest pre-install backup, if any.
$BackupsRoot = Join-Path $Brain "backups"
$prev = Get-ChildItem -Path $BackupsRoot -Directory -Filter "*-prime-extension-pre-install" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if ($prev) {
    $prevTarget = Join-Path $prev.FullName "extensions\second-brain"
    if (Test-Path $prevTarget) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Target) | Out-Null
        Copy-Item -Recurse -Force $prevTarget $Target
        Write-Host "Restored previous extension from $prevTarget"
    }
    $prevSettings = Join-Path $prev.FullName "settings\settings.json"
    if (Test-Path $prevSettings) {
        Write-Host "NOTE: settings.json backup at $prevSettings was NOT restored automatically."
        Write-Host "      Restore manually only if you know it is safe."
    }
} else {
    Write-Host "No pre-install backup found."
}
exit 0
