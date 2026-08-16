# Removes the Second Brain P0 Codex hooks from Codex config.
#
# Default: deletes ONLY the marker-guarded [hooks] event keys (no other
# table is touched) and prints the diff. With -RestoreBackup, restores the
# most recent pre-install backup (config.toml.sb-hooks-backup-*) — full
# reversal to the exact prior state.
param(
    [string]$CodexHome = "",
    [switch]$RestoreBackup
)
$ErrorActionPreference = "Stop"

if (-not $CodexHome) {
    $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
}
$configPath = Join-Path $CodexHome "config.toml"
if (-not (Test-Path $configPath)) {
    Write-Host "no config at $configPath; nothing to uninstall."
    exit 0
}

if ($RestoreBackup) {
    $backup = Get-ChildItem "$configPath.sb-hooks-backup-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $backup) { Write-Host "no backup found; refusing to guess."; exit 1 }
    Copy-Item $backup.FullName $configPath -Force
    Write-Host "restored prior state from $($backup.FullName)"
    exit 0
}

$begin = "# BEGIN second-brain-codex-hooks (Phase 0C SHADOW; managed by install-codex-hooks.ps1)"
$content = Get-Content -Raw $configPath
if ($content -notmatch [regex]::Escape($begin)) {
    Write-Host "second-brain-codex-hooks block not present; nothing to uninstall."
    exit 0
}

$pattern = "(?ms)^\s*# BEGIN second-brain-codex-hooks.*?# END second-brain-codex-hooks[ \t]*`r?`n?"
$newContent = [regex]::Replace($content, $pattern, "")
# Drop a now-empty [hooks] header line if we left one behind.
$newContent = $newContent -replace "(?m)^\[hooks\]\s*`r?`n(?=\S)", ""
[System.IO.File]::WriteAllText($configPath, $newContent, (New-Object System.Text.UTF8Encoding $false))
Write-Host "--- removed second-brain-codex-hooks block from $configPath ---"
Write-Host "reversible with: .\scripts\uninstall-codex-hooks.ps1 -RestoreBackup"
