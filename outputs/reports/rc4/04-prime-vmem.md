# Prime VMem Integration

Phase R3. Fixes the structural plumbing bug found in R1
([02-prime-live-callgraph.md](02-prime-live-callgraph.md)) and wires VMem's
own documented compaction-boundary integration point. Does **not** yet page
cold context into a live `context`-event message replacement — that remains
capability-unlocked but content-undecided, for a reason explained below, not
fabricated around.

## 1. The structural fix

`brainstem/prime-extension/src/index.ts`'s `context` handler was registered
through the generic `wire()`/`safeHandler()` combinator, whose return type
is declared `(event, ctx) => void` (index.ts, `safeHandler`) — it **always**
returns `undefined` to Prime regardless of what the mapper computes. The
host's `ContextEventResult { messages?: unknown[] }` (prime.d.ts:249-251)
would have been silently discarded even after a correct VMem paging
function was written.

Fixed: `context` is now registered directly via `pi.on("context", ...)`
(the same pattern already used by `before_agent_start`, `tool_result`, and
`session_before_compact`), with its own try/catch and a real return value
distinct from the telemetry write. Verified in
`tests/ledger-mirror.test.ts` ("context event: direct registration") that
the handler completes synchronously and its return value reaches the
caller directly — not silently dropped by a `void`-typed wrapper.

## 2. Why no `{messages}` patch is generated yet

Per the plan's own instruction, faking a message-shape-aware paging
decision is exactly the kind of thing to stop and document rather than
invent. Two independent, source-grounded reasons:

1. **Message shape is genuinely unknown.** `ContextEvent.messages` is typed
   `unknown[]` in `prime.d.ts` ("Fields we ignore are typed `unknown`;
   never rely on their shape"), and `sensors.context()` only ever computes
   `messages.length` — no code anywhere in this repository has ever
   introspected an individual Prime message's fields. Building a
   role/content-aware eviction-and-replacement function against a guessed
   shape risks corrupting every live session's context; this can only be
   done correctly after a real Prime session captures the actual shape
   (deferred to the R9-era live pilot).
2. **VMem has nothing to page yet.** `VMemStore.store_object()` — the only
   way a session object enters VMem — is called from exactly one place in
   the whole codebase: `src/second_brain/cli.py`'s `vmem store` subcommand.
   Nothing in Prime (or anywhere else) writes turn content into VMem
   automatically. Even with a correct message-replacement mechanism, there
   would be no real session objects to page for an actual Prime session
   today.

## 3. What is genuinely wired (bookkeeping, not context mutation)

VMem's own docstring identifies its natural integration point: "§6.7
Compaction barrier interaction." This pass wires exactly that — real
subprocess calls at the two hooks that already safely mutate/observe
compaction, using the identical `execFile`-based CLI-bridge pattern already
proven live for the ledger checkpoint (`ledger-mirror.ts`,
`runLedgerCheckpoint`/`runLedgerSegmentRollover`):

- **New:** `brainstem/prime-extension/src/vmem.ts` —
  `runVmemCompactPrep()` (`second_brain vmem compact-prep <session>
  --json`) and `runVmemHotContext()` (`second_brain vmem hot-context
  <session> --budget <n> --json`). Fail-open: missing venv, spawn error, or
  unparsable stdout all resolve `{ok: false, error}`, never throw.
- **`session_before_compact`** (`index.ts`): after the ledger checkpoint
  durability barrier succeeds, calls `runVmemCompactPrep()` when `[vmem]
  enabled=true`. This marks unpinned resident VMem objects `EVICTED` in
  VMem's own SQLite store. **Advisory only** — a VMem failure never
  cancels compaction; only the ledger checkpoint may return
  `{cancel: true}` (verified by test: vmem `compact-prep` throws, handler
  still returns `undefined`).
- **`session_compact`** (`index.ts`): fire-and-forget call to
  `runVmemHotContext()` when enabled, recording `resident_count` /
  `evicted_count` / `resident_tokens` telemetry — the measurable
  post-compaction working-set state, without touching model-visible
  context.
- **Config:** new `[vmem]` section in `config/context.toml` (and the
  packaged default template), `enabled = false` / `budget_tokens = 1500` —
  safe-by-default, same live-flip-without-redeploy pattern as `[rtd]`.
  Parser: `config.ts` `vmemConfigFromContextToml()`/`loadVmemConfig()`,
  mirroring `rtdConfigFromContextToml()` exactly.
- **Telemetry:** two new additive record kinds, `vmem_compact_prep` and
  `vmem_hot_context` (`sensors.ts`), documented in
  `brainstem/telemetry/SCHEMA.md`.

## 4. Verification (this pass — component-level, not a live Prime session)

```
cd brainstem/prime-extension
npx tsc --noEmit   → clean
npx eslint .       → clean
npx vitest run     → 16 files, 395 passed (was 378; +17 new)
```

New tests: `tests/vmem.test.ts` (7 — spawn contract, arg shape, fail-open on
missing venv/spawn error/unparsable JSON for both `compact-prep` and
`hot-context`), `tests/config.test.ts` (+6 — `[vmem]` TOML parsing and
`loadVmemConfig` file read), `tests/ledger-mirror.test.ts` (+4 — `[vmem]`
disabled by default means zero vmem calls; enabled=true triggers
`compact-prep`/`hot-context` with correct args; a failing `compact-prep`
never cancels compaction; `context` handler returns synchronously via
direct registration).

## 5. What R3 required that remains open

The plan's required live-proof scenario (info A goes cold → compaction →
A evicted → later task needs A → JIT fault-in restores A → task succeeds →
no full transcript replay) needs: (a) something populating VMem objects
from real turn content, (b) a message-shape-aware `context` patch. Neither
exists yet, for the reasons in §2. This is recorded as capability-unlocked,
content-undecided — not a host limitation (unlike Action Cache in R5) and
not fabricated around.
