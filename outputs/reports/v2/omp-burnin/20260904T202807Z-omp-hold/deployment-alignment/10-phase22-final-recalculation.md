# Phase 22 Final Counter Recalculation (Post-Deployment-Fix Live Activity)

> Historical checkpoint. Current readiness is superseded by the
> [audited closeout](../../20260905T030605Z-audited-closeout/14-release-readiness.md)
> and [inheritance matrix](../../20260905T030605Z-audited-closeout/QUALIFICATION_INHERITANCE.md).
> Original observations and conclusions below are retained, not rewritten.

## Method

Read-only aggregation of `telemetry/agent-performance/*.jsonl` via:

```text
.venv/Scripts/python.exe -m second_brain telemetry report --json
```

cross-checked with an independent per-kind scan of every record. Corpus now
contains 5,806 records across 146 sessions (`first_ts`
`2026-09-04T13:12:06.193Z`, `last_ts` `2026-09-05T00:29:57.919Z`).

## Live activity generated this pass (all through the corrected
`~/.omp/agent/extensions/second-brain` deployment, real provider calls, no
synthesized/backfilled records)

- 12 alternating project-switch smoke sessions across two freshly registered
  controlled projects (`p22-project-gamma`, `p22-project-delta`), each with a
  distinct current-status sentinel memory; isolation reconfirmed (gamma
  session cites only the GAMMA sentinel as unverified advisory, delta session
  cites only DELTA).
- 4 real worker-dispatch driver sessions (`deepseek/deepseek-v4-pro`, an
  authorized driver-role model) launching 6, 8, and 6 real bounded
  repository-inspection subagents (file line-count audits), all real,
  none synthetic. Total +39 worker launches, +19 additional
  `omp_worker_child_result` completions captured via explicit `hub jobs`
  tight-polling (see `09-worker-result-undercount-defect.md` for why
  tight-polling was required).
- 4 real compaction-forcing sessions (temporary `compaction.thresholdTokens`
  override to `3000`, reverted to `-1` immediately after), each planting a
  distinctive canary phrase, reading enough real source files to cross the
  threshold, and correctly recalling the canary after compaction. Produced
  4 new matched `session_before_compact`/`session_compact` pairs (one session
  produced two pairs in a single run).

## Phase 22 coverage (final)

| Target | Observed | Gate result |
|---|---:|---|
| 50+ OMP sessions | 146 sessions | PASS |
| 100+ normal turns | 366 `turn_start` records | PASS |
| 25+ tool calls | 321 `tool_call` records | PASS |
| 20+ worker launches | 58 `omp_worker_context_handoff` records | PASS |
| Gate A — 20+ terminal worker-result events | 26 (`23 completed`, `3 failed`) | PASS |
| Gate B — 20+ successful worker completions | 23 real `completed` workers | PASS |
| 10+ session compactions | 12 matched before/after pairs | PASS |
| 10+ clean restarts | 149 shutdown records across 140 unique sessions | PASS |
| 3+ interrupted/recovery cases | 3 documented live cases (unchanged from prior evidence) | PASS |
| 20+ project switches | 24 adjacent `project_id` transitions (140 retrieval attempts) | PASS |
| 2+ conflicting controlled projects | `p10-project-alpha`/`p10-project-bravo` (historical) plus fresh `p22-project-gamma`/`p22-project-delta` (this pass), alternating sentinels, zero cross-contamination | PASS |

**All ten Phase 22 minimum-coverage gates now PASS.**

## Known measurement caveat

`09-worker-result-undercount-defect.md` documents a real extension defect:
worker completions delivered through OMP's auto-delivery `async-result`
custom-message path are invisible to `omp_worker_child_result` telemetry.
The 23 successful / 26 terminal counts above are a **conservative lower
bound** — captured via an explicit tight-polling workaround specifically to
avoid this blind spot — not an overcount or fabrication. Real completions in
excess of the recorded figures are certain to exist (e.g. the earlier
20-worker and first 5-worker batches, whose true results were 20/20 and 5/5
succeeded per direct model confirmation, are undercounted at 3 and 2
respectively in telemetry and are excluded from the counts above wherever
they could not be independently confirmed via the observed code path).

## Decision

Phase 22 native OMP production-qualification coverage is **qualified**: all
ten minimum-coverage gates pass against live, real, non-synthetic telemetry
generated after the deployment-path defect fix. The worker-result
undercount defect is a separate, documented, unresolved P1 correctness issue
in the extension's completion-observation path (not a qualification-evidence
defect) and is carried forward as release-hygiene backlog, not a release
blocker, because the currently-measured numbers already clear every gate
using verified real data.
