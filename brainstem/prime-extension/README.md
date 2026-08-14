# Second Brain Observability — Prime Agent Extension

Measurement-only [Prime Agent](https://prime.cursor.sh) extension for The Second
Brain OS **Phase 2 (Observability)**. It observes the Prime agent lifecycle and
appends JSONL telemetry. It **never** mutates agent behavior:

- No handler returns `{block}`, `{messages}`, `{systemPrompt}`, or any patch.
- `tool_call` handlers only read `event.input` — they never modify it.
- Every handler is wrapped in try/catch; storage writes are fire-and-forget and
  never throw into the session.

## What it records

All 11 subscribed lifecycle events are mapped to schema v2 records (see
`brainstem/telemetry/SCHEMA.md` — the authoritative schema):

`session_start`, `before_agent_start`, `turn_start`, `context`, `tool_call`,
`tool_result`, `turn_end`, `session_before_compact`, `session_compact`,
`agent_end`, `session_shutdown`, plus `extension_error` for internal failures.

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

Copy this directory to `~/.prime/agent/extensions/second-brain/` (global) or
`.prime/agent/extensions/second-brain/` (project-local), then run `npm install`
there (dev deps are only needed for tests/lint — the extension itself has zero
runtime dependencies beyond Node built-ins), and restart Prime Agent
(`/reload` works for auto-discovered extensions). For a quick test:

```bash
prime-agent -p -e ./src/index.ts "Reply with exactly: ok"
```

## Config gate

| Setting | Effect |
|---|---|
| `SECOND_BRAIN_OBSERVABILITY=off\|0\|false\|no` (case-insensitive) | Disables the extension silently |
| `SECOND_BRAIN_HOME=<dir>` | Brain home (must exist, else silently disabled) |
| *(unset)* | `%USERPROFILE%\Documents\The-Second-Brain` |

Telemetry directory: `<brain-home>/telemetry/agent-performance/` (created on
first write). Session id = basename of `ctx.sessionManager.getSessionFile()`
without `.jsonl`; fallback `anon-<epochms>-<4 hex>`.

## Development

```bash
npm install
npm run typecheck   # tsc --noEmit
npm run lint        # eslint .
npm run test        # vitest run
bash tests/integration/run-integration.sh   # 2 real prime-agent runs
```

Layout:

- `src/index.ts` — factory; wires all handlers through a safe wrapper.
- `src/config.ts` — config gate (env + brain home existence).
- `src/sensors.ts` — pure event→record mappings (no fs; unit-tested).
- `src/storage.ts` — async JSONL store; promise chain; first failure logged once.
- `types/prime.d.ts` — ambient type surface for the Prime API (type-only).
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
