# Final Clean-Candidate Regression

## Candidate identity

- Branch: `brain/v2-omp-qualification`
- SHA: `86585e114115bc43bf932145e716f2ed4d3dd30e`
- OMP: `18.1.10`
- OMP executable: `C:\Users\assas\.bun\bin\omp.exe`
- Extension: `brainstem/prime-extension/src/index.ts`
- Python: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\.venv\Scripts\python.exe`
- State: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot`
- Adapter build fingerprint: `56b61076903f681215426ae38d6ff47225739283bff731d85db1c71e25d81f68`
- Brain build version: `2.0.0-rc.1`

The candidate worktree was clean before this report was created. A direct
`second_brain doctor` invocation against the explicit state/runtime pair passed
all 19 checks, including build identity (`sha=86585e114115`), schema 21, and
runtime/state coherence.

## Automated checks

| Check | Result | Evidence |
|---|---|---|
| Python full suite | **1802 passed, 13 failed** in 657.50s | command: `.../.venv/Scripts/python.exe -m pytest` |
| TypeScript typecheck | **PASS** | `npm run typecheck` |
| Targeted async worker regressions | **PASS — 4 passed, 91 skipped** | `npx vitest run tests/wiring.test.ts -t "correlates ...\|never double-reports ...\|still-running"` |
| Synchronous ledger spawn-throw regression | **PASS — 1 passed, 28 skipped** | `npx vitest run tests/ledger-mirror.test.ts -t "execFile throws synchronously"` |
| TypeScript full Vitest suite | **642 passed, 18 failed** across 31 files | `npm test` |
| TypeScript lint | **FAIL — 9 existing errors** | `npm run lint`; same pre-existing lint set recorded in Phase 4 |
| Python Ruff | **FAIL — 438 existing findings** | `ruff check src tests`; unrelated repository-wide backlog |
| Python Pyright | **FAIL — 85 existing diagnostics** | `pyright`; unrelated repository-wide backlog |

The Phase 4 baseline delta report established no candidate-only failures at the
qualified comparison point and identical TypeScript failure identities. The
current Python full run was not paired with a fresh baseline run; its failures
are in the previously observed migration, retrieval-isolation, policy, working-
set, and adapter/test-environment classes, while the branch's post-baseline
source repair is TypeScript-only. No new P0/P1 is attributed to the current
candidate from these results. The non-green local suites remain an explicit
release caveat, not a hidden pass.

## Critical live checks

The repaired candidate's already-proven invariant live paths remain documented
in Phases 8–19: AutoInject context delivery, cache invalidation, project
isolation, worker capsule/result attribution, routing, visibility, compaction,
restart, backup/restore, and fail-open behavior. The Phase 19 EINVAL crash was
fixed at `02c9204` and its focused regression passes above.

A complete final live rerun of those critical paths was **not possible** after
the sustained-burn-in attempts: the provider returned HTTP 429
`rate_limit_error` with `retry-after-ms: 9017000`. Retrying would not create
valid qualification evidence. Phase 22 records the resulting coverage hold.

## Final regression result

**HOLD.** The candidate identity and local repair regressions are coherent, but
this is not a clean release qualification: the full local suites retain known
failures, count-based sustained burn-in is incomplete, and the required final
critical live rerun is unavailable under the provider throttle. No `v2.0.0`
tag or release claim is made.
