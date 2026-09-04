# Second Brain v2 OMP Release Decision

## Candidate
- Branch: `brain/v2-omp-qualification`
- SHA: `86585e114115bc43bf932145e716f2ed4d3dd30e`
- OMP version: `18.1.10`
- OMP executable: `C:\Users\assas\.bun\bin\omp.exe`
- Extension path: `brainstem/prime-extension/src/index.ts`
- SECOND_BRAIN_PYTHON: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot\.venv\Scripts\python.exe`
- SECOND_BRAIN_HOME: `C:\Users\assas\Documents\The-Second-Brain\.worktrees\v2-one-shot`
- Build fingerprint: `56b61076903f681215426ae38d6ff47225739283bff731d85db1c71e25d81f68`

## Qualification Summary
- Gates passed: 0–21, 24, with invariant prior live evidence explicitly identified in the matrix
- Gates failed: none classified as a new implementation defect
- Gates on hold: 22 sustained burn-in; 23 final clean-candidate regression
- P0 open: 0
- P1 open: 0
- P2 open: 0 unexplained reliability defects; coverage remains externally blocked
- Token result: W1 extension overhead +0.42%; W2 cost −52.6%; W6 cost −26.7%; see `../20-token-efficiency/TOKEN_EFFICIENCY.md`
- Latency result: AutoInject median 532ms, p95 944ms, max 1559ms; see `../21-latency-qualification/LATENCY_QUALIFICATION.md`
- Burn-in coverage: 82 unique session identities (72 with provider response), 190 turn starts, 152 tool calls, 19 worker launches, 7 worker results (4 completed/3 failed), 8 compactions, 76 shutdown-bearing sessions, 3 interrupted/recovery cases, 11 project switches, and 2 conflicting controlled projects

## Critical Live Proof
- AutoInject reaches OMP context: PASS — actual context delivery proven; final rerun held by provider quota
- Project isolation: PASS — alternating alpha/bravo sentinels remained isolated
- Worker context capsule: PASS — bounded relevant and empty capsules proven
- Worker result lifecycle: PASS — async completion, failure, dedupe, and running-state regressions pass
- Routing: PASS — live selection and fail-open routing failure proven
- Compaction continuity: PASS — repeated automatic compaction preserved continuity
- Restart persistence: PASS — clean and interrupted restart persistence proven
- Fail-open: PASS — runtime, bridge, project, backup, and ledger faults handled without wrong-memory behavior
- Backup/restore: PASS — manifest/hash restore and SQLite integrity proven
- Rollback: PASS — baseline ancestry, state backup, and isolated byte-exact restore proven

## Prime Dependency Audit
- Prime binary required for OMP v2: **NO**
- If YES, exact capability and code path: N/A
- If NO, obsolete Prime release blocker removed: **YES**

## Decision
**HOLD**

## Reason
The candidate is operationally coherent and the repaired worker-result and
ledger fail-open paths are regression-tested. The release gate is not complete:
Phase 22 remains below the plan's minimums for worker launches (`19/20`), worker
results (`7/20`), compactions (`8/10`), and project switches (`11/20`). The final
critical live rerun needed to close Phase 23 was attempted only until the
provider returned HTTP 429 `rate_limit_error` with `retry-after-ms: 9017000`.
No valid qualification evidence can be manufactured from those unavailable
requests.

The final local suites also retain their known baseline/repository backlog:
Python `1802 passed / 13 failed`, TypeScript `642 passed / 18 failed`, ESLint
9 findings, Ruff 438 findings, and Pyright 85 diagnostics. The prior baseline
delta report records no candidate-only regression, but this final run did not
silently convert a non-green suite into a pass.

The plan requires every mandatory matrix row to be PASS before tagging
`v2.0.0`. This candidate therefore remains an RC qualification hold. Prime is
not a blocker; reinstalling Prime would not address the unmet OMP coverage or
provider quota.

## Qualified Release SHA
**NONE**
