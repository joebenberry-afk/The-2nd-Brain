<#
.SYNOPSIS
  Install Second Brain V4 for Oh My Pi: the `brain` command and the OMP extension.

.DESCRIPTION
  - Finds a runtime: Node >= 22.18 (runs TypeScript directly) or Bun.
  - Writes brain\bin\brain.cmd (cmd.exe) and brain\bin\brain.ps1 (PowerShell; not under a
    Restricted or AllSigned execution policy, which would refuse it) next to the committed
    sh shim brain\bin\brain (Git Bash, where Claude Code runs hooks) and adds brain\bin to the user
    PATH (once; -NoPath skips). The PATH is edited as stored, so entries like %USERPROFILE%\... keep
    expanding.
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

# The user PATH as stored (REG_EXPAND_SZ): [Environment]::GetEnvironmentVariable would expand
# %VARS% and SetEnvironmentVariable would write them back frozen.
function Get-UserPath {
    $raw = (Get-Item "HKCU:\Environment").GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    return @(($raw -split ";") | Where-Object { $_ })
}
function Set-UserPath([string[]]$Parts) {
    Set-ItemProperty -Path "HKCU:\Environment" -Name Path -Value ($Parts -join ";") -Type ExpandString
    # SetEnvironmentVariable announces the change, so new terminals see the new PATH.
    [Environment]::SetEnvironmentVariable("SECOND_BRAIN_PATH_CHANGED", "1", "User")
    [Environment]::SetEnvironmentVariable("SECOND_BRAIN_PATH_CHANGED", $null, "User")
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

# 2. brain.cmd, brain.ps1 + PATH (brain\bin also holds the sh shim `brain` for Git Bash)
$BinDir = Join-Path (Join-Path $SourceRoot "brain") "bin"
Write-Utf8NoBom (Join-Path $BinDir "brain.cmd") "@$Runtime `"%~dp0brain.mjs`" %*`r`n"
# PowerShell prefers brain.ps1 to brain.cmd, whose cmd.exe expands %VAR% even inside quoted note text.
# Under a Restricted or AllSigned policy it refuses brain.ps1 without falling back to brain.cmd, so
# then only brain.cmd is kept. The Process scope is skipped: -ExecutionPolicy Bypass on this run says
# nothing about later shells, and Windows PowerShell with nothing set is Restricted.
$Policy = @("MachinePolicy", "UserPolicy", "CurrentUser", "LocalMachine") | ForEach-Object { "$(Get-ExecutionPolicy -Scope $_)" } | Where-Object { $_ -ne "Undefined" } | Select-Object -First 1
if (-not $Policy -and $PSVersionTable.PSEdition -ne "Core") { $Policy = "Restricted" }
# PowerShell 7 reads its own policy; Windows PowerShell also finds brain.ps1 and applies its own
# (Restricted by default). Ask it, without the -ExecutionPolicy this run may have inherited.
if ($PSVersionTable.PSEdition -eq "Core" -and (Get-Command powershell.exe -ErrorAction SilentlyContinue)) {
    $saved = $env:PSExecutionPolicyPreference; $env:PSExecutionPolicyPreference = $null
    try { $WinPs = "$(& powershell.exe -NoProfile -NonInteractive -Command Get-ExecutionPolicy)".Trim() } finally { $env:PSExecutionPolicyPreference = $saved }
    if ($WinPs -in @("Restricted", "AllSigned")) { $Policy = "$WinPs (Windows PowerShell)" }
}
$Ps1Shim = Join-Path $BinDir "brain.ps1"
if ($Policy -match '^(Restricted|AllSigned)') {
    if (Test-Path $Ps1Shim) { Remove-Item -Force $Ps1Shim }
    Write-Warning "Execution policy $Policy would block brain.ps1, so PowerShell runs brain.cmd: cmd.exe expands %VAR% in note text, and from Windows PowerShell double quotes inside arguments are dropped. For brain.ps1: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned, then re-run this installer."
} else {
    # argv travels as JSON in BRAIN_ARGV: Windows PowerShell 5.1 passes native arguments without
    # escaping the quotes inside them. The finally keeps it out of the caller's session.
    # [string] keeps a token as typed: interpolation reformats numbers PowerShell parsed
    # (3.10 -> 3.1, 0x80070005 -> -2147024891). "/" works for node on Windows and under Linux pwsh.
    # $OutputEncoding (script scope) keeps piped hook JSON UTF-8 without a BOM.
    $ps1 = @'
$env:BRAIN_ARGV = ConvertTo-Json -Compress -InputObject @($args | ForEach-Object { [string]$_ })
try {
    if ($MyInvocation.ExpectingInput) { $OutputEncoding = [Text.UTF8Encoding]::new($false); $input | & RUNTIME "$PSScriptRoot/brain.mjs" }
    else { & RUNTIME "$PSScriptRoot/brain.mjs" }
} finally { Remove-Item Env:BRAIN_ARGV -ErrorAction SilentlyContinue }
exit $LASTEXITCODE
'@
    Write-Utf8NoBom $Ps1Shim ($ps1.Replace("RUNTIME", $Runtime) + "`r`n")
}
$oldShim = Join-Path $SourceRoot "brain.cmd"   # written by earlier versions of this script
if (Test-Path $oldShim) { Remove-Item -Force $oldShim }
if (-not $NoPath) {
    $parts = @(Get-UserPath | Where-Object { $_.TrimEnd("\") -ne $SourceRoot })
    if (@($parts | Where-Object { $_.TrimEnd("\") -eq $BinDir }).Count -eq 0) {
        Set-UserPath ($parts + $BinDir)
        Write-Host "Added $BinDir to the user PATH (new terminals pick it up)."
    }
}

# 3. Brain home
# The process value first: it inherits the user value, and a caller (or test) may override it.
$BrainHome = $env:SECOND_BRAIN_HOME
if (-not $BrainHome) { $BrainHome = [Environment]::GetEnvironmentVariable("SECOND_BRAIN_HOME", "User") }
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
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"   # one stamp for everything parked now: -Restore brings back the set
foreach ($name in @("second-brain", "second-brain-v3")) {
    $old = Join-Path $ExtensionsDir $name
    if (Test-Path $old) {
        New-Item -ItemType Directory -Force -Path $Disabled | Out-Null
        $parked = Join-Path $Disabled "$name-$Stamp"
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
    $IndexPath = Join-Path $Target "index.ts"
    Write-Utf8NoBom $IndexPath "// Second Brain V4 (copied from $SourceRoot; re-run install-v4.ps1 -Copy after updates).`nexport { default } from `"./omp.ts`";`n"
    # Telemetry names a build by its newest source mtime: the generated loader must not be newer
    # than the checkout's sources (cli.ts included), or copy and CLI rows look like two builds.
    (Get-Item $IndexPath).LastWriteTime = (Get-ChildItem $SrcDir -Filter *.ts | Measure-Object LastWriteTime -Maximum).Maximum
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
