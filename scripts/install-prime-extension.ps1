# Install the Second Brain OMP extension (historically named prime-extension)
# from this repository, never from Brain state. Defaults to OMP's real
# auto-discovery directory (~/.omp/agent/extensions); pass -ExtensionsDir to
# target a different install. Settings are never modified.

[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SettingsFile,
    [string]$SourceRoot
)

$ErrorActionPreference = "Stop"

if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".omp\agent\extensions" }
$ExtensionsDir = [System.IO.Path]::GetFullPath($ExtensionsDir)

$Src = Join-Path $SourceRoot "brainstem\prime-extension\src"
$TypesSrc = Join-Path $SourceRoot "brainstem\prime-extension\types"
$Target = Join-Path $ExtensionsDir "second-brain"

function Get-ExtensionManifest([string]$Root) {
    if (-not (Test-Path $Root -PathType Container)) { return @() }
    return @(Get-ChildItem -Path $Root -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($Root.Length).TrimStart("\", "/").Replace("\", "/")
            "$relative`t$((Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLowerInvariant())"
        })
}

function Get-ManifestHash([string[]]$Manifest) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Manifest -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $sha.Dispose() }
}

if (-not (Test-Path (Join-Path $Src "index.ts") -PathType Leaf)) {
    throw "Extension source missing index.ts: $Src"
}

$ExpectedManifest = @(
    Get-ChildItem -Path $Src -File -Filter "*.ts" | ForEach-Object {
        "$($_.Name)`t$((Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLowerInvariant())"
    }
    if (Test-Path $TypesSrc -PathType Container) {
        Get-ChildItem -Path $TypesSrc -File -Filter "*.d.ts" | ForEach-Object {
            "types/$($_.Name)`t$((Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLowerInvariant())"
        }
    }
) | Sort-Object
if ($ExpectedManifest.Count -eq 0) { throw "Extension source manifest is empty: $SourceRoot" }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$BackupDir = Join-Path $SourceRoot "backups\$stamp-prime-extension-pre-install"
$Stage = Join-Path $ExtensionsDir ".second-brain-install-$stamp"
$Displaced = Join-Path $ExtensionsDir ".second-brain-previous-$stamp"
if ((Test-Path $ExtensionsDir) -and -not (Test-Path $ExtensionsDir -PathType Container)) {
    throw "Extensions destination is not a directory: $ExtensionsDir"
}
if ((Test-Path $Target) -and -not (Test-Path $Target -PathType Container)) {
    throw "Extension destination is not a directory: $Target"
}
New-Item -ItemType Directory -Force -Path $ExtensionsDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$BackupManifest = @(Get-ExtensionManifest $Target)
$HadExtension = Test-Path $Target -PathType Container
if ($HadExtension) {
    $Previous = Join-Path $BackupDir "extensions\second-brain"
    New-Item -ItemType Directory -Force -Path (Split-Path $Previous) | Out-Null
    Copy-Item -Recurse -Force $Target $Previous
    if ((Compare-Object $BackupManifest (Get-ExtensionManifest $Previous)).Count -ne 0) {
        throw "Pre-install backup does not match the existing extension"
    }
}
if ($SettingsFile -and (Test-Path $SettingsFile -PathType Leaf)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $BackupDir "settings") | Out-Null
    Copy-Item -Force $SettingsFile (Join-Path $BackupDir "settings\settings.json")
}
$BackupRecord = [ordered]@{
    schema_version = 1
    target = $Target
    had_extension = [bool]$HadExtension
    extension_manifest = @($BackupManifest)
}
$BackupRecord | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 -Path (Join-Path $BackupDir "install.json")

try {
    New-Item -ItemType Directory -Force -Path $Stage | Out-Null
    Copy-Item -Force (Join-Path $Src "*.ts") $Stage
    if (Test-Path $TypesSrc -PathType Container) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Stage "types") | Out-Null
        Copy-Item -Force (Join-Path $TypesSrc "*.d.ts") (Join-Path $Stage "types")
    }
    $StagedManifest = @(Get-ExtensionManifest $Stage)
    if ((Compare-Object $ExpectedManifest $StagedManifest).Count -ne 0) {
        throw "Installed extension manifest does not match source"
    }
    $TargetDisplaced = $false
    if (Test-Path $Target) {
        Move-Item $Target $Displaced
        $TargetDisplaced = $true
    }
    try {
        Move-Item $Stage $Target
    } catch {
        if ($TargetDisplaced) {
            if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
            Move-Item $Displaced $Target
        }
        throw
    }
    # The verified stage is only a statement about the staged bytes: re-verify
    # what actually landed in the discovery path, and undo the swap when it does
    # not match. Otherwise an interrupted or partial move could leave an
    # unverified extension loaded by OMP while the install reported success.
    $InstalledManifest = @(Get-ExtensionManifest $Target)
    if ((Compare-Object $ExpectedManifest $InstalledManifest).Count -ne 0) {
        Remove-Item -Recurse -Force $Target
        if ($TargetDisplaced) {
            Move-Item $Displaced $Target
            $TargetDisplaced = $false
        }
        throw "Installed extension manifest does not match source after swap"
    }
    if (Test-Path $Displaced) { Remove-Item -Recurse -Force $Displaced }
} catch {
    if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
    throw
}

$SourceCommit = "unknown"
if (Test-Path (Join-Path $SourceRoot ".git")) {
    $SourceCommit = (& git -C $SourceRoot rev-parse HEAD 2>$null)
}
$ManifestHash = Get-ManifestHash $InstalledManifest
Write-Host "Source repository: $SourceRoot"
Write-Host "Source commit: $SourceCommit"
Write-Host "Target: $Target"
Write-Host "File count: $($InstalledManifest.Count)"
Write-Host "Manifest SHA-256: $ManifestHash"
Write-Host "Pre-install backup: $BackupDir"
Write-Host "Restart OMP or run /reload to load the extension."
exit 0
