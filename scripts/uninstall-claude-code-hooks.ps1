# Removes the "hooks" key installed by install-claude-code-hooks.ps1 from
# Claude Code's global settings.json, or restores the pre-install backup.
#
# Windows PowerShell 5.1 compatible: no ConvertFrom-Json -AsHashtable.
param(
    [switch]$RestoreBackup
)
$ErrorActionPreference = "Stop"

$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = Join-Path $HOME ".claude" }
$settingsPath = Join-Path $configDir "settings.json"

if ($RestoreBackup) {
    $backup = Get-ChildItem "$settingsPath.sb-hooks-backup-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $backup) { Write-Output "No backup found."; exit 1 }
    Copy-Item $backup.FullName $settingsPath -Force
    Write-Output "Restored $settingsPath from $($backup.Name)"
    exit 0
}

if (-not (Test-Path $settingsPath)) { Write-Output "No settings.json found."; exit 0 }
$existing = Get-Content $settingsPath -Raw | ConvertFrom-Json
if ($existing.PSObject.Properties.Name -contains "hooks") {
    $existing.PSObject.Properties.Remove("hooks")
    ($existing | ConvertTo-Json -Depth 10) | Set-Content -Path $settingsPath -Encoding utf8
    Write-Output "Removed hooks block from $settingsPath"
} else {
    Write-Output "No hooks block present."
}
