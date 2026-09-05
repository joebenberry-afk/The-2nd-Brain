# P1 #1 — Worker Auto-Delivery Repair

## Files changed

- `brainstem/prime-extension/src/index.ts`
- `brainstem/prime-extension/types/prime.d.ts`

## Design (matches the requested architecture exactly)

```text
existing worker spawn
    ↓
pendingWorkerJobs
    ↓
either:
    A. hub tool_result           (recordAsyncWorkerCompletions)
    OR
    B. message_end custom async-result (recordAsyncResultDeliveries, NEW)
    ↓
takePendingWorkerJob (shared, atomic get+delete)
    ↓
emitWorkerCompletion (shared, unchanged)
    ↓
telemetry + durable Brain worker-result lifecycle (unchanged)
```

No second, independent worker-result architecture was created.

## Changes

1. **`MessageEndMessage` type** (`types/prime.d.ts`): added explicit
   `customType?: string` and `content?: unknown` fields (previously only
   reachable via the index-signature fallback to `unknown`), documented
   against the live-confirmed auto-delivery shape.

2. **`takePendingWorkerJob(agentId)`** (new shared helper, placed directly
   after the `pendingWorkerJobs` map declaration): atomically reads and
   removes one correlation record. Both `recordAsyncWorkerCompletions` (hub
   path) and the new `recordAsyncResultDeliveries` (auto-delivery path) use
   it, so whichever observer sees a settled job first consumes the
   correlation entry; the other observer's lookup then naturally misses and
   no-ops. `emitWorkerCompletion`'s existing `reportedWorkerTaskIds` set is
   the second, independent dedupe guard by `task_id`.

3. **`TASK_RESULT_BLOCK_RE`** (new constant, next to `WORKER_TASK_MARKER_RE`):
   `/<task-result\s+id="([^"]*)"[^>]*\sstatus="([^"]*)"[^>]*>[\s\S]*?<\/task-result>/g`
   — matches the live-observed `<task-result id="…" status="…">…</task-result>`
   block shape, capturing the OMP agent id and terminal status; the full
   match is reused verbatim as the worker-result summary text (parity with
   the hub path's `job.resultText`).

4. **`recordAsyncResultDeliveries(message, ctx)`** (new function, placed
   directly after `recordAsyncWorkerCompletions`): ignores anything that is
   not `role === "custom"` with `customType === "async-result"`; ignores
   non-string `content`; extracts every `<task-result>` block via
   `TASK_RESULT_BLOCK_RE`; for each, looks up `takePendingWorkerJob(agentId)`
   — unknown/untracked ids are silently ignored (never fabricated); maps
   `status !== "completed"` to `"failed"` (parity with the existing hub-path
   mapping); calls the existing `emitWorkerCompletion` with the same field
   shape as the hub path (`task_id`, `packet_sha256`, `child_omp_agent_id`,
   `child_omp_session_file: null`, `worker_agent`, `worker_model: null` —
   the auto-delivery text carries no resolved-model attribute — `status`).

5. **`recordAsyncWorkerCompletions`** (hub path): refactored its inline
   `pendingWorkerJobs.get`/`.delete` pair to call the new shared
   `takePendingWorkerJob` helper. Behavior is unchanged (verified by the
   pre-existing hub-path tests, still passing unmodified).

6. **`message_end` handler**: after the existing `assistant_usage` capture
   logic, added a fire-and-forget call
   `void recordAsyncResultDeliveries(message, ctx).catch(...)` (errors routed
   to `extension_error` telemetry, matching the handler's existing fail-open
   pattern). The handler's declared return type
   (`MessageEndEventResult | undefined`, no `Promise` union) is unchanged —
   `return { message: event.message };` still executes synchronously and
   unconditionally, exactly preserving the documented contract that the
   runtime replaces the finalized message with the same object
   (role-preserving no-op for this concern).

## Fail-open guarantees preserved

- Non-custom or non-`async-result` messages: no-op (checked first, cheapest
  branch).
- Non-string `content`: no-op.
- No `<task-result>` blocks found: no-op, no throw.
- Unknown/untracked agent id: no-op, no fabricated result.
- Any thrown error inside the async correlation chain: caught, routed to
  `extension_error`, never surfaces to the `message_end` handler's
  synchronous return path.

## Non-goals honored

- No second, competing worker-result architecture.
- No unbounded new "seen" set — reuses the existing bounded
  `pendingWorkerJobs` map and `reportedWorkerTaskIds` set exactly as before.
- No behavior change to the hub-path tests (all pre-existing hub-path tests
  pass unmodified, see `03-worker-regression-results.md`).
