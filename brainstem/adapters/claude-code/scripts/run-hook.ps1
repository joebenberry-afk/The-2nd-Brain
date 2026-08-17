# The Second Brain -- Claude Code Lifecycle Hook Launcher (THIN TRANSPORT)
#
# stdin  : Claude Code's own hook JSON payload (already carries
#          hook_event_name -- unlike Antigravity's official payload, no
#          -Event param is needed here).
# flow   : payload -> `brainctl autoinject claude-code-hook` (Python owns
#          ALL policy). This script is transport only: invoke, return
#          stdout verbatim, fail open to `{}` on any error.
# events : SessionStart, PreCompact, Stop (P3a scope only).

$ErrorActionPreference = "Stop"

$repoHome = $env:SECOND_BRAIN_HOME
if (-not $repoHome) { $repoHome = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$python = Join-Path $repoHome ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Output "{}"
    exit 0
}

$payload = ""
try {
    if ([Console]::IsInputRedirected) {
        $payload = [Console]::In.ReadToEnd()
    }
} catch {
    $payload = ""
}
if (-not $payload -or -not $payload.Trim()) {
    $payload = "{}"
}

# Clear corrupted environment variables (repo gotcha: PYTHONHOME pollution)
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null

try {
    $response = $payload | & $python -m second_brain --home $repoHome autoinject claude-code-hook 2>$null
} catch {
    $response = "{}"
}

if (-not $response -or -not $response.Trim()) {
    $response = "{}"
}

Write-Output $response
exit 0
