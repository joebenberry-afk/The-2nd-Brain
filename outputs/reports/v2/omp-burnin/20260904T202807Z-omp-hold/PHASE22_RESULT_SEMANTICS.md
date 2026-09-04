# Phase 22 Worker-Result Semantics

This note records the gate interpretation required before resuming the OMP
qualification campaign.

## Canonical gate

The canonical OMP production qualification plan defines the Phase 22 target as
`20+ worker completions`. Its worker-result lifecycle contract separately
requires coverage of completed, failed, duplicate, and interrupted workers.
The OMP telemetry schema records each observed child result as one
`omp_worker_child_result` event with bounded correlation fields and a `status`.

## Decision

For this campaign, `worker results: 20` means **20 legitimate terminal child
result events, regardless of whether the terminal status is `completed` or
`failed`**. A legitimate terminal event must be emitted by the real OMP
`tool_result` observation path for a real worker and must retain task, packet,
child-agent, and session correlation. A still-`running` job produces no result
event and does not count. Repeated observation of the same settled job is
one event because the bridge deduplicates task IDs. Cancellation/rejection may
count only when the real OMP result path emits that terminal event; it is never
synthesized.

This interpretation follows the plan's explicit failed-worker handling
requirement, the telemetry event contract, and the worker lifecycle state
machine's terminal-state definition. The existing `7/20` is therefore valid:
4 real `completed` events plus 3 real `failed` events. The remaining deficit is
13 legitimate terminal result events.

## Current execution boundary

The last authoritative provider response was HTTP `429 rate_limit_error` with
`retry-after-ms: 9017000`. At the proceeding-plan checkpoint (`2026-09-04T21:19:58Z`)
the cooldown had not elapsed. No new OMP provider-backed action was started
from this checkpoint, and no result counter was fabricated or backfilled.
