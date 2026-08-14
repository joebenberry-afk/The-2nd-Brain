# Thin doctor wrapper: sanitizes env and runs the Python doctor.
$ErrorActionPreference = "Stop"
$Brain = if ($env:SECOND_BRAIN_HOME) { $env:SECOND_BRAIN_HOME } else { Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
Set-Location $Brain
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$env:UV_INTERNAL__PYTHONHOME = $null
$py = Join-Path $Brain ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { Write-Error "Python not found"; exit 1 }
    $py = $cmd.Source
}
& $py -m second_brain doctor
exit $LASTEXITCODE
