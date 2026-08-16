# The Second Brain — install the Google Antigravity harness adapter.
# Copies brainstem/adapters/antigravity -> ~/.gemini/config/plugins/second-brain-adapter/
# (Antigravity app surface) and/or registers it via `agy plugin install` when
# the Antigravity CLI is available. Pre-install backup kept under backups/.
# Reversible via scripts\uninstall-antigravity-adapter.ps1.
#
# The adapter is validated before install: plugin.json must parse and carry
# name + description; hooks.json must parse. No Brain core config is touched.

[CmdletBinding()]
param(
    [ValidateSet("App", "Cli", "Both")]
    [string]$Target = "App",
    [string]$PluginsDir
)

$ErrorActionPreference = "Stop"

if ($env:SECOND_BRAIN_HOME) { $Brain = $env:SECOND_BRAIN_HOME }
else { $Brain = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$Brain = [System.IO.Path]::GetFullPath($Brain)

if (-not $PluginsDir) { $PluginsDir = Join-Path $env:USERPROFILE ".gemini\config\plugins" }

$Src = Join-Path $Brain "brainstem\adapters\antigravity"
$TargetDir = Join-Path $PluginsDir "second-brain-adapter"

# 1. Validate source plugin (manifest + hooks schema)
if (-not (Test-Path (Join-Path $Src "plugin.json"))) {
    Write-Warning "Adapter source not found at $Src (missing plugin.json)."
    exit 2
}
try {
    $manifest = Get-Content (Join-Path $Src "plugin.json") -Raw | ConvertFrom-Json
    if (-not $manifest.name -or -not $manifest.description) {
        Write-Warning "plugin.json must carry name and description."
        exit 2
    }
} catch {
    Write-Warning "plugin.json is not valid JSON: $($_.Exception.Message)"
    exit 2
}
$hooksPath = Join-Path $Src "hooks.json"
if (-not (Test-Path $hooksPath)) {
    Write-Warning "hooks.json missing; nothing to install."
    exit 2
}
try {
    $null = Get-Content $hooksPath -Raw | ConvertFrom-Json
} catch {
    Write-Warning "hooks.json is not valid JSON: $($_.Exception.Message)"
    exit 2
}

# 2. CLI target: use the official managed install when agy exists
if ($Target -eq "Cli" -or $Target -eq "Both") {
    $agy = Get-Command agy -ErrorAction SilentlyContinue
    if ($agy) {
        & agy plugin install $Src
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "agy plugin install failed (exit $LASTEXITCODE)."
            exit 3
        }
        Write-Host "Registered adapter via agy plugin install."
        if ($Target -eq "Cli") { exit 0 }
    } else {
        Write-Warning "agy CLI not found; CLI target skipped. Install agy and re-run with -Target Cli (or run: agy plugin install <path>)."
        if ($Target -eq "Cli") { exit 4 }
    }
}

# 3. App target: copy with pre-install backup (skip when identical)
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$BackupDir = Join-Path $Brain "backups\$stamp-antigravity-adapter-pre-install"

$identical = $false
if (Test-Path $TargetDir) {
    $same = $true
    Get-ChildItem -Recurse -File $Src | ForEach-Object {
        $rel = $_.FullName.Substring($Src.Length)
        $dst = Join-Path $TargetDir $rel.TrimStart("\")
        if (-not (Test-Path $dst)) { $same = $false }
        else {
            $h1 = (Get-FileHash $_.FullName).Hash
            $h2 = (Get-FileHash $dst).Hash
            if ($h1 -ne $h2) { $same = $false }
        }
    }
    $identical = $same
}

if ($identical) {
    Write-Host "Adapter already installed and identical at $TargetDir; no copy needed."
} else {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    if (Test-Path $TargetDir) {
        Copy-Item -Recurse -Force $TargetDir (Join-Path $BackupDir "plugins\second-brain-adapter")
    }
    if (Test-Path $TargetDir) { Remove-Item -Recurse -Force $TargetDir }
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Src "*") $TargetDir
    Write-Host "Installed Second Brain Antigravity adapter to $TargetDir"
    Write-Host "Pre-install backup: $BackupDir"
}
Write-Host "Next: enable the plugin in Antigravity (Settings -> Skills & Customizations -> Plugins) and verify hooks are listed."
exit 0
