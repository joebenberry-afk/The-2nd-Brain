<#
.SYNOPSIS
  Install Second Brain V4 for Oh My Pi: the `brain` command and the OMP extension.

.DESCRIPTION
  - Finds a runtime: Node >= 22.18 (runs TypeScript directly) or Bun.
  - Writes <SourceRoot>\brain.cmd and adds <SourceRoot> to the user PATH (once).
  - Sets the user variable SECOND_BRAIN_HOME to <SourceRoot> when it is unset.
  - Parks older Brain extensions (second-brain, second-brain-v3) in ..\extensions-disabled\ so
    memory is not pushed twice (undo: uninstall-v4.ps1 -Restore).
  - Writes <ExtensionsDir>\second-brain-v4\index.ts, a one-line loader that imports the extension
    from this checkout, so `git pull` + an OMP restart is the whole update.
  Nothing else on the machine changes. Restart OMP afterwards.
#>
[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SourceRoot,
    [switch]$NoPath
)
$ErrorActionPreference = "Stop"

if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path $env:USERPROFILE ".omp\agent\extensions" }
$Entry = Join-Path $SourceRoot "brain\src\omp.ts"
if (-not (Test-Path $Entry -PathType Leaf)) { throw "Extension source missing: $Entry" }

# 1. Runtime
$Runtime = $null
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $v = (& node --version).TrimStart("v").Split(".")
    if ([int]$v[0] -gt 22 -or ([int]$v[0] -eq 22 -and [int]$v[1] -ge 18)) { $Runtime = "node" }
}
if (-not $Runtime -and (Get-Command bun -ErrorAction SilentlyContinue)) { $Runtime = "bun" }
if (-not $Runtime) { throw "Need Node >= 22.18 or Bun on PATH." }

# 2. brain.cmd + PATH
$Shim = Join-Path $SourceRoot "brain.cmd"
Set-Content -Path $Shim -Encoding ASCII -Value "@$Runtime `"%~dp0brain\bin\brain.mjs`" %*"
if (-not $NoPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($userPath -split ";" | Where-Object { $_ })
    if ($parts -notcontains $SourceRoot) {
        [Environment]::SetEnvironmentVariable("Path", (($parts + $SourceRoot) -join ";"), "User")
        Write-Host "Added $SourceRoot to the user PATH (new terminals pick it up)."
    }
}

# 3. Brain home
if (-not [Environment]::GetEnvironmentVariable("SECOND_BRAIN_HOME", "User")) {
    [Environment]::SetEnvironmentVariable("SECOND_BRAIN_HOME", $SourceRoot, "User")
    Write-Host "SECOND_BRAIN_HOME = $SourceRoot"
}

# 4. Park older extensions
$Disabled = Join-Path (Split-Path $ExtensionsDir -Parent) "extensions-disabled"
foreach ($name in @("second-brain", "second-brain-v3")) {
    $old = Join-Path $ExtensionsDir $name
    if (Test-Path $old) {
        New-Item -ItemType Directory -Force -Path $Disabled | Out-Null
        $parked = Join-Path $Disabled ("$name-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        Move-Item $old $parked
        Write-Host "Parked $name at $parked"
    }
}

# 5. Extension loader
$Target = Join-Path $ExtensionsDir "second-brain-v4"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$ImportPath = $Entry.Replace("\", "/")
Set-Content -Path (Join-Path $Target "index.ts") -Encoding UTF8 -Value @(
    "// Second Brain V4: loads the extension from the Brain checkout; git pull + OMP restart updates it.",
    "export { default } from `"$ImportPath`";"
)

Write-Host "Installed (runtime: $Runtime). Check with: brain check   then restart OMP."
