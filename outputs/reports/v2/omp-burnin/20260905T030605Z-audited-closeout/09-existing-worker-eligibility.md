# Existing eight-worker eligibility

## Result

**0 eligible natural successful outcomes; 20 remain.** This is not a campaign reset based on source changes. The preserved prompt explicitly required each worker to emit only `worker-N-ok`, with no tool calls. These are diagnostic pings, excluded by this closeout's meaningful-natural-work requirement.

## Preserved evidence

Source report: `../20260904T202807Z-omp-hold/final-p1-repair/10-live-8worker-autodelivery-proof.md`.
Prompt: `../20260904T202807Z-omp-hold/final-p1-repair/live-8worker-prompt-v2.txt:1`.
Parent session: `2026-09-05T02-16-14-068Z_01a06f5a-25f4-762b-b74e-1464fa61981f`.
Raw telemetry: `telemetry/agent-performance/<parent-session>.jsonl:343-353`.
Read-only database/ledger cross-check: `artifacts/eight-worker-audit.json`.

| Jobs | Observed terminal status | Existing durable evidence | Natural success credit |
|---|---|---|---:|
| RealCaterpillar, OutstandingLocust, ClearWolverine, SoundSmelt, RulingOx, ControversialWorm | completed | Each has matching COMPLETED worker-task state, packet hash, owning parent, and one legacy worker_completed result-hash receipt | 0 — fixed-text diagnostic tasks |
| RisingFlea, GeographicalQuail | failed | FAILED worker-task state and matching packet/parent; no canonical result-hash receipt found | 0 — failed, also fixed-text diagnostic tasks |

The **8 observations = 6 completed + 2 failed** remain useful historical auto-delivery/status evidence. They are not eight successful outcomes. The six legacy completed receipts are retained as real evidence; absence of the new schema-22 receipt table does not erase them. The two failed jobs are not relabeled successful because their response text happened to look correct.

## Applicability

The run used DeepSeek through profile `p1-live-proof2` with an explicit extension path, not default discovery. Preserve that historical evidence without making new DeepSeek calls. It does not prove the repaired candidate's default loading, named-agent option preservation, new dispatch identity, atomic receipts, current governor ancestry, or current paging behavior.

The prior shared-daemon/global-budget explanation is superseded by the exact contribution audit in `04-governor-scope-reproduction.md`: the queried totals came from their own cache-heavy driver sessions; descendants contributed zero. No history was deleted or backfilled, no cap was raised, and no stale WORKING row was promoted to a terminal result.

## Deterministic count rule

For each distinct real host dispatch, require verified candidate/config/provider applicability, an actual host launch, an observed native terminal result, a matching authoritative accepted completed receipt, and an independently checked meaningful task outcome. Exclude prepared-only capsules, failed/cancelled tasks, pings, duplicate deliveries, stale tasks, and unknown-build records.

`remaining = 20 - eligible_existing_successes = 20 - 0 = 20`.
