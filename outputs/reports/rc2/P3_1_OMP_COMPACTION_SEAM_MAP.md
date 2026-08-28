# P3.1 OMP Primary-Session Compaction Seam Map

**Verdict:** `P3.1_COMPACTION_SEAM_FOUND`

**Scope:** Read-only investigation of the installed OMP v18.0.4 primary-session
`/compact` lifecycle. No Active State Capsule semantics, `working_set.py`, VMem,
JIT, AutoInject, frozen P3.1 contract, or production implementation was changed.
P3.2 was not started.

## Executive finding

OMP exposes a real, supported pre-context-replacement extension event:

```text
session_before_compact
```

The smallest supported wiring task is **not** a capsule implementation change.
It is to load the existing Second Brain extension into the primary OMP process
through an OMP-supported extension path:

```text
--extension brainstem/prime-extension/src/index.ts
```

or persistent OMP settings:

```text
<project>/.omp/settings.json       { "extensions": ["..."] }
<user>/.omp/agent/settings.json    { "extensions": ["..."] }
```

The current primary OMP process was launched as `omp.exe` with no `--extension`
argument. Neither persistent settings path exists, and `omp plugin list` reports
no installed plugins. This explains a successful host `/compact` with no
Second Brain compaction telemetry: the host compacted, but the Second Brain
extension was not bound to that primary session's extension runner.

## Exact lifecycle path

```text
interactive `/compact`
  -> builtin slash-command registry
  -> TUI command adapter
  -> CommandController.handleCompactCommand()
  -> CommandController.executeCompaction()
  -> AgentSession.compact()
  -> SessionMaintenance.compact()
  -> prepareCompaction()
  -> ExtensionRunner.emit(session_before_compact)
  -> summarize/compact through selected method
  -> appendCompaction()
  -> buildDisplaySessionContext()
  -> agent.replaceMessages(sessionContext.messages)
  -> rebase/reset provider and runtime state
  -> ExtensionRunner.emit(session_compact)
```

### 1. Interactive command handling

`src/slash-commands/builtin-lifecycle.ts:130-195` registers `/compact`.
The interactive `handleTui` path clears the editor and calls
`runtime.ctx.handleCompactCommand(parsed.instructions, parsed.mode)` at
`:186-194`.

`src/modes/controllers/command-controller.ts:1268-1291` performs the TUI
precondition check, then calls `executeCompaction()`.
`executeCompaction()` calls `ctx.session.compact()` at `:1323-1361` and rebuilds
the visible transcript after completion at `:1362-1374`.

### 2. Actual context replacement

`src/session/session-maintenance.ts:704-805` implements manual compaction:
abort/disconnect active generation, resolve the method, obtain the current
session branch, and prepare the messages to summarize.

`src/session/session-maintenance.ts:1029-1052` commits the result.
The shared commit sequence at `:1432-1500`:

1. appends the compaction entry (`:1452-1465`);
2. rebuilds display context (`:1466-1468`);
3. replaces live agent messages (`:1468`);
4. rebases/reset plan, advisor, todo, and provider state (`:1469-1480`);
5. emits `session_compact` (`:1481-1499`).

Therefore `session_compact` is post-replacement. It cannot be the only seam for
pre-compaction capsule durability.

## Lifecycle surfaces available immediately around compaction

### `session_before_compact` — supported pre-compaction host extension event

The installed OMP contract defines `SessionBeforeCompactEvent` in
`src/extensibility/shared-events.ts:63-74`: it carries compaction preparation,
branch entries, optional custom instructions, and an abort signal. The return
shape can cancel or supply a compaction result (`:375-381`).

The host emits it in `session-maintenance.ts:820-837`, after preparation and
before compaction summarization. This is the exact pre-context-replacement
seam. It is awaited, so an extension can persist bounded state before OMP
continues.

Conclusion: this is a **real OMP host event**, not an assumption and not merely
an internal Second Brain event.

### `session.compacting` — internal/customization event before summarization

The installed OMP contract defines `SessionCompactingEvent` in
`src/extensibility/shared-events.ts:76-81`. OMP emits it at
`session-maintenance.ts:2242-2253` to customize summarizer context/prompt and
pass preserve data. It is usable for summary customization, but it is not the
smallest durability seam: `session_before_compact` fires earlier and is already
intended for cancellation/checkpoint work.

The current Second Brain extension does not register `session.compacting`.

### `session_compact` — supported post-compaction host extension event

OMP defines the event at `shared-events.ts:83-89` and emits it only after the
new compaction entry is appended, live messages are replaced, and runtime state
is rebased (`session-maintenance.ts:1432-1499`).

The Second Brain extension registers this callback at
`brainstem/prime-extension/src/index.ts:1515-1562` for post-compact segment
rollover and optional VMem rendering.

### Auto-compaction events — separate automatic path

`auto_compaction_start` and `auto_compaction_end` are AgentSession lifecycle
events, defined in `session/agent-session-events.ts:19-32` and emitted by the
automatic maintenance branch at `session-maintenance.ts:2930-2952` and
`:2996-3121`. They describe automatic threshold/overflow maintenance; manual
interactive `/compact` does not enter this auto-only start/end pair.

Manual and automatic compaction share the same commit/context-replacement
sequence, including `session_before_compact` and `session_compact` where
handlers exist.

## Second Brain extension registration status

The existing extension already contains the correct callback wiring:

- `brainstem/prime-extension/src/index.ts:1423-1513`
  registers `pi.on("session_before_compact", async ...)`.
- It resolves the host session identity, mirrors `compaction_started`, writes
  `sensors.sessionBeforeCompact`, persists the existing Active State Capsule
  with `verification.pre_compaction = persisted`, checkpoints the ledger, and
  returns `{ cancel: true }` on a failed durability barrier.
- `brainstem/prime-extension/src/index.ts:1515-1562`
  registers `session_compact` for post-commit rollover/rendering.

No callback implementation is missing for the supported seam.

## Why the actual primary session emitted no Second Brain evidence

The actual interactive OMP session is persisted at:

```text
C:/Users/assas/.omp/agent/sessions/-Documents-The-Second-Brain/
2026-08-24T04-23-53-608Z_01a03202-b608-733b-b815-61b43631b201.jsonl
```

Its session header identifies OMP session UUID
`01a03202-b608-733b-b815-61b43631b201` and the project cwd at line 2.
The live OMP process command line is only:

```text
"C:\Users\assas\.bun\bin\omp.exe"
```

There is no `--extension` argument. The supported discovery implementation
confirms that configured extension roots come from CLI `--extension`/`-e`,
project `.omp/settings.json`, user `~/.omp/agent/settings.json`, or installed
plugins (`discovery/omp-extension-roots.ts:4-13, 168-226`). The project and user
settings files are absent, and `omp plugin list` reports no plugins.

The Second Brain telemetry directory has no file named for the actual primary
session. By contrast, prior probe commands explicitly launched OMP with
`--extension brainstem/prime-extension/src/index.ts` and produced the separate
`2026-08-24T05-22-28-604Z...` and `2026-08-24T05-31-42-023Z...` telemetry files.
Those are child/probe identities, not the primary session identity.

This is an extension-loading gap, not a different host compaction event name.

## Identity and main/worker differences

Second Brain's resolver uses `ctx.sessionManager.getSessionFile()` and takes the
session-file stem (`brainstem/prime-extension/src/index.ts:176-194`). For a
persisted OMP session, this would correlate the full filename stem, including
the timestamp prefix, to the Brain host-session identity.

OMP creates workers separately in `task/executor.ts`:

- a worker uses its own `SessionManager.open(sessionFile)` or
  `SessionManager.inMemory()` (`:3006-3012`);
- it receives a separate `agentId`, session manager, and telemetry conversation
  identity (`:3055-3076`);
- its own `AgentSession` is created at `:3175-3188`;
- extension source paths are forwarded and rebound per worker at
  `:3124-3126`, `:3204-3216`.

Thus main and spawned agents do **not** use different compaction algorithms.
They use the same OMP maintenance surface, but they are distinct session
contexts with distinct persistence/identity lifecycles. Isolated or restricted
workers can receive no extension paths by policy, and in-memory workers have no
persisted session file to correlate.

## Smallest supported wiring task

1. Make the existing `brainstem/prime-extension/src/index.ts` load in the
   primary OMP process using `--extension/-e` or an OMP `extensions` setting.
2. Do not change capsule schema, working-set behavior, VMem, JIT, AutoInject, or
   the P3.1 contract.
3. On the next real primary `/compact`, the existing handler will run at
   `session_before_compact`, persist the current capsule, then allow OMP to
   replace context; the existing `session_compact` handler will observe the
   post-commit boundary.

No new hook, event simulation, unit-test substitution, or parallel state system
is required.

## Qualification boundary

```text
P3.1_COMPACTION_SEAM_FOUND
```

The seam is statically and source-verified. A fresh real primary-session proof
still requires launching the primary with the existing extension loaded and
observing `session_before_compact` plus the resulting capsule/ledger/telemetry
correlation. This report does not claim that missing live proof.
