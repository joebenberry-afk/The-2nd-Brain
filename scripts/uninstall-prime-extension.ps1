# Remove the Second Brain OMP extension (historically named prime-extension)
# and optionally restore the exact installer-owned backup named by -BackupDir.
# Defaults to OMP's real auto-discovery directory
# (~/.omp/agent/extensions); settings are never modified.

[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SettingsFile,
    [string]$SourceRoot,
    [string]$BackupDir
)

$ErrorActionPreference = "Stop"

# Accepted for command-line compatibility only; rollback is bound to BackupDir
# metadata and never reads source/state or modifies settings.
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".omp\agent\extensions" }
$ExtensionsDir = [System.IO.Path]::GetFullPath($ExtensionsDir)
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

if ((Test-Path $ExtensionsDir) -and -not (Test-Path $ExtensionsDir -PathType Container)) {
    throw "Extensions destination is not a directory: $ExtensionsDir"
}
if ((Test-Path $Target) -and -not (Test-Path $Target -PathType Container)) {
    throw "Extension destination is not a directory: $Target"
}

if (-not $BackupDir) {
    if (Test-Path $Target) {
        Remove-Item -Recurse -Force $Target
        Write-Host "Removed $Target"
    } else {
        Write-Host "Extension is not installed at $Target"
    }
    Write-Host "No backup specified; no backup was selected automatically."
    exit 0
}

$BackupDir = [System.IO.Path]::GetFullPath($BackupDir)
if (-not (Test-Path $BackupDir -PathType Container)) {
    throw "Backup directory does not exist: $BackupDir"
}
$RecordFile = Join-Path $BackupDir "install.json"
if (-not (Test-Path $RecordFile -PathType Leaf)) {
    throw "Backup is not an installer-owned extension backup: $BackupDir"
}
try {
    $BackupRecord = Get-Content -Raw -Path $RecordFile | ConvertFrom-Json
} catch {
    throw "Backup metadata is invalid: $RecordFile"
}
$RecordProperties = @($BackupRecord.PSObject.Properties.Name)
if (
    $BackupRecord.schema_version -ne 1 -or
    -not $BackupRecord.target -or
    $RecordProperties -notcontains "had_extension" -or
    -not ($BackupRecord.had_extension -is [bool]) -or
    $RecordProperties -notcontains "extension_manifest"
) {
    throw "Backup metadata is unsupported: $RecordFile"
}
$RecordedTarget = [System.IO.Path]::GetFullPath([string]$BackupRecord.target)
if (-not [StringComparer]::OrdinalIgnoreCase.Equals($RecordedTarget, $Target)) {
    throw "Backup target '$RecordedTarget' does not match destination '$Target'"
}

$HadExtension = [bool]$BackupRecord.had_extension
$Previous = Join-Path $BackupDir "extensions\second-brain"
$ExpectedManifest = @($BackupRecord.extension_manifest)
if ($HadExtension) {
    if (-not (Test-Path $Previous -PathType Container)) {
        throw "Backup is missing the previous extension: $Previous"
    }
    if ((Compare-Object $ExpectedManifest (Get-ExtensionManifest $Previous)).Count -ne 0) {
        throw "Backup contents do not match installer metadata: $BackupDir"
    }
} elseif (Test-Path $Previous) {
    throw "Backup metadata does not match its extension contents: $BackupDir"
}

if (-not $HadExtension) {
    if (Test-Path $Target) {
        Remove-Item -Recurse -Force $Target
        Write-Host "Removed $Target"
    }
    Write-Host "Restored pre-install state (extension absent) from $BackupDir"
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$RestoreStage = Join-Path $ExtensionsDir ".second-brain-restore-$stamp"
$Displaced = Join-Path $ExtensionsDir ".second-brain-uninstall-$stamp"
New-Item -ItemType Directory -Force -Path $ExtensionsDir | Out-Null
try {
    Copy-Item -Recurse -Force $Previous $RestoreStage
    if ((Compare-Object $ExpectedManifest (Get-ExtensionManifest $RestoreStage)).Count -ne 0) {
        throw "Staged restore does not match backup"
    }
    $TargetDisplaced = $false
    if (Test-Path $Target) {
        Move-Item $Target $Displaced
        $TargetDisplaced = $true
    }
    try {
        Move-Item $RestoreStage $Target
    } catch {
        if ($TargetDisplaced) {
            if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
            Move-Item $Displaced $Target
        }
        throw
    }
    if (Test-Path $Displaced) { Remove-Item -Recurse -Force $Displaced }
} catch {
    if (Test-Path $RestoreStage) { Remove-Item -Recurse -Force $RestoreStage }
    throw
}

Write-Host "Restored previous extension from $Previous"
$PreviousSettings = Join-Path $BackupDir "settings\settings.json"
if (Test-Path $PreviousSettings -PathType Leaf) {
    Write-Host "settings.json backup retained at $PreviousSettings"
}
exit 0
