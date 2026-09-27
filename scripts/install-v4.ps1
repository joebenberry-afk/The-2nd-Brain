<#
.SYNOPSIS
  Install Second Brain V4 for Oh My Pi: the `brain` command and the OMP extension.

.DESCRIPTION
  - Finds a runtime: Node >= 22.18 (runs TypeScript directly) or Bun.
  - Writes <SourceRoot>\brain.cmd and adds <SourceRoot> to the user PATH (once; -NoPath skips).
  - Sets the user variable SECOND_BRAIN_HOME to <SourceRoot> when it is unset (-NoEnv skips).
  - Parks older Brain extensions (second-brain, second-brain-v3) in ..\extensions-disabled\ so
    memory is not pushed twice (undo: uninstall-v4.ps1 -Restore).
  - Installs <ExtensionsDir>\second-brain-v4\index.ts. By default a one-line loader that imports
    brain\src\omp.ts from this checkout, so `git pull` + an OMP restart is the whole update.
    -Copy installs a self-contained copy of brain\src instead (re-run after each update); use it
    if OMP does not follow the loader.
  - Runs `brain check` against the Brain home as a self-test.
  Works with Windows PowerShell 5.1 and PowerShell 7. Restart OMP afterwards, from a new
  terminal so it sees the new environment variables.
#>
[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SourceRoot,
    [switch]$NoPath,
    [switch]$NoEnv,
    [switch]$Copy
)
$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path (Join-Path $HOME ".omp") "agent/extensions" }
$ExtensionsDir = [System.IO.Path]::GetFullPath($ExtensionsDir)
$SrcDir = Join-Path $SourceRoot "brain/src"
$Entry = Join-Path $SrcDir "omp.ts"
if (-not (Test-Path $Entry -PathType Leaf)) { throw "Extension source missing: $Entry" }

# 1. Runtime
$Runtime = $null
if (Get-Command node -ErrorAction SilentlyContinue) {
    $v = ((& node --version) -replace '^v', '').Split(".")
    if ([int]$v[0] -gt 22 -or ([int]$v[0] -eq 22 -and [int]$v[1] -ge 18)) { $Runtime = "node" }
}
if (-not $Runtime -and (Get-Command bun -ErrorAction SilentlyContinue)) { $Runtime = "bun" }
if (-not $Runtime) { throw "Need Node >= 22.18 or Bun on PATH." }

# 2. brain.cmd + PATH
Write-Utf8NoBom (Join-Path $SourceRoot "brain.cmd") "@$Runtime `"%~dp0brain\bin\brain.mjs`" %*`r`n"
if (-not $NoPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @(($userPath -split ";") | Where-Object { $_ })
    if ($parts -notcontains $SourceRoot) {
        [Environment]::SetEnvironmentVariable("Path", (($parts + $SourceRoot) -join ";"), "User")
        Write-Host "Added $SourceRoot to the user PATH (new terminals pick it up)."
    }
}

# 3. Brain home
$BrainHome = [Environment]::GetEnvironmentVariable("SECOND_BRAIN_HOME", "User")
if (-not $BrainHome) { $BrainHome = $env:SECOND_BRAIN_HOME }
if (-not $BrainHome) {
    $BrainHome = $SourceRoot
    if (-not $NoEnv) {
        [Environment]::SetEnvironmentVariable("SECOND_BRAIN_HOME", $SourceRoot, "User")
        Write-Host "SECOND_BRAIN_HOME = $SourceRoot"
    }
} elseif ([System.IO.Path]::GetFullPath($BrainHome) -ne $SourceRoot) {
    Write-Warning "SECOND_BRAIN_HOME is $BrainHome, not this checkout; the extension will use it."
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

# 5. Extension
$Target = Join-Path $ExtensionsDir "second-brain-v4"
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
if ($Copy) {
    Get-ChildItem $SrcDir -Filter *.ts | Where-Object { $_.Name -ne "cli.ts" } | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $Target $_.Name)
    }
    Write-Utf8NoBom (Join-Path $Target "index.ts") "// Second Brain V4 (copied from $SourceRoot; re-run install-v4.ps1 -Copy after updates).`nexport { default } from `"./omp.ts`";`n"
    $mode = "copy"
} else {
    $importPath = $Entry.Replace("\", "/")
    Write-Utf8NoBom (Join-Path $Target "index.ts") "// Second Brain V4: loads the extension from the Brain checkout; git pull + OMP restart updates it.`nexport { default } from `"$importPath`";`n"
    $mode = "loader"
}

# 6. Self-test
& $Runtime (Join-Path $SourceRoot "brain/bin/brain.mjs") check --home $BrainHome
if ($LASTEXITCODE -ne 0) { Write-Warning "brain check reported problems (see above); the extension still loads." }

Write-Host "Installed ($mode, runtime: $Runtime, home: $BrainHome). Restart OMP from a new terminal."
