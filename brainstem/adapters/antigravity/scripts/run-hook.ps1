# The Second Brain — Antigravity Lifecycle Hook Launcher (THIN TRANSPORT)
#
# stdin  : Antigravity hook JSON payload (official camelCase contract)
# flow   : payload -> `brainctl autoinject antigravity-hook` (Python control
#          authority owns ALL policy: AutoInject mode, Lean runtime, Stop
#          decision). This script is a transport only:
#            * attaches the event name from the hook command line when the
#              Antigravity input carries no event field (the official payload
#              has none — the event is implicit in the hook);
#            * invokes the canonical Brain CLI;
#            * returns the Brain-generated Antigravity response verbatim;
#            * fails open to `{}` on launcher errors.
#
# It NEVER decides AutoInject visibility, NEVER defaults a mode, and NEVER
# suppresses the Brain's response. AutoInject mode resolution lives in the
# Brain (env override > config/autoinject.toml > default), not here.

[CmdletBinding()]
param(
    [string]$Event = "PreInvocation"
)

$ErrorActionPreference = "Stop"

$repoHome = $env:SECOND_BRAIN_HOME
if (-not $repoHome) { $repoHome = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$python = Join-Path $repoHome ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Output "{}"
    exit 0
}

# Read stdin payload if available
$payload = ""
try {
    if ([Console]::IsInputRedirected) {
        $payload = [Console]::In.ReadToEnd()
    }
} catch {
    $payload = ""
}

# Attach the event name ONLY when the payload lacks one (official payloads
# have no event field; legacy/internal callers may).
if ($payload -and $payload.Trim()) {
    try {
        $obj = $payload | ConvertFrom-Json
        if (-not $obj.event) {
            $obj | Add-Member -NotePropertyName "event" -NotePropertyValue $Event -Force
            $payload = $obj | ConvertTo-Json -Compress
        }
    } catch {
        # Non-JSON payload: pass through as-is; the Python handler fails open.
    }
} else {
    $payload = "{`"event`": `"$Event`"}"
}

# Clear corrupted environment variables (repo gotcha: PYTHONHOME pollution)
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null

try {
    $response = $payload | & $python -m second_brain --home $repoHome autoinject antigravity-hook 2>$null
    $exitCode = $LASTEXITCODE
} catch {
    $response = "{}"
    $exitCode = 0
}

if (-not $response -or -not $response.Trim()) {
    $response = "{}"
}

# The Brain's response is authoritative: return it verbatim (it already
# conforms to the official Antigravity result contract per event).
Write-Output $response
exit 0
