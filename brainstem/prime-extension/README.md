# Second Brain Observability — Prime Agent Extension

[Prime Agent](https://prime.cursor.sh) extension for The Second Brain OS
**Phase 2 (Observability) + Phase 1 (Sol minimal-orchestrator guard)**. It
observes the Prime agent lifecycle, appends JSONL telemetry, and — for
orchestrator-model sessions only (default model substring `gpt-5.6-sol`) —
blocks direct execution tools and injects the Sol contract. Everything else is
measurement-only:

- `tool_call` handlers only read `event.input` — they never modify it.
- The ONLY patches returned are: `{ block: true, reason }` from `tool_call`
  when an orchestrator model calls a blocked tool (`bash`/`edit`/`websearch`;
  `ipython` is NOT blocked — RLM delegation runs through the IPython kernel),
  and `{ systemPrompt }` from `before_agent_start` for orchestrator-model
  sessions (the condensed Sol contract). Every other session/event returns
  undefined.
- Every handler is wrapped in try/catch; storage writes are fire-and-forget and
  never throw into the session. Guard failures fail open (`extension_error`
  record, no block).

## What it records

All 11 subscribed lifecycle events are mapped to schema v2 records (see
`brainstem/telemetry/SCHEMA.md` — the authoritative schema):

`session_start`, `before_agent_start`, `turn_start`, `context`, `tool_call`,
`tool_result`, `turn_end`, `session_before_compact`, `session_compact`,
`agent_end`, `session_shutdown`, plus `extension_error` for internal failures.
`orchestrator_policy_violation` (bounded enumerated fields; **WIRED since
commit 61c536a** — emitted by the `tool_call` guard when an orchestrator-model
session is blocked, `detected_by=runtime_guard`, `blocked=true`; see
`brainstem/policies/sol-minimal-orchestrator.md` §12-13).

Each record carries `v: 2`, `ts` (ISO-8601 UTC, ms), `kind`, and `session`.
Kinds are stored in
`<brain-home>/telemetry/agent-performance/<session-stem>.jsonl` (one JSON object
per line).

## Privacy

Per `constitution/security-boundaries.md`: **no content is ever stored** —
no message text, prompts, tool I/O payloads, or chain-of-thought. Only:

- counts (messages, turns, tool results, branch entries),
- sizes (`input_bytes`, `output_bytes`, `prompt_chars`),
- flags (`is_error`, `from_extension`),
- tool names and ids,
- the bash command text (`command`), **only** for the `bash` tool, truncated to
  500 chars.

## Install

Canonical installer (backups the previous state first):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-prime-extension.ps1
```

It copies `src/*.ts` and `types/*.d.ts` to
`~/.prime/agent/extensions/second-brain/` (global auto-discovery), never edits
settings.json, and is reversible via
`scripts\uninstall-prime-extension.ps1`. Restart Prime Agent (`/reload` works
for auto-discovered extensions).

`npm install` inside this directory is for DEVELOPMENT only (tests/lint/type
check; the extension itself has zero runtime dependencies beyond Node
built-ins). For a quick uninstalled test:

```bash
prime-agent -p -e ./src/index.ts "Reply with exactly: ok"
```

## Config gate

| Setting | Effect |
|---|---|
| `SECOND_BRAIN_OBSERVABILITY=off\|0\|false\|no` (case-insensitive) | Disables the extension silently |
| `SECOND_BRAIN_HOME=<dir>` | Brain home (must exist, else silently disabled) |
| `ORCHESTRATOR_MODELS=<a,b>` | Comma-separated model-id substrings identifying the orchestrator role (default `gpt-5.6-sol`; matched case-insensitively on the lowercased model id) |
| `ORCHESTRATOR_BLOCKED_TOOLS=<a,b>` | Comma-separated tool names blocked for orchestrator sessions (default `bash,edit,websearch`; `ipython` deliberately not listed) |
| `SECOND_BRAIN_RTD=active` | RTD shadow records intent to substitute (substitution NOT implemented — shadow mode) |
| `SECOND_BRAIN_RTD_THRESHOLD=<n>` | RTD size threshold in JSON chars (default 8000) |
| *(unset)* | `%USERPROFILE%\Documents\The-Second-Brain` |

Telemetry directory: `<brain-home>/telemetry/agent-performance/` (created
once per extension lifecycle — one shared readiness step, not per record).

**Deployment status (2026-08-15):** the committed source includes the Sol
guard, but the installed copy at `~/.prime/agent/extensions/second-brain/`
predates it. Deployment is a separate step pending campaign end; until then
the live runtime remains measurement-only (advisory policy only).
Session id = basename of `ctx.sessionManager.getSessionFile()`
without `.jsonl`; fallback `anon-<epochms>-<4 hex>` **created once per
extension lifecycle** (Phase 2, 2026-08-15) so anonymous sessions write one
telemetry file instead of one per event.

## Development

```bash
npm install
npm run typecheck   # tsc --noEmit
npm run lint        # eslint .
npm run test        # vitest run
bash tests/integration/run-integration.sh   # 2 real prime-agent runs
```

Layout:

- `src/index.ts` — factory; wires all handlers through a safe wrapper + Sol guard.
- `src/config.ts` — config gate (env + brain home existence).
- `src/orchestrator-guard.ts` — pure Sol-guard decision logic (no side effects).
- `src/sensors.ts` — pure event→record mappings (no fs; unit-tested).
- `src/storage.ts` — async JSONL store; promise chain; first failure logged once.
- `types/prime.d.ts` — ambient type surface for the Prime API (type-only; includes
  `ToolCallEventResult` / `BeforeAgentStartEventResult` return shapes).
- `tests/` — Vitest unit tests + `integration/run-integration.sh`.

## Notes / limitations

- `ctx.getContextUsage()` returns `{ tokens, contextWindow, percent }` at
  runtime (verified against Prime v0.7.2); the schema field `context_usage` is
  mapped to `{ used: tokens, total: contextWindow, percent }`.
- All writes are async and unawaited (measurement must never delay the
  session). The one exception is the terminal `session_shutdown` record, which
  is written synchronously (`appendFinal`) because Prime's daemon supervisor
  tears the worker down right after the event — an async write can lose the
  race with process exit and the last record would be missing.
- In daemon-routed runs the extension runs in the daemon worker process. The
  worker inherits the client's environment, so `SECOND_BRAIN_HOME` /
  `SECOND_BRAIN_OBSERVABILITY` are honored; only `HERDR_*` vars are pinned via
  the daemon env allowlist, everything else comes from the daemon's own
  startup env.


## Production deployment note

Prime Agent runs sessions inside a daemon that inherits the environment it was
started with. Set `SECOND_BRAIN_HOME` (and optionally
`SECOND_BRAIN_OBSERVABILITY`) **before** starting `prime-agent` so the daemon
passes them to worker sessions. If the home directory does not exist or the
gate var disables observability, the extension silently writes nothing.
