#!/usr/bin/env bash
# Integration test for the Second Brain observability extension.
#
# Runs real prime-agent invocations (2 total) against a temp brain home and
# asserts the telemetry pipeline end-to-end:
#   1. enabled run   -> exactly one .jsonl, all lines v==2, kinds present,
#                       session field matches a real session file
#   2. disabled run  -> SECOND_BRAIN_OBSERVABILITY=off -> no new .jsonl
#
# Env isolation notes:
#   - PRIME_AGENT_INTERNAL_* vars are stripped so a nested agent never
#     inherits the parent daemon's worker identity.
#   - Each run uses a dedicated --daemon-socket pipe. Prime Agent routes
#     print-mode runs through a daemon, and the daemon only pins HERDR_*
#     client env vars; a fresh daemon (spawned from this process) inherits
#     SECOND_BRAIN_HOME / SECOND_BRAIN_OBSERVABILITY, which a shared daemon
#     would not. Each test daemon is shut down afterwards.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../" && pwd)"
EXT_SRC="$REPO_ROOT/brainstem/prime-extension/src/index.ts"
PRIME_SH="${PRIME_SH:-C:/Tools/prime-agent/prime-agent.sh}"
MODEL="${MODEL:-deepseek/deepseek-v4-flash}"

# ---------------------------------------------------------------------------
# Environment hygiene
# ---------------------------------------------------------------------------
unset PRIME_AGENT_INTERNAL_DAEMON_SUPERVISOR_SOCKET \
      PRIME_AGENT_INTERNAL_DAEMON_WORKER \
      PRIME_AGENT_INTERNAL_DAEMON_WORKER_ACTIVE_SESSION_ID \
      PRIME_AGENT_INTERNAL_DAEMON_WORKER_RECOVERY_JOURNAL \
      PRIME_AGENT_INTERNAL_DAEMON_WORKER_TOKEN \
      PRIME_AGENT_INTERNAL_ORPHAN_PROCESS_JOURNAL \
      PRIME_AGENT_INTERNAL_SESSION_LEASES \
      PRIME_AGENT_INTERNAL_SESSION_LEASE_OWNER_ID \
      PRIME_AGENT_INTERNAL_SESSION_LEASE_CREATED_AT \
      PRIME_AGENT_LAUNCHER_PATH \
      PRIME_AGENT_BUILD_ID 2>/dev/null || true
unset PYTHONHOME PYTHONPATH UV_INTERNAL__PYTHONHOME PYTHONSTARTUP

TMP="$(mktemp -d)"
TMP_WIN="$(cygpath -w "$TMP" 2>/dev/null || echo "$TMP")"
trap 'rm -rf "$TMP"' EXIT

# Host session/config files must not fall back to the user's real profile.
export HOME="$TMP"
export USERPROFILE="$TMP_WIN"
export XDG_CONFIG_HOME="$TMP/config-home"
export XDG_DATA_HOME="$TMP/data-home"

# A minimal but plausible brain home: VERSION + config/brain.toml +
# pre-created telemetry dir.
mkdir -p "$TMP/telemetry/agent-performance"
echo "0.4.0" > "$TMP/VERSION"
mkdir -p "$TMP/config"
printf 'schema_version = 1\n' > "$TMP/config/brain.toml"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "  ok: $*"; }

export SECOND_BRAIN_HOME="$TMP_WIN"
# The disposable home has no interpreter. Bind bridges to this candidate,
# never to an inherited Python or the installed Brain.
export SECOND_BRAIN_PYTHON="$(cygpath -w "$REPO_ROOT/.venv/Scripts/python.exe" 2>/dev/null || echo "$REPO_ROOT/.venv/Scripts/python.exe")"
test -f "$REPO_ROOT/.venv/Scripts/python.exe" || fail "candidate Python is missing"

run_agent() { # $1 = label, $2 = daemon pipe
  local label="$1" pipe="$2"
  local out
  echo "==> run: $label"
  echo "    cmd: env SECOND_BRAIN_HOME=$TMP_WIN SECOND_BRAIN_OBSERVABILITY=${SECOND_BRAIN_OBSERVABILITY:-<unset>} bash $PRIME_SH -p -e $EXT_SRC -nt --model $MODEL --offline --daemon-socket $pipe \"Reply with exactly: ok\""
  out="$("$PRIME_SH" -p -e "$EXT_SRC" -nt --model "$MODEL" --offline --daemon-socket "$pipe" "Reply with exactly: ok" 2>&1)" || fail "$label: prime-agent exited $?; output: $(printf '%s' "$out" | tail -n 5)"
  printf '%s\n' "$out" | sed 's/^/    out: /' | tail -n 3
  echo "    (exit 0)"
  # Shut the dedicated daemon down again.
  "$PRIME_SH" daemon shutdown --daemon-socket "$pipe" >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# Run 1: enabled
# ---------------------------------------------------------------------------
run_agent "enabled" "\\\\.\\pipe\\sb-obs-${$}-1"

TELEMETRY_DIR="$TMP/telemetry/agent-performance"
FILES=("$TELEMETRY_DIR"/*.jsonl)
[[ ${#FILES[@]} -eq 1 && -f "${FILES[0]}" ]] || fail "expected exactly one .jsonl in $TELEMETRY_DIR, found: ${FILES[*]:-none}"
TELEMETRY_FILE="${FILES[0]}"
pass "exactly one telemetry file: $(basename "$TELEMETRY_FILE")"

# First line -> session id (also validates v==2 on line 1)
SESSION_ID="$(node -e '
const fs = require("fs");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").trim().split("\n");
if (lines.length === 0 || !lines[0]) { console.error("empty telemetry file"); process.exit(1); }
const rec = JSON.parse(lines[0]);
if (rec.v !== 2) { console.error("first record v != 2: " + JSON.stringify(rec)); process.exit(1); }
process.stdout.write(rec.session);
' "$TELEMETRY_FILE")" || fail "telemetry file empty or first record has v!=2"
pass "session id from telemetry: $SESSION_ID"

# Every line: JSON, v==2, has kind/session/ts; required kinds present
node -e '
const fs = require("fs");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").trim().split("\n");
const kinds = [];
for (const line of lines) {
  if (!line) continue;
  const rec = JSON.parse(line);
  if (rec.v !== 2) { console.error("record v != 2: " + line); process.exit(1); }
  if (typeof rec.kind !== "string" || !rec.kind) { console.error("record missing kind: " + line); process.exit(1); }
  if (typeof rec.session !== "string" || !rec.session) { console.error("record missing session: " + line); process.exit(1); }
  if (typeof rec.ts !== "string" || Number.isNaN(Date.parse(rec.ts))) { console.error("record bad ts: " + line); process.exit(1); }
  kinds.push(rec.kind);
}
for (const required of ["session_start", "turn_start", "turn_end", "session_shutdown"]) {
  if (!kinds.includes(required)) { console.error("missing required kind " + required + "; got: " + kinds.join(",")); process.exit(1); }
}
process.stdout.write(kinds.join(","));
' "$TELEMETRY_FILE" || fail "telemetry content assertions failed"
pass "all lines valid (v==2); required kinds present (see kinds above)"

# Session field must match a real session file, unless anonymous fallback
if [[ "$SESSION_ID" == anon-* ]]; then
  pass "session id is the anonymous fallback; skipping session-file match"
else
  MATCHED=""
  for SESS_DIR in "$HOME/.prime/agent/sessions" "$USERPROFILE/.prime/agent/sessions"; do
    if [[ -n "$SESS_DIR" && -f "$SESS_DIR/$SESSION_ID.jsonl" ]]; then MATCHED="$SESS_DIR"; break; fi
  done
  [[ -n "$MATCHED" ]] || fail "no session file found for telemetry session id $SESSION_ID under ~/.prime/agent/sessions"
  pass "session $SESSION_ID matches $MATCHED/$SESSION_ID.jsonl"
fi

# ---------------------------------------------------------------------------
# Run 2: disabled
# ---------------------------------------------------------------------------
BEFORE="$(find "$TELEMETRY_DIR" -maxdepth 1 -name '*.jsonl' | wc -l | tr -d ' ')"
export SECOND_BRAIN_OBSERVABILITY=off
run_agent "disabled" "\\\\.\\pipe\\sb-obs-${$}-2"
unset SECOND_BRAIN_OBSERVABILITY
AFTER="$(find "$TELEMETRY_DIR" -maxdepth 1 -name '*.jsonl' | wc -l | tr -d ' ')"
[[ "$BEFORE" -eq "$AFTER" ]] || fail "disabled run created telemetry (before=$BEFORE after=$AFTER)"
pass "disabled run wrote no telemetry (before=$BEFORE after=$AFTER)"

echo "ALL INTEGRATION CHECKS PASSED"
