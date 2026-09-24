<#
.SYNOPSIS
  Install the standalone Second Brain V3 OMP extension (brainstem/omp-v3/index.ts).

.DESCRIPTION
  Copies the single-file extension to <ExtensionsDir>\second-brain-v3\index.ts and checks the
  copy byte-for-byte. The legacy `second-brain` extension would push memory a second time, so
  the install refuses while it is present unless -DisableLegacy is given; that switch moves the
  legacy directory to <ExtensionsDir>\..\extensions-disabled\ (undo: uninstall-omp-v3.ps1
  -RestoreLegacy). Restart OMP afterwards. Needs SECOND_BRAIN_HOME; without it the extension
  registers nothing.
#>
[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SourceRoot,
    [switch]$DisableLegacy
)
$ErrorActionPreference = "Stop"

if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".omp\agent\extensions" }
$Src = Join-Path $SourceRoot "brainstem\omp-v3\index.ts"
if (-not (Test-Path $Src -PathType Leaf)) { throw "Extension source missing: $Src" }
$Target = Join-Path $ExtensionsDir "second-brain-v3"
$Legacy = Join-Path $ExtensionsDir "second-brain"

if (Test-Path $Legacy) {
    if (-not $DisableLegacy) {
        throw "The legacy second-brain extension is installed at $Legacy. Rerun with -DisableLegacy (reversible) so memory is not pushed twice."
    }
    $Parked = Join-Path (Split-Path $ExtensionsDir -Parent) ("extensions-disabled\second-brain-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    New-Item -ItemType Directory -Force -Path (Split-Path $Parked) | Out-Null
    Move-Item $Legacy $Parked
    Write-Host "Legacy extension parked at $Parked"
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Force $Src (Join-Path $Target "index.ts")
$Want = (Get-FileHash -Algorithm SHA256 $Src).Hash
$Got = (Get-FileHash -Algorithm SHA256 (Join-Path $Target "index.ts")).Hash
if ($Want -ne $Got) { throw "Installed extension does not match its source" }
if (-not $env:SECOND_BRAIN_HOME) {
    Write-Warning "SECOND_BRAIN_HOME is not set; the extension stays silent until it is."
}
Write-Host "Installed $Target (sha256 $($Want.ToLowerInvariant())). Run 'brain views', then restart OMP."
