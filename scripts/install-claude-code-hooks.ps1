# Installs the Second Brain P3a Claude Code hooks (SessionStart/PreCompact/
# Stop only) into Claude Code's global settings.json.
#
# Target: $env:CLAUDE_CONFIG_DIR/settings.json, else ~/.claude/settings.json.
# Merges ONLY the top-level "hooks" key from
# brainstem/adapters/claude-code/hooks.json; never touches any other key.
# Idempotent (re-running just re-writes the same "hooks" value). Keeps a
# timestamped backup for uninstall-claude-code-hooks.ps1 -RestoreBackup.
#
# Windows PowerShell 5.1 compatible: does NOT use ConvertFrom-Json
# -AsHashtable (Core-only), works on PSCustomObject throughout.
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)

$templatePath = Join-Path $RepoRoot "brainstem\adapters\claude-code\hooks.json"
$runPs1 = Join-Path $RepoRoot "brainstem\adapters\claude-code\scripts\run-hook.ps1"
if (-not (Test-Path $templatePath)) { throw "hooks.json not found at $templatePath" }
if (-not (Test-Path $runPs1)) { throw "run-hook.ps1 not found at $runPs1" }
$systemDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::System)
$powerShell = Join-Path $systemDir "WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $powerShell -PathType Leaf)) { throw "Trusted Windows PowerShell not found at $powerShell" }

$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = Join-Path $HOME ".claude" }
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$settingsPath = Join-Path $configDir "settings.json"

$escapedPath = ($runPs1 | ConvertTo-Json -Compress).Trim('"')
$escapedPowerShell = ($powerShell | ConvertTo-Json -Compress).Trim('"')
$templateText = (Get-Content $templatePath -Raw -Encoding UTF8).Replace("<RUN_PS1>", $escapedPath).Replace("<POWERSHELL_EXE>", $escapedPowerShell)
$template = $templateText | ConvertFrom-Json

$existing = if (Test-Path $settingsPath) {
    Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    [pscustomobject]@{}
}

if (Test-Path $settingsPath) {
    $backup = "$settingsPath.sb-hooks-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $settingsPath $backup
    Write-Output "Backup written: $backup"
}

$existing | Add-Member -NotePropertyName "hooks" -NotePropertyValue $template.hooks -Force
($existing | ConvertTo-Json -Depth 10) | Set-Content -Path $settingsPath -Encoding utf8

Write-Output "Installed Claude Code hooks (SessionStart/PreCompact/Stop) -> $settingsPath"
