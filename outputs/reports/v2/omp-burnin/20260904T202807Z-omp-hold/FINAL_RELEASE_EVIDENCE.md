# Final OMP Qualification Evidence

Generated at `2026-09-04T21:43:41Z` after the proceeding checkpoint and
release-hygiene cleanup. A subsequent documentation-only correction clarifies
the separate terminal-result and successful-completion gates before
qualification resumes.

## Candidate identity

- Branch: `brain/v2-omp-qualification`
- Final candidate SHA: `0ec276e15f109a146199cd8b48d1e3d68cedfb54`
- Starting synchronized SHA: `b7d893bf149be77f7c2663cab17f9aa48e598dd5`
- Runtime qualification ancestor: `86585e114115bc43bf932145e716f2ed4d3dd30e`
- OMP: `18.1.10` (`C:\Users\assas\.bun\bin\omp.exe`)
- Brain version: `2.0.0-rc.1`
- Database schema: `21`
- Adapter build fingerprint: `56b61076903f681215426ae38d6ff47225739283bff731d85db1c71e25d81f68`
- Candidate worktree at this SHA: clean

The runtime/extension source is unchanged from the authorized qualification
ancestor. The candidate snapshot SHA contains only proceeding evidence and the
package-lock root metadata cleanup. The subsequent gate-semantics correction
changes documentation only.

## Phase 22 counts

| Gate | Observed | Result |
|---|---:|---|
| OMP sessions | 82 | PASS |
| Normal turns | 190 `turn_start` records | PASS |
| Tool calls | 152 | PASS |
| Worker launches | 19/20 | HOLD — 1 short |
| Gate A — terminal worker results | 7/20: 4 `completed`, 3 `failed` | HOLD — 13 short |
| Gate B — successful worker completions | 4/20 real workers with status `completed` | HOLD — 16 short |
| Session compactions | 8/10 matched pairs | HOLD — 2 short |
| Clean restarts | 85 shutdown records across 76 sessions | PASS |
| Interrupted/recovery cases | 3 | PASS |
| Project switches | 11/20 | HOLD — 9 short |
| Conflicting controlled projects | 2 alternating alpha/bravo projects | PASS |

Gate A counts legitimate terminal lifecycle events: legitimate `completed`,
`failed`, and other real eligible terminal statuses. Gate B counts only real
workers with terminal status `completed`; the three failed events remain
failure-path evidence and do not count toward Gate B. Running, stale,
duplicate, fabricated, and backfilled results are excluded. Four database rows
remain stale `WORKING` rows with expired leases and no matching terminal event.
They are excluded from both gates.

## Final checks

- Candidate-source `second_brain doctor`: **19 checks, 0 failures, 0 warnings**.
- Build identity: **PASS** at the candidate SHA; `dirty=false`, schema `21`,
  fingerprint unchanged.
- Package metadata: **PASS** after cleanup; `package.json` and both
  `package-lock.json` root version fields are `0.2.0`.
- Packaging checks: **PASS** — `npm run typecheck`; `npm ci --dry-run
  --ignore-scripts` reported up to date.
- Critical live final regression: **NOT RUN** after this proceeding checkpoint.
  It requires fresh provider calls and remains blocked by the same Phase 22
  provider boundary; prior live invariant evidence remains documented, but no
  unavailable request is represented as a pass.
- Known local-suite backlog remains as previously recorded: Python `1802
  passed / 13 failed`, TypeScript `642 passed / 18 failed`, ESLint `9`
  findings, Ruff `438` findings, and Pyright `85` diagnostics.
- Candidate-source telemetry validator reports 301 historical heartbeat records
  missing `artifacts_gc_count`; no historical telemetry was rewritten.

The last authoritative provider response was HTTP `429 rate_limit_error` with
`retry-after-ms: 9017000`, observed around `2026-09-04T19:49Z`. The cooldown had
not elapsed at the proceeding checks, so no fresh OMP provider-backed activity
was started. The two-gate semantics correction was recorded before
qualification resumes. The remaining real-activity deficits are:
13 terminal-result events, 16 successful completions, 1 worker launch,
2 compactions, and 9 project switches.
**RELEASE DECISION: HOLD**

No `v2.0.0` tag is created. Qualified release SHA: **NONE**. Resume only with
fresh real OMP activity after provider capacity returns, then rerun the missing
Phase 22 coverage and the critical live final regression.
