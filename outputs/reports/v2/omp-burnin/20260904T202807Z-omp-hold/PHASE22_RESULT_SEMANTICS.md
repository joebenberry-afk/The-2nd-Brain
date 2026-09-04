# Phase 22 Worker-Gate Semantics

This documentation correction clarifies the two worker gates before
qualification resumes. Historical telemetry and the earlier checkpoint
interpretation are retained below; only the qualification interpretation is
corrected.

## Canonical distinction

The canonical Phase 22 plan requires proof that OMP workers successfully
complete. The separate worker-result lifecycle proof requires completed,
failed, duplicate, and interrupted-worker handling. A failed worker is valid
failure-path evidence, but it is not a successful completion.

## Gate A — terminal-result lifecycle

Target: **20+ legitimate terminal `omp_worker_child_result` events**.

Eligible statuses are `completed`, `failed`, and `cancelled`/`rejected` only
when emitted by the real OMP worker-result lifecycle. Running, stale,
duplicate, synthesized, or manually backfilled records do not count. Repeated
observation of one settled job remains one event because the bridge
deduplicates task IDs.

Current Gate A evidence: **7/20** terminal events — **4 `completed` and
3 `failed`**. The existing `7/20` count is valid for Gate A.

## Gate B — successful worker completions

Target: **20+ real workers with terminal status `completed`**.

Only a real OMP worker result with terminal status `completed` counts. Failed,
cancelled, rejected, running, stale, duplicate, synthesized, and manually
backfilled results do not count toward this gate.

Current Gate B evidence: **4/20** successful completions. The failed workers
remain useful lifecycle evidence but cannot substitute for successful
operation.

## Gate relationship

The gates are cumulative requirements, not alternatives. Gate A proves that
terminal worker outcomes are observed and correlated correctly. Gate B proves
that workers reliably complete. For example, `2 completed + 18 failed` can
never satisfy Gate B.

## Earlier checkpoint interpretation retained

The prior checkpoint used `worker results` as shorthand for legitimate terminal
child-result events, regardless of terminal status. That interpretation remains
the recorded Gate A definition and is not erased. It is superseded only as an
interpretation of the canonical successful-completion gate. This correction is
recorded before qualification resumes.

## Current execution boundary

The last authoritative provider response was HTTP `429 rate_limit_error` with
`retry-after-ms: 9017000`. No new OMP provider-backed action has been started
while the cooldown boundary remains active, and no result counter has been
fabricated or backfilled.
