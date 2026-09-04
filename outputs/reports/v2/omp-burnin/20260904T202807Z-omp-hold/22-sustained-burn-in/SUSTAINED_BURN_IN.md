# Phase 22 — Sustained OMP Burn-In

## Candidate

- Run ID: `20260904T202807Z-omp-hold`
- Branch: `brain/v2-omp-qualification`
- SHA: `86585e114115bc43bf932145e716f2ed4d3dd30e`
- OMP: `18.1.10` (`C:\Users\assas\.bun\bin\omp.exe`)
- Extension: `brainstem/prime-extension/src/index.ts`
- State: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot`
- Telemetry source: `telemetry/agent-performance/*.jsonl`

## Coverage measurement

Counts below are from the complete telemetry corpus present at the end of
this run. The corpus contains 83 JSONL files and 82 unique session identities;
duplicate `session_start` records are not counted as additional sessions.
Where a conservative completed-work count is available, it is shown beside the
raw lifecycle count.

| Target | Observed | Result |
|---|---:|---|
| 50+ OMP sessions | 82 unique identities; 72 sessions with provider response `200` | PASS |
| 100+ normal turns | 190 `turn_start`; 180 provider responses | PASS |
| 25+ tool calls | 152 `tool_call`; 150 `tool_result` | PASS |
| 20+ worker launches | 19 `omp_worker_context_handoff` events | HOLD — 1 short |
| 20+ worker completions | 7 `omp_worker_child_result` events: 4 completed, 3 failed | HOLD — 13 short even counting failures |
| 10+ session compactions | 8 `session_before_compact`/`session_compact` pairs | HOLD — 2 short |
| 10+ clean restarts | 85 shutdown records across 76 unique sessions | PASS |
| 3+ interrupted/recovery cases | 3 live cases documented in Phases 9, 16, and 19 | PASS |
| 20+ project switches | 11 project transitions in retrieval telemetry | HOLD — 9 short |
| 2+ conflicting controlled projects | `p10-project-alpha` and `p10-project-bravo`, alternating sentinels | PASS |

The already-qualified phase evidence covers coding/repository work, inspection,
planning, memory-relevant and irrelevant prompts, delegation, compaction,
restart, and project switching. The late burn-in attempt added real OMP worker
dispatch and compact-session pressure, but did not complete enough provider
work to close the remaining count gaps.

## Continuous checks

- No cross-project packet was observed. The complete retrieval sequence records
  11 transitions and the Phase 10 alpha/bravo alternating-sentinel proof remains
  clean.
- AutoInject cache invalidation and duplicate-delivery checks remain covered by
  Phase 9; no stale or foreign packet was served.
- Worker handoff/result telemetry remains bounded and identity-bearing. The
  current failed child results are explicitly `failed`, not fabricated
  completions.
- The Phase 19 synchronous `execFile` rejection defect was repaired at
  `02c9204` and regression-tested. The repaired live path records
  `extension_error` and keeps the OMP session responsive.
- No repeated unexplained Second Brain P2 reliability failure was identified in
  the accumulated burn-in evidence. Provider throttling is classified
  separately below.

## External constraint

The additional worker-burn and compaction OMP invocations reached the Anthropic
provider rate limit at approximately `2026-09-04T19:49Z`. The OMP job output was
HTTP `429`, error type `rate_limit_error`, with
`retry-after-ms: 9017000` (about 2.5 hours). The six child OMP sessions created
by those dispatches have local lifecycle telemetry but no provider response;
they are not counted as successful completed work. No repeated live provider
attempt was made after the authoritative throttle response.

This is an external resource constraint, not a Second Brain bridge failure, but
it prevents honest completion of the remaining count-based burn-in targets.

## Gate 22 result

**HOLD.** Existing live behavior has no unresolved P0/P1 defect in the repaired
candidate, but the plan's sustained count targets are incomplete: worker
launches, worker completions, compactions, and project switches remain below
minimum. The candidate is not eligible for a v2.0.0 tag until those live counts
are completed under an available provider quota.
