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
$python = $env:SECOND_BRAIN_PYTHON
if (-not $python) { $python = Join-Path $repoHome ".venv\Scripts\python.exe" }
if (-not (Test-Path $python)) {
    Write-Output "{}"
    exit 0
}

# Read stdin as raw UTF-8 bytes. [Console]::In.ReadToEnd() decodes through
# the ambient console input codepage, which is not guaranteed to be UTF-8
# and can leave a leading BOM character (U+FEFF) in the decoded string;
# json.loads() on the Python side then fails on that leading character,
# producing the exact anonymous/no-task fallback this adapter was silently
# hitting on nearly every real invocation. Decoding explicitly as UTF-8 and
# stripping any BOM removes that host-dependent ambiguity entirely.
$payload = ""
try {
    if ([Console]::IsInputRedirected) {
        $stdinStream = [Console]::OpenStandardInput()
        $ms = New-Object System.IO.MemoryStream
        $stdinStream.CopyTo($ms)
        $bytes = $ms.ToArray()
        if ($bytes.Length -gt 0) {
            $payload = [System.Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF)
        }
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

# Invoke the Brain CLI through System.Diagnostics.Process directly rather
# than PowerShell's `|` pipe-to-native-process operator. The pipe operator's
# stdin byte encoding is governed by ambient $OutputEncoding/console
# codepage state, which was confirmed to intermittently corrupt the JSON
# payload in real Antigravity-spawned hook invocations even though the
# identical payload bytes, replayed directly to the same Python process
# outside PowerShell's pipe, parsed and injected correctly every time.
# ProcessStartInfo.StandardInputEncoding/StandardOutputEncoding do not exist
# on the .NET Framework that hosts Windows PowerShell 5.1 (setting them
# throws, silently caught below as a fail-open {}), so raw bytes are
# written/read directly through each stream's .BaseStream instead, with an
# explicit UTF-8 encode/decode on our side — no ambient encoding state is
# ever consulted. CRITICAL: close `.BaseStream`, never the `.StandardInput`
# StreamWriter wrapper itself — `StreamWriter.Close()`/`.Dispose()` flushes
# its OWN encoding's preamble (the default `Encoding.UTF8` emits a BOM) even
# though every actual write bypassed that StreamWriter entirely; that stray
# BOM byte sequence is exactly what broke json.loads() on the Python side on
# nearly every real invocation (root cause of the P4.5 telemetry gap).
$response = "{}"
$exitCode = 0
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $python
    $psi.Arguments = "-m second_brain --home `"$repoHome`" autoinject antigravity-hook"
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $false
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)

    $inBytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $proc.StandardInput.BaseStream.Write($inBytes, 0, $inBytes.Length)
    $proc.StandardInput.BaseStream.Flush()
    $proc.StandardInput.BaseStream.Close()

    $outMs = New-Object System.IO.MemoryStream
    $proc.StandardOutput.BaseStream.CopyTo($outMs)
    $response = [System.Text.Encoding]::UTF8.GetString($outMs.ToArray())

    $proc.WaitForExit()
    $exitCode = $proc.ExitCode
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
