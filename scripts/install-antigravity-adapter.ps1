# The Second Brain — install the Google Antigravity harness adapter.
# Renders the trusted PowerShell path into a disposable plugin copy, then
# installs that copy for the App and/or through `agy plugin install`.
# Pre-install backup kept under backups/.
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
$PluginsDir = [System.IO.Path]::GetFullPath($PluginsDir)

$Src = Join-Path $Brain "brainstem\adapters\antigravity"
$TargetDir = Join-Path $PluginsDir "second-brain-adapter"

# 1. Validate source plugin (manifest + hooks schema)
if (-not (Test-Path (Join-Path $Src "plugin.json"))) {
    Write-Warning "Adapter source not found at $Src (missing plugin.json)."
    exit 2
}
try {
    $manifest = Get-Content (Join-Path $Src "plugin.json") -Raw -Encoding UTF8 | ConvertFrom-Json
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
    $null = Get-Content $hooksPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Warning "hooks.json is not valid JSON: $($_.Exception.Message)"
    exit 2
}

# Render executable identity before either installer consumes the plugin.
# The CLI copies its supplied source into its managed plugin directory.
$systemDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::System)
$powerShell = Join-Path $systemDir "WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $powerShell -PathType Leaf)) { throw "Trusted Windows PowerShell not found at $powerShell" }
function Set-StagedHooks([string]$runPs1) {
    $escapedPowerShell = ($powerShell | ConvertTo-Json -Compress).Trim('"')
    $escapedRun = ($runPs1 | ConvertTo-Json -Compress).Trim('"')
    $rendered = (Get-Content $hooksPath -Raw -Encoding UTF8).Replace("<POWERSHELL_EXE>", $escapedPowerShell).Replace("<RUN_PS1>", $escapedRun)
    $null = $rendered | ConvertFrom-Json
    [System.IO.File]::WriteAllText((Join-Path $stage "hooks.json"), $rendered,
        (New-Object System.Text.UTF8Encoding $false))
}
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("sb-antigravity-stage-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    Copy-Item -Recurse -Force (Join-Path $Src "*") $stage

# 2. CLI target: use the official managed install when agy exists
if ($Target -eq "Cli" -or $Target -eq "Both") {
    $agy = Get-Command agy -ErrorAction SilentlyContinue
    if ($agy) {
        $cliDir = Join-Path $env:USERPROFILE ".gemini\config\plugins\second-brain-adapter"
        Set-StagedHooks (Join-Path $cliDir "scripts\run-hook.ps1")
        & agy plugin install $stage
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "agy plugin install failed (exit $LASTEXITCODE)."
            exit 3
        }
        $cliHooks = Join-Path $cliDir "hooks.json"
        $cliScript = Join-Path $cliDir "scripts\run-hook.ps1"
        if (-not (Test-Path $cliHooks -PathType Leaf) -or
            -not (Test-Path $cliScript -PathType Leaf) -or
            (Get-FileHash $cliHooks).Hash -ne (Get-FileHash (Join-Path $stage "hooks.json")).Hash -or
            (Get-FileHash $cliScript).Hash -ne (Get-FileHash (Join-Path $stage "scripts\run-hook.ps1")).Hash) {
            throw "agy installed plugin bytes or destination differ from the trusted staged hooks"
        }
        Write-Host "Registered adapter via agy plugin install."
        if ($Target -eq "Cli") { exit 0 }
    } else {
        Write-Warning "agy CLI not found; CLI target skipped. Install agy and re-run this script with -Target Cli."
        if ($Target -eq "Cli") { exit 4 }
    }
}

# 3. App target: copy with pre-install backup (skip when identical)
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$BackupDir = Join-Path $Brain "backups\$stamp-antigravity-adapter-pre-install"
Set-StagedHooks (Join-Path $TargetDir "scripts\run-hook.ps1")

$identical = $false
if (Test-Path $TargetDir) {
    $same = $true
    Get-ChildItem -Recurse -File $stage | ForEach-Object {
        $rel = $_.FullName.Substring($stage.Length)
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
    Copy-Item -Recurse -Force (Join-Path $stage "*") $TargetDir

    # Post-copy integrity: every copied file must be non-empty and byte-identical.
    $mismatch = $false
    Get-ChildItem -Recurse -File $stage | ForEach-Object {
        $rel = $_.FullName.Substring($stage.Length).TrimStart("\\")
        $dst = Join-Path $TargetDir $rel
        if (-not (Test-Path $dst) -or (Get-Item $dst).Length -eq 0) {
            Write-Warning "MISSING/EMPTY after copy: $rel"
            $mismatch = $true
        } elseif ((Get-FileHash $_.FullName).Hash -ne (Get-FileHash $dst).Hash) {
            Write-Warning "HASH MISMATCH after copy: $rel"
            $mismatch = $true
        }
    }
    if ($mismatch) {
        Write-Warning "Install incomplete; re-run after fixing the source."
        exit 5
    }
    Write-Host "Installed Second Brain Antigravity adapter to $TargetDir (hashes verified)"
    Write-Host "Pre-install backup: $BackupDir"
}
Write-Host "IMPORTANT: do NOT run 'agy plugin import' against this plugin dir (it truncates plugin files)."
Write-Host "Use scripts/install-antigravity-adapter.ps1 -Target Cli for a trusted rendered CLI install."
Write-Host "Next: enable the plugin in Antigravity (Settings -> Skills & Customizations -> Plugins) and verify hooks are listed."
} finally {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
}
exit 0
