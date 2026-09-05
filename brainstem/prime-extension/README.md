# Second Brain Observability — Prime Agent Extension

[Prime Agent](https://prime.cursor.sh) extension for The Second Brain OS. It
observes the Prime agent lifecycle, appends JSONL telemetry, drives the v2
AutoInject retrieval path, and — for orchestrator-model sessions only
(default model substring `gpt-5.6-sol`) — blocks direct execution tools and
injects the Sol contract. Everything else is measurement or advisory-only:

- `tool_call` handlers only read `event.input` — they never modify it.
- The ONLY patches returned are: `{ block: true, reason }` from `tool_call`
  when an orchestrator model calls a blocked tool (`bash`/`edit`/`websearch`;
  `ipython` is NOT blocked — RLM delegation runs through the IPython kernel),
  `{ systemPrompt }` from `before_agent_start` for orchestrator-model
  sessions (the condensed Sol contract), and a low-authority `message`
  (`customType: "brain.autoinject.packet"`, `authority: advisory` inside the
  packet text) from `before_agent_start` when v2 AutoInject is in
  `advisory`/`active` mode. Every other session/event returns undefined.
- Every handler is wrapped in try/catch; storage writes are fire-and-forget
  and never throw into the session. Guard and retrieval failures fail open
  (`extension_error` record, no block, no packet).

## Current deployment status

This section describes the FACTS an operator can verify right now, not a
point-in-time claim that goes stale. Never trust a hardcoded date in this
file over live evidence:

- `brainctl doctor --home <brain-home>` — `identity coherence` and
  `build identity` checks report the exact runtime/state pairing and the
  exact commit/schema/adapter-fingerprint currently in effect.
- `<brain-home>/state/extension-runtime-ready.json` — written once per Prime
  extension lifecycle (see "Runtime and state separation" below); the
  authoritative record of which home/runtime/Brain-version THIS running
  extension instance is frozen to.
- `outputs/reports/v2/burnin/` in this repository — the evidence trail for
  every repair applied since the qualified baseline commit
  `4af64affdf4f1ec07b9483b67f440394d2853b32` (branch `brain/v2-one-shot`).
  `v2.0.0` is not tagged until production burn-in on Prime 0.9.1 and Claude
  Code both pass; see
  `The_Second_Brain_v2_Burnin_Repair_and_Release_Plan.md` for the gate list.

## Legacy recall vs v2 AutoInject vs Retrieval Intelligence 2.0

Three retrieval mechanisms exist in this codebase; only one is the active
production path:

| Mechanism | Status | Trigger | Notes |
|---|---|---|---|
| **Phase 14 recall hook** (`SECOND_BRAIN_RECALL`) | Legacy, default OFF | Env var only | Predates AutoInject; a single `brain memory search` text-format spawn appending a compact Brief. Kept for backward compatibility; NOT the v2 retrieval architecture. Do not confuse "recall default off" with v2 AutoInject being inactive — they are independent switches. |
| **v2 AutoInject** | Active production path | `config/autoinject.toml` `[autoinject] mode` (or `SECOND_BRAIN_AUTOINJECT_MODE` env override); default `shadow` | This extension's `before_agent_start`/`session_start` handlers spawn `second_brain autoinject shadow` (or advisory/active). `shadow` decides and records but never injects; `advisory`/`active` may return the low-authority packet message. See `src/autoinject.ts`. |
| **Retrieval Intelligence 2.0** | Active, invoked BY AutoInject | N/A (Python-internal) | The scoring/ranking engine (`hybrid_retrieval.py`, `semantic.py`) that v2 AutoInject calls on the Python side for every non-shadow-skip decision: relevance, authority, scope, freshness, contradiction, activation need, diversity, MMR selection. Never invoked directly by this extension. |

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

## Environment variables: persistent vs process-local

**Persistent** — set BEFORE starting `prime-agent`; the daemon inherits its
startup environment and passes it to every worker session for the life of
that daemon process. Changing these mid-session never retargets a running
extension instance (see "Runtime and state separation"); only a daemon
restart or `/reload` re-reads them:

- `SECOND_BRAIN_HOME` — Brain state root.
- `SECOND_BRAIN_PYTHON` — explicit Python runtime executable (overrides the
  `<home>/.venv/Scripts/python.exe` compatibility fallback).
- `SECOND_BRAIN_OBSERVABILITY` — kill switch.
- `ORCHESTRATOR_MODELS`, `ORCHESTRATOR_BLOCKED_TOOLS`, `DRIVER_MODELS`,
  `WORKER_MODELS` — role classification tables.

**Process-local / per-invocation** — read live at call time by the specific
bridge that consumes them; safe to vary between sessions without a restart
because nothing caches them at factory startup:

- `SECOND_BRAIN_AUTOINJECT_MODE`, `SECOND_BRAIN_AUTOINJECT_TIMEOUT_MS` — also
  overridable per-Brain via `config/autoinject.toml` (the live flip switch;
  takes effect on the NEXT event, no redeploy).
- `SECOND_BRAIN_PROJECT` — lowest-precedence rung of the canonical project
  resolution ladder (`brainctl project resolve`); explicit/manifest/registry
  rungs win when present.
- `SECOND_BRAIN_RECALL*` — legacy Phase 14 recall gate tuning.
- `SECOND_BRAIN_RTD`, `SECOND_BRAIN_RTD_THRESHOLD` — RTD shadow tuning.
- `SECOND_BRAIN_REREAD_AVOIDANCE` — reread-hint mode.

## Runtime and state separation

`SECOND_BRAIN_HOME` (state) and `SECOND_BRAIN_PYTHON` (runtime) are
independently configurable so changing one can never silently change the
other. Every bridge in this extension resolves the Python executable with
the same precedence: explicit call-site option > `SECOND_BRAIN_PYTHON` >
`<home>/.venv/Scripts/python.exe` compatibility fallback. `brainctl doctor`
fails when an explicit `--home` disagrees with `SECOND_BRAIN_HOME`, or when
the importing Python runtime's package source disagrees with the requested
`SECOND_BRAIN_RUNTIME_ROOT`.

## /reload and frozen-per-lifecycle semantics

Brain home, runtime python, and their identity hash are resolved ONCE when
Prime loads this extension (`loadConfig()` inside the factory closure) and
written to `<home>/state/extension-runtime-ready.json`. An environment
change after that point never silently retargets the running instance —
only `/reload` (or a full Prime restart), which re-runs the factory and
rewrites the status file, picks up a new value. This is deliberate: a
mid-session home swap must never happen invisibly.

## Privacy

Lifecycle telemetry excludes message text, prompts, raw tool outputs and
chain-of-thought. It records:

- counts (messages, turns, tool results, branch entries),
- sizes (`input_bytes`, `output_bytes`, `prompt_chars`),
- flags (`is_error`, `from_extension`),
- tool names and ids,
- the bash command text (`command`), **only** for the `bash` tool, truncated to
  500 chars.

Worker lifecycle receipts are separate from telemetry: schema 22 stores the
bounded canonical result summary and hash in the existing Brain database.
Native OMP custom journal entries retain bounded pending-result data for
recovery; neither journal presence nor a telemetry observation proves acceptance.

## Install

Canonical installer (backups the previous state first):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-prime-extension.ps1
```

It copies `src/*.ts` and `types/*.d.ts` to
`~/.omp/agent/extensions/second-brain/` (OMP's real auto-discovery
directory, live-confirmed against OMP 18.1.10), never edits settings.json,
and is reversible via `scripts\uninstall-prime-extension.ps1`. Restart OMP
(`/reload` works for auto-discovered extensions). Pass `-ExtensionsDir
<path>` to target a different location explicitly (for example a separate
"Prime Agent" binary's own extensions directory) without changing the
default.

`-SourceRoot` selects the checkout independently of `SECOND_BRAIN_HOME`.
Installation manifests cover exactly the flattened top-level `src/*.ts` and
`types/*.d.ts` files. Restore requires an explicit, destination-bound
`-BackupDir`; uninstall without that flag does not select a latest backup.
`-SettingsFile` remains snapshot-only compatibility input: neither script
modifies or restores that configuration.

Worker receipt replay is idempotent, including failed and cancelled outcomes.
Historical terminal tasks without a durable receipt return
`RESULT_NOT_RECORDED`; they are not retroactively credited.

Automatic result capture requires native `async-result` `details.jobs[]`
entries with `jobId`, `type`, `status`, and `agentId`. Correlation uses `jobId`;
the child identity and terminal status come only from structured metadata.
Rendered content is limited to a 2,048-character, non-authoritative batch summary.
No rendered `<task-result>` attributes or live snapshot polling provide authority.

Stock OMP 18.1.10 lacks this metadata: automatic results remain pending and
emit `BRAIN_WORKER_STRUCTURED_ASYNC_UNAVAILABLE` once per extension lifecycle.
Synchronous results and explicit structured `hub` observations retain their
existing settlement path. Patched-host compatibility was verified on both
pinned `f241301c83726afe75a847e919b89977a54dafbe` and current-main base
`5964a0f7649275bcde818f20073193fd032451f2`, using upstream patch
[`874fe1f20b`](https://github.com/joebenberry-afk/oh-my-pi/commit/874fe1f20bc5f906812ff52c0a6a5698a59c191e).
The patch preserves status/identity even after the live job row is evicted.

The candidate remains **HOLD**: no default deployment or provider qualification
was performed. See the
[structured-contract offline evidence](../../outputs/reports/v2/omp-burnin/20260905-host-contract-offline/).

`npm install` inside this directory is for DEVELOPMENT only (tests/lint/type
check; the extension itself has zero runtime dependencies beyond Node
built-ins). For a quick uninstalled test:

```bash
omp -p -e ./src/index.ts "Reply with exactly: ok"
```

## Config gate

| Setting | Effect |
|---|---|
| `SECOND_BRAIN_OBSERVABILITY=off\|0\|false\|no` (case-insensitive) | Disables the extension silently |
| `SECOND_BRAIN_HOME=<dir>` | Brain home (must exist, else silently disabled) |
| `ORCHESTRATOR_MODELS=<a,b>` | Comma-separated model-id substrings identifying the orchestrator role (default `gpt-5.6-sol`; matched case-insensitively on the lowercased model id) |
| `ORCHESTRATOR_BLOCKED_TOOLS=<a,b>` | Comma-separated tool names blocked for orchestrator sessions (default `bash,edit,websearch`; `ipython` deliberately not listed) |
| `DRIVER_MODELS=<a,b>` | Comma-separated model-id substrings identifying the DRIVER role (default `deepseek-v4-pro,gpt-5.6-luna`; matched case-insensitively on the lowercased model id; see "Agent roles" below) |
| `WORKER_MODELS=<a,b>` | Comma-separated model-id substrings identifying the WORKER role (default `deepseek-v4-flash,qwen3.5`; never receive the driver contract) |
| `SECOND_BRAIN_RTD=active` | RTD shadow records intent to substitute (substitution NOT implemented — shadow mode) |
| `SECOND_BRAIN_RTD_THRESHOLD=<n>` | RTD size threshold in JSON chars (default 8000) |
| `SECOND_BRAIN_RECALL=1\|true\|yes` | **Phase 14 recall hook (DEFAULT OFF)**: enables ONE bounded Brain recall per before_agent_start for substantial prompts |
| `SECOND_BRAIN_RECALL_MAX_ROWS=<n>` | Max brief rows (default 3) |
| `SECOND_BRAIN_RECALL_MIN_CHARS=<n>` | Min prompt length to attempt recall (default 40) |
| `SECOND_BRAIN_RECALL_TIMEOUT_MS=<n>` | Recall spawn timeout (default 5000) |
| *(unset)* | `%USERPROFILE%\Documents\The-Second-Brain` |

Telemetry directory: `<brain-home>/telemetry/agent-performance/` (created
once per extension lifecycle — one shared readiness step, not per record).

## Agent roles

The active model is classified on `before_agent_start` into exactly one role
(canonical policy: `brainstem/policies/driver-orchestration.md`; resolution in
`src/driver-orchestrator.ts`):

| Role | Default model substrings | Behavior |
|---|---|---|
| `hard_orchestrator` | `gpt-5.6-sol` (via `ORCHESTRATOR_MODELS`) | Strict Sol contract replaces the system prompt; execution tools blocked (`bash`/`edit`/`websearch`); ipython kept for delegation |
| `driver` | `deepseek-v4-pro`, `gpt-5.6-luna` (via `DRIVER_MODELS`) | Driver-orchestration contract APPENDED to the full current system prompt (deduped by marker; default-off recall brief appends AFTER it in one patch) |
| `worker` | `deepseek-v4-flash`, `qwen3.5` (via `WORKER_MODELS`) | Measurement-only; never receives the driver contract; does not inherit the driver role |
| `normal` | anything else (e.g. `anthropic/claude-sonnet-5`, `openai-codex/gpt-5.6-terra`) | Measurement-only |

Precedence: `hard_orchestrator` > `driver` > `worker` > `normal` (lowercased
substring containment). The driver contract mandates: orchestrate substantive
work by default (never wait for the user to ask for subagents), execute
trivial work directly, delegate the bulk of execution-heavy work, concurrency
default 1 / max 2 / never 3+, prefer the cheapest competent worker, and
workers must never orchestrate (anti-recursion). Each `before_agent_start`
telemetry record carries the resolved `role`; driver sessions also carry
`driver_contract_injected` (see `brainstem/telemetry/SCHEMA.md`).

See "Current deployment status" above for how to verify what is actually
installed and running right now instead of trusting a date in this file.

## Legacy: Phase 14 recall hook (default OFF, superseded by v2 AutoInject)

`SECOND_BRAIN_RECALL` in {1,true,yes} enables one bounded Brain recall per
`before_agent_start` for substantial, non-trivial prompts (default OFF =
zero behavior change, zero spawns). The handler runs
`<brain-home>/.venv/Scripts/python.exe -m second_brain memory search "<prompt>"`
(runtime resolved via the SAME `SECOND_BRAIN_PYTHON` precedence documented
above; cwd = brain home, `SECOND_BRAIN_HOME` set, `PYTHONHOME`/`PYTHONPATH`
removed, hard timeout) and appends a compact **Brain Brief** (<= 3 rows,
<= 1000 words, current/superseded/uncertain labels) to the FULL current
system prompt (`ctx.getSystemPrompt()` — never replaces the base prompt).
Recall never runs for orchestrator-model (Sol) sessions, which get the Sol
contract instead. Every failure is silent (no spawn error, no injection;
`extension_error` record only). Gate: disabled, blank/short (< 40 chars),
< 8 words, greeting, or continuation/CLI-ish starts all skip.

Limitations: `brain memory search` has no `--json` mode, so the CLI text
format is parsed (id/status/grade/title only — summary/project are optional
fields for a future JSON path); `parseRecallRows` already accepts a JSON
array when a `--json` mode lands.
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



