# Install the Second Brain OMP extension (historically named prime-extension)
# from this repository, never from Brain state. Defaults to OMP's real
# auto-discovery directory (~/.omp/agent/extensions); pass -ExtensionsDir to
# target a different install (for example a separate "Prime Agent" binary).

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
if (-not $SettingsFile) { $SettingsFile = Join-Path $env:USERPROFILE ".omp\agent\settings.json" }

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

$SourceManifest = Get-ExtensionManifest (Join-Path $SourceRoot "brainstem\prime-extension")
if ($SourceManifest.Count -eq 0) { throw "Extension source manifest is empty: $SourceRoot" }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$BackupDir = Join-Path $SourceRoot "backups\$stamp-prime-extension-pre-install"
$Stage = Join-Path $ExtensionsDir ".second-brain-install-$stamp"

New-Item -ItemType Directory -Force -Path $ExtensionsDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
if (Test-Path $Target) {
    New-Item -ItemType Directory -Force -Path (Join-Path $BackupDir "extensions") | Out-Null
    Copy-Item -Recurse -Force $Target (Join-Path $BackupDir "extensions\second-brain")
}
if (Test-Path $SettingsFile -PathType Leaf) {
    New-Item -ItemType Directory -Force -Path (Join-Path $BackupDir "settings") | Out-Null
    Copy-Item -Force $SettingsFile (Join-Path $BackupDir "settings\settings.json")
}

try {
    New-Item -ItemType Directory -Force -Path $Stage | Out-Null
    Copy-Item -Force (Join-Path $Src "*.ts") $Stage
    if (Test-Path $TypesSrc -PathType Container) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Stage "types") | Out-Null
        Copy-Item -Force (Join-Path $TypesSrc "*.d.ts") (Join-Path $Stage "types")
    }
    $InstalledManifest = Get-ExtensionManifest $Stage
    $ExpectedManifest = @($SourceManifest | Where-Object { $_ -match "^(src/.*\.ts|types/.*\.d\.ts)`t" } |
        ForEach-Object { $_ -replace "^src/", "" })
    if ((Compare-Object $ExpectedManifest $InstalledManifest).Count -ne 0) {
        throw "Installed extension manifest does not match source"
    }
    if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
    Move-Item $Stage $Target
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
