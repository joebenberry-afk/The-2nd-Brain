# Phase 12 — OMP Worker Result Lifecycle

## Defect found live: worker completion telemetry never fired

Live test 1 (single worker, `/tmp/omp-p11-worker2`) and live test 2 (batch
of two, one deliberately failing, `/tmp/omp-p12-workers`) both spawned real
workers, received correct final results back through the driver's own
conversation, but **zero `omp_worker_child_result`/`worker_completed`
telemetry was ever recorded**, in either test.

### Root cause (confirmed via temporary raw-event diagnostic capture)

This OMP version's `task` tool defaults to **background/async execution**
for the generic `task` agent. The spawning `tool_result` for
`toolName==="task"` always returns `details.results: []` (raw capture:
`{"async":{"state":"running",...},"results":[],"progress":[{...}]}`); the
ONLY place the marker-embedded task text (`[SECOND_BRAIN_WORKER_TASK
task_id=... packet_sha256=...]`) appears at spawn time is `details.progress[]`.
The actual settlement is delivered later via a **separate `hub` tool call**
(`op:"wait"`/`"jobs"`), whose `details.jobs[]` entries have the shape
`{ id, type:"task", status:"running"|"completed"|"failed", resultText? |
errorText? }` (both literal status values live-confirmed) — carrying only
the OMP-assigned agent id, never the Second Brain packet identity.
`recordWorkerChildResults` (`brainstem/prime-extension/src/index.ts`)
only ever read `details.results` and only reacted to `toolName==="task"`,
so it structurally could never observe an async completion.

### Fix

`src/index.ts`:
- `recordWorkerChildResults` now ALSO scans `details.progress[]` at spawn
  time and records `agentId -> {taskId, packetSha256, parentSessionId,
  agent}` into a new `pendingWorkerJobs` map, regardless of whether
  `details.results` is populated.
- New `recordAsyncWorkerCompletions`, wired into the same `tool_result`
  handler for `toolName==="hub"`: for each settled (`status !== "running"`)
  `type:"task"` job, looks up `pendingWorkerJobs`, and — if found — emits the
  identical `omp_worker_child_result`/`worker_completed`/`workerResultRunner`
  triple that the synchronous path already emitted, via a new shared
  `emitWorkerCompletion` helper.
- `reportedWorkerTaskIds: Set<string>` deduplicates: a settled job observed
  by a repeated `hub jobs`/`wait` poll is reported exactly once.

## Regression coverage

`tests/wiring.test.ts` — new describe block `"OMP async worker result
correlation (real factory, [worker_result_lifecycle])"`, 4 tests, all
exercising the REAL factory (not the parse-only unit level):
1. Completed async job correlates correctly (`task_id`, `packet_sha256`,
   `child_omp_agent_id`, `status:"completed"`; `workerResultRunner` called
   once with matching fields).
2. Failed async job records `status:"failed"` (not silently "completed").
3. Three repeated `hub` polls of the same settled job produce exactly ONE
   `omp_worker_child_result` record and exactly one `workerResultRunner`
   call (duplicate-completion handling).
4. A still-`"running"` job produces zero completion telemetry and zero
   `workerResultRunner` calls (no premature/fabricated completion).

All 4 pass; full suite after the fix: 641 passed / 18 failed (same
pre-existing baseline failures as before this change, +4 new passing
tests) — confirmed via `vitest run`, `tsc --noEmit` (clean), `eslint`
(same pre-existing 9 errors).

## Live re-verification after the fix

| Scenario | Session | Result |
|---|---|---|
| Single worker, completed | `/tmp/omp-p12-fix1` | `omp_worker_child_result` recorded: `status:"completed"`, correct `task_id`/`packet_sha256`/`child_omp_agent_id:"UnitedPuma"` |
| Single worker, deliberately failed, driver explicitly waits | `/tmp/omp-p12-fix3` | `omp_worker_child_result` recorded: `status:"failed"`, correct identity |
| Two workers spawned in one batch, driver waits then polls `hub jobs` twice more | `/tmp/omp-p12-fix4` | Exactly 2 `omp_worker_child_result` records (one per worker, correctly distinct `task_id`s/`packet_sha256`s), no duplicates despite the extra polls |
| Single worker, driver does NOT wait/poll before the process exits | `/tmp/omp-p12-fix2` | No completion telemetry (see limitation below) — correctly does not fabricate one |

## Residual, inherent limitation (not a defect)

If the driver session never polls (`hub jobs`/`wait`) before its own OMP
process exits, Second Brain has no event through which to observe the
worker's later settlement — there is no OMP-native hook for "a background
job settled after the parent process already exited." This is a structural
property of extension-based observation of an out-of-process async job
manager, not something this fix (or any Second Brain code) can close.
Every realistic use case where the driver actually depends on the worker's
result (the point of spawning one) requires the driver to check on it before
finishing, which is exactly the case this fix covers.

## Plan checklist

1. **Spawn at least two workers** — done (`/tmp/omp-p12-workers`, `/tmp/omp-p12-fix4`).
2. **Complete in different order if possible** — OMP settles jobs independently; both fix4 workers were observed completing at different poll timestamps (`QuietReindeer` then `OrganisationalEel`), captured correctly regardless of order.
3. **Task/session/project correlation** — proven: each worker's `task_id`/`packet_sha256` is distinct and correctly attributed to the spawning `parent_session_id`.
4. **Duplicate completion handling** — proven via regression test 3 and the live `fix4` extra-polls run.
5. **Failed worker handling** — proven (`fix3`, regression test 2): `status:"failed"`, not silently "completed".
6. **Interrupted worker handling** — the `aborted`/`abortReason` sync-path branch (pre-existing, unchanged) still maps to `"cancelled"`; the async `hub`-job path's 3-value status enum (`running`/`completed`/`failed`) has no separate "cancelled" state at the job level, so an aborted async worker settles as `"failed"` — acceptable (never silently "completed"), documented here rather than invented as a 4th enum value not evidenced in the live job shape.
7. **Persistence destination** — per code (unchanged by this fix, only now actually reached): `getStore` local telemetry (JSONL), `mirror(..., "worker_completed", ...)` ledger record, and `workerResultRunner` -> Python `worker_protocol.record_worker_event` (best-effort, exception-swallowed so a Brain-side recording failure never blocks the session). No candidate-memory or active-state write is intended by the current code for a bare worker completion — not invented here.

## Gate 12

**PASS (after fix).** No worker result is attributed to the wrong
task/session/project in any of the 4 live-re-verified scenarios or the 4
regression tests; the defect that made this gate previously unverifiable
(silence, not misattribution) is fixed, tested, and does not regress the
adjacent RTD/context-paging/visibility wiring tests that also fire through
the same `tool_result` handler.
