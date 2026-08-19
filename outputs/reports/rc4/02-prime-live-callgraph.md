# Prime Live Call-Graph Audit

Phase R1. Built from direct reading of
[`brainstem/prime-extension/src/index.ts`](../../../brainstem/prime-extension/src/index.ts)
(922 lines) and the ambient API surface in
[`brainstem/prime-extension/types/prime.d.ts`](../../../brainstem/prime-extension/types/prime.d.ts)
(311 lines, "Hand-written to match the installed runtime... verified against
the installed runtime" per its own header). No RC3 report claim is taken on
trust; every row below cites the source line.

## `session_start` (index.ts:327–386)

- **Current behavior:** fires shadow AutoInject (no-op on empty task text),
  resolves agent role, mirrors `session_started` + `host_artifact_ref`
  (transcript, telemetry path) to the ledger, appends a measurement record.
- **Missing:** nothing claimed by the plan for this event beyond measurement.
- **Fail-open path:** whole handler wrapped via `wire()`/`safeHandler()`
  (index.ts:190–223) — any error appends an `extension_error` record and
  returns `undefined`; never throws into the session.

## `before_agent_start` (index.ts:430–553)

- **Current behavior:** this is **not** measurement-only. It genuinely
  patches the system prompt: AutoInject advisory/active message
  (`runAdvisoryAutoInject`), Sol-orchestrator contract injection
  (`SOL_ORCHESTRATOR_CONTRACT`, returned via `{systemPrompt}` when
  `isOrchestratorModel`), driver-role contract append
  (`appendDriverContract`), Lean Code kernel injection
  (`decideLeanRuntime` / `appendLeanKernel`), and a bounded Brain recall
  brief (`recallBrief`) appended after the composed base.
- **Missing:** nothing per plan §7 for this event — this is real live wiring,
  confirmed by source, not an RC3 claim.
- **Fail-open path:** registered directly via `pi.on` (not through `wire`,
  because it needs to `await` and return a patch). Every branch is inside
  `try/catch`; on error, an already-computed `aiMessage` is still returned
  bare in advisory/active mode (index.ts:541–550) so a packet already built
  is never silently dropped, but no new patch is constructed after a
  failure.

## `context` (index.ts:559–561) — **VMem gap confirmed**

- **Current behavior:** `sensors.context(session, event.messages)` —
  measurement only, exactly as RC3-audit finding F3 states. Registered
  through the generic `wire<ContextEvent>()` helper.
- **API capability (prime.d.ts:294–298, :249–251):** the host **does**
  support context replacement — `on("context", handler)` where the handler
  may return `ContextEventResult { messages?: unknown[] }`, applied by the
  runtime (types.ts:925 per the file's own verification comment).
- **Structural blocker, not a host limitation:** `wire()` (index.ts:280–286)
  calls `pi.on(type, safeHandler(...))`, and `safeHandler`'s return type is
  declared `(event, ctx) => void` (index.ts:190–195) — it always returns
  `undefined` to the host, regardless of what `mapper` computes. So even if
  a VMem paging function were written, wiring it through `wire()` as
  `context` currently is would silently discard the patch. VMem context
  integration (plan Phase R3) requires switching `context` to direct
  `pi.on` registration (the same pattern already used for
  `before_agent_start`, `tool_result`, `session_before_compact`) so a
  `{messages}` patch can actually reach the host.
- **Required change:** (1) register `context` directly; (2) implement the
  hot/cold working-set decision against `src/second_brain/vmem.py` (exists,
  unwired — confirmed via `find src -iname "*vmem*"`); (3) return
  `{messages}` only when paging actually changes the set, mirroring the
  `tool_result` RTD pattern's original-content-on-failure discipline.
- **Fail-open path:** none today, because there is no branch that can fail —
  the handler does exactly one thing. Any real implementation must add the
  same try/catch-and-return-`undefined` discipline as `tool_result`
  (index.ts:784–791).

## `tool_call` (index.ts:685–721) — **Action Cache capability ceiling confirmed**

- **Current behavior:** telemetry (`sensors.toolCall`), ledger mirror
  (`tool_requested`), and the Sol minimal-orchestrator policy guard
  (`orchestratorPolicyFor` → `{block: true, reason}` for disallowed
  tools/models). No Action Cache lookup.
- **API capability (prime.d.ts:189–192, :262–265):**
  `ToolCallEventResult = { block?: boolean; reason?: string }` — that is the
  **entire** result shape the host accepts from a `tool_call` handler. There
  is no field to supply a result payload and skip execution.
- **Consequence for R5 (do not overclaim):** a `tool_call` hook **cannot**
  short-circuit execution and return cached content — confirmed from the
  type surface, not inferred. Prime Action Cache **cannot** claim
  host-level execution bypass at this hook. Per the plan's own instruction
  ("do NOT claim Prime Action Cache execution bypass... integrate cache at
  a lower Brain-owned tool wrapper where execution can be safely bypassed"),
  any R5 implementation must sit below Prime — e.g. wrapping the
  deterministic read/scan/search helpers `second_brain` itself exposes,
  not the Prime `tool_call` hook — and must be documented as
  capability-limited at the Prime layer.
- **Fail-open path:** `try/catch` around the whole handler
  (index.ts:685–719); guard failures never block (`extension_error`
  appended, no `{block}` returned).

## `tool_result` (index.ts:741–792)

- **Current behavior:** runs the existing RTD path (`runRtd`) — eligible
  large bash/pytest/git/rg/grep results are preserved byte-exactly via the
  artifact store, verified recoverable, then replaced with a
  `[SECOND_BRAIN_RTD]` block; ineligible/failed-preservation results pass
  through unchanged. This matches F3's claim precisely: "runs existing RTD
  path, not the newly claimed Python Firewall integration" —
  `src/second_brain/firewall.py` exists (confirmed) but nothing in
  `index.ts` imports or calls it.
- **Missing:** whether Observation Firewall should *become* the RTD
  reducer or stay a separate reusable library (plan's own R2 either/or) is
  an open design decision, not evaluated in this pass.
- **Fail-open path:** try/catch returns `undefined` on error
  (index.ts:784–791) — original tool content is never lost.

## `session_before_compact` / `session_compact` (index.ts:835–906)

- **Current behavior:** a real durability barrier —
  `session_before_compact` awaits `runLedgerCheckpoint` and returns
  `{cancel: true}` on checkpoint failure (host throws "Compaction
  cancelled", confirmed against `agent-session.ts:7199` per the code
  comment); `session_compact` rolls the ledger segment over. No VMem
  eviction bookkeeping at this boundary.
- **Missing:** plan R3 implies VMem should treat compaction as a pressure
  signal for eviction; not present.
- **Fail-open path:** `session_before_compact` catch returns
  `{cancel: true}` — "never compact on an unproven barrier"
  (index.ts:880), i.e. it fails *closed* by design (favoring durability
  over availability), which is a deliberate exception to the
  fail-open convention stated elsewhere in the file header.

## Worker spawn lifecycle — **no hook exists**

- **Current behavior:** none. `PrimeEvent` (prime.d.ts:167–181) — the
  complete union of the 11 subscribed event types — contains no
  spawn/subagent/child event of any kind.
- **Consequence for R7:** Prime exposes **no extension hook to intercept
  worker spawning**, confirmed by exhaustive enumeration of the type union,
  not by absence-of-evidence reasoning. Per the plan's own instruction, this
  must be documented as a host limitation; any worker-ceiling enforcement
  has to live elsewhere (`WorkerPlaneManager`/`spawn_worker` currently only
  found in `src/second_brain/repository_intelligence.py` and its test —
  there is no dedicated `worker_plane` module in `src/second_brain/`
  despite RC3's `outputs/reports/rc3/08-worker-plane-live.md` implying one).

## Usage events (`before_provider_request` / `after_provider_response` / `message_end`)

- **Current behavior:** read-only measurement (privacy-scoped: counts/sizes/
  sha256 only, per file header). `message_end` returns `{message:
  event.message}` — the exact same object — which the code comments justify
  as "a provably safe no-op that keeps the original role" (index.ts:606–609).
- **Missing:** nothing claimed for these events beyond measurement.

## `session_shutdown` (index.ts:908–920)

- **Current behavior:** final synchronous telemetry write (`appendFinal`,
  not the async `append` used elsewhere) — because "Prime's daemon tears
  the worker down right after the event, so async writes can lose the race
  with process exit" (index.ts:186–188).
- **Missing:** nothing claimed here.

## Tool Working Set — capability exists, unused

- **API capability (prime.d.ts:306–309):** `ExtensionAPI` declares
  `getActiveTools?()`, `getAllTools?()`, `setActiveTools?(toolNames)`,
  annotated "modeled for Phase J measurement, not consumed today."
- **Current behavior:** `index.ts` never calls any of the three (confirmed:
  no `getActiveTools`/`setActiveTools`/`getAllTools` call site in the file).
  `src/second_brain/tool_working_set.py` and `working_set.py` exist and are
  unwired.
- **Consequence for R6:** unlike Action Cache (§ above) and Worker Plane,
  this is **not** a host limitation — the control surface is present and
  typed. R6 is pure wiring work: compute the minimum deterministic tool set
  from task intent, call `setActiveTools`, verify via `getActiveTools`
  before/after in a real session.

## Summary table

| Feature | Hook exists? | Patch-capable today? | Blocker type |
|---|---|---|---|
| VMem context paging | yes (`context`) | **no** — wired through `wire()`, which always discards the return value | structural (this codebase), not host |
| Action Cache tool bypass | yes (`tool_call`) | **no** — `ToolCallEventResult` has no result field | host (Prime API) |
| Observation Firewall reduction | yes (`tool_result`) | yes, but currently runs RTD, not Firewall | design decision, not blocker |
| Worker Plane spawn gate | **no event exists** | n/a | host (Prime API) |
| Tool Working Set control | yes (`getActiveTools`/`setActiveTools`) | yes, unused | none — just unwired |
