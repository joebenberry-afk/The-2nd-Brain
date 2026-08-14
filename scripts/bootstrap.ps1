# The Second Brain — Windows bootstrap (plan §83)
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 [-Force] [-PersistEnv] [-SkipVenv]
# Never silently edits global agent configs; adapters are a separate step.

[CmdletBinding()]
param(
    [switch]$Force,        # allow bootstrap into an existing non-empty non-Brain directory
    [switch]$PersistEnv,   # persist SECOND_BRAIN_HOME at User scope (after checks pass)
    [switch]$SkipVenv      # use system python instead of creating/using .venv
)

$ErrorActionPreference = "Stop"

# 1. Resolve Brain root: $SECOND_BRAIN_HOME, else the canonical Documents path.
if ($env:SECOND_BRAIN_HOME) {
    $Brain = $env:SECOND_BRAIN_HOME
} else {
    $Brain = Join-Path $env:USERPROFILE "Documents\The-Second-Brain"
}
$Brain = [System.IO.Path]::GetFullPath($Brain)
Write-Host "Brain root: $Brain"

# Sanitize the known-bad PYTHONHOME pollution before launching any Python.
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$env:UV_INTERNAL__PYTHONHOME = $null

# 2. Refuse unsafe overwrite of unrelated existing data.
$isBrain = (Test-Path (Join-Path $Brain "VERSION")) -or (Test-Path (Join-Path $Brain "config\brain.toml"))
if (Test-Path $Brain) {
    $nonEmpty = Get-ChildItem -Path $Brain -Force | Where-Object { $_.Name -ne ".git" }
    if ($nonEmpty -and -not $isBrain -and -not $Force) {
        Write-Error "Refusing: $Brain exists, is non-empty, and is not a Brain. Re-run with -Force only if you are certain."
        exit 2
    }
}
New-Item -ItemType Directory -Force -Path $Brain | Out-Null
Set-Location $Brain

# 3. Create backup directory (derived data).
New-Item -ItemType Directory -Force -Path (Join-Path $Brain "backups") | Out-Null

# 4. Verify Python.
$Py = $null
if (-not $SkipVenv) {
    $venvPy = Join-Path $Brain ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { $Py = $venvPy }
}
if (-not $Py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        & python --version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $Py = (Get-Command python).Source }
    }
    if (-not $Py) {
        $cmd = Get-Command py -ErrorAction SilentlyContinue
        if ($cmd) { $Py = (Get-Command py).Source }
    }
}
if (-not $Py) {
    Write-Error "Python not found. Install Python 3.11+ and re-run."
    exit 1
}
Write-Host "Python: $Py"

# 5. Verify Git.
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    Write-Error "Git not found. Install Git for Windows and re-run."
    exit 1
}

# 6. Initialize venv (unless -SkipVenv).
if (-not $SkipVenv) {
    $venvPy = Join-Path $Brain ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Host "Creating venv..."
        & $Py -m venv (Join-Path $Brain ".venv")
        if ($LASTEXITCODE -ne 0) { Write-Error "venv creation failed"; exit 1 }
    }
    $Py = $venvPy
    # 8a. Install the package into the venv (config files come from the repo).
    # Prefer uv (the documented environment manager); fall back to pip.
    # Note: uv-created venvs do not include pip by default.
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) {
        & uv pip install -q -e . --python $Py
        if ($LASTEXITCODE -ne 0) { Write-Error "uv pip install -e . failed"; exit 1 }
    } else {
        & $Py -m pip install -q -e .
        if ($LASTEXITCODE -ne 0) { Write-Error "pip install -e . failed"; exit 1 }
    }
}

# 7. Initialize Git (only when missing).
if (-not (Test-Path (Join-Path $Brain ".git"))) {
    & git init | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error "git init failed"; exit 1 }
}

# 8b/9. Initialize layout + config presence + SQLite via brainctl init (idempotent).
& $Py -m second_brain init
if ($LASTEXITCODE -ne 0) { Write-Error "brainctl init failed"; exit 1 }

# 10. Run doctor.
& $Py -m second_brain doctor
$doctorExit = $LASTEXITCODE

# Persist SECOND_BRAIN_HOME only when explicitly requested AND doctor passed.
if ($PersistEnv) {
    if ($doctorExit -ne 0) {
        Write-Warning "Doctor did not pass; skipping SECOND_BRAIN_HOME persistence."
    } else {
        [Environment]::SetEnvironmentVariable("SECOND_BRAIN_HOME", $Brain, "User")
        Write-Host "SECOND_BRAIN_HOME persisted at User scope: $Brain"
    }
}

# 11. Next steps.
Write-Host ""
Write-Host "Next steps:"
Write-Host "  brainctl status"
Write-Host "  brainctl project add <path-to-repo>"
Write-Host "  brainctl backup"
if (-not $PersistEnv) {
    Write-Host "  To persist SECOND_BRAIN_HOME for all future shells (after doctor passes):"
    Write-Host "    [Environment]::SetEnvironmentVariable('SECOND_BRAIN_HOME', '$Brain', 'User')"
}
exit $doctorExit
