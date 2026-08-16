# Second Brain P0 Codex hook launcher — SHADOW (Phase 0C part 2; plan §6.10).
#
# stdin : Codex hook JSON payload (UserPromptSubmit/SubagentStart/SessionStart
#         carry {prompt|task, session_id, cwd, ...}).
# flow  : payload -> `brainctl autoinject codex-shadow` (Python control
#         authority; task text travels via stdin only, never argv).
# stdout: `{}` — SHADOW invariant: no additionalContext, no model-visible
#         mutation. The decision JSON is appended (privacy-safe) to
#         <brain>/telemetry/agent-performance/codex-hooks.jsonl.
# exit  : forwards the CLI exit code; the CLI always exits 0 on handled
#         failures (fail-open), so hooks never break the Codex session.
$ErrorActionPreference = "Stop"

$repoHome = $env:SECOND_BRAIN_HOME
if (-not $repoHome) { $repoHome = Join-Path $env:USERPROFILE "Documents\The-Second-Brain" }
$python = Join-Path $repoHome ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Write-Output "{}"; exit 0 }

$payload = [Console]::In.ReadToEnd()

# Strip the corrupted user-level Python env (repo AGENTS.md gotcha).
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null

$decisionJson = $payload | & $python -m second_brain --home $repoHome autoinject codex-shadow 2>$null
$exitCode = $LASTEXITCODE

try {
  # Privacy-safe decision record (SCHEMA.md rules): counts/ids/hash only —
  # never task text, never packet content.
  $parsed = $decisionJson | ConvertFrom-Json
  $record = @{
    v = 2
    ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    kind = "codex_hook_shadow_decision"
    decision = $parsed.decision
    reason = $parsed.reason
    packet_tokens = $parsed.packet_tokens
    delivery_id = $parsed.delivery_id
    candidate_count = @($parsed.candidate_ids).Count
    selected_count = @($parsed.selected_ids).Count
  } | ConvertTo-Json -Compress
  $tdir = Join-Path $repoHome "telemetry\agent-performance"
  New-Item -ItemType Directory -Force -Path $tdir | Out-Null
  $logPath = Join-Path $tdir "codex-hooks.jsonl"
  # no-BOM append: BOM would corrupt the first JSONL line for telemetry readers
  [System.IO.File]::AppendAllText($logPath, $record + "`r`n",
      (New-Object System.Text.UTF8Encoding $false))
} catch {
  # logging must never fail the hook
}

Write-Output "{}"
exit $exitCode
