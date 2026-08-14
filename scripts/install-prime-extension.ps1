# The Second Brain — install the Prime Agent measurement extension (Phase 2).
# Copies brainstem/prime-extension/src -> ~/.prime/agent/extensions/second-brain/
# with a pre-install backup (plan §126). Never edits settings.json.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install-prime-extension.ps1
# Testable override params: -ExtensionsDir <dir> -SettingsFile <file>

[CmdletBinding()]
param(
    [string]$ExtensionsDir,   # defaults to ~/.prime/agent/extensions
    [string]$SettingsFile     # defaults to ~/.prime/agent/settings.json (backup only)
)

$ErrorActionPreference = "Stop"

if ($env:SECOND_BRAIN_HOME) { $Brain = $env:SECOND_BRAIN_HOME }
else { $Brain = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$Brain = [System.IO.Path]::GetFullPath($Brain)

if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".prime\agent\extensions" }
if (-not $SettingsFile) { $SettingsFile = Join-Path $env:USERPROFILE ".prime\agent\settings.json" }

$Src = Join-Path $Brain "brainstem\prime-extension\src"
$TypesSrc = Join-Path $Brain "brainstem\prime-extension\types"
$Target = Join-Path $ExtensionsDir "second-brain"

# 1. Source must exist (don't install an empty extension).
if (-not (Test-Path (Join-Path $Src "index.ts"))) {
    Write-Warning "Extension source not found at $Src (missing index.ts). Build Phase 2 first."
    exit 2
}

# 2. Pre-install backup (plan §126: backup before adapter/global-config change).
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$BackupDir = Join-Path $Brain "backups\$stamp-prime-extension-pre-install"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
if (Test-Path $Target) {
    Copy-Item -Recurse -Force $Target (Join-Path $BackupDir "extensions\second-brain")
}
if (Test-Path $SettingsFile) {
    New-Item -ItemType Directory -Force -Path (Join-Path $BackupDir "settings") | Out-Null
    Copy-Item -Force $SettingsFile (Join-Path $BackupDir "settings\settings.json")
}
Write-Host "Pre-install backup: $BackupDir"

# 3. Install (replace target with an exact mirror of the source tree; the
#    previous state lives in the pre-install backup; never edit settings.json).
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Force (Join-Path $Src "*.ts") $Target
if (Test-Path $TypesSrc) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Target "types") | Out-Null
    Copy-Item -Force (Join-Path $TypesSrc "*.d.ts") (Join-Path $Target "types")
}
Write-Host "Installed extension to $Target"

Write-Host ""
Write-Host "Next steps:"
Write-Host "  - restart Prime Agent (or /reload) to load the extension"
Write-Host "  - disable measurement: set SECOND_BRAIN_OBSERVABILITY=off"
Write-Host "  - uninstall: powershell -ExecutionPolicy Bypass -File scripts\uninstall-prime-extension.ps1"
exit 0
