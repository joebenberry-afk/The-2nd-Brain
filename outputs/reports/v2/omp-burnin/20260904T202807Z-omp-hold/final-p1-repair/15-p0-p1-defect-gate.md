# Phase 17-21 — P0/P1 Defect Gate Re-Evaluation (Post-Repair)

## This repair's two target defects

| Defect | Status | Evidence |
|---|---|---|
| `P1-OMP-WORKER-AUTODELIVERY` | **FIXED** | Unit: `03-worker-regression-results.md` (12/12 pass, incl. 8 new tests covering completed/failed/multi-block/unrelated-message/malformed/unknown-id/dedup-both-orders). Live: `10-live-8worker-autodelivery-proof.md` (8/8 real worker completions captured via `message_end`/`async-result`, zero `hub` polling, against the deployed candidate). |
| `P1-OMP-INSTALLER-DEFAULT` | **FIXED** | Unit: `04-installer-regression-results.md` (2 new default-path tests pass). Live: `08-deploy-verification.md` (byte-exact deploy at `~/.omp/agent/extensions` with zero override) + `14-rollback-proof.md` (byte-exact rollback at the same default path with zero override). |

**P0 open: 0. This repair's P1 count: 0 open, 2 fixed.**

## New defect discovered during this repair's live-proof work (documented, NOT fixed — out of scope)

`P2-GOVERNOR-BUDGET-LEDGER-OVERSCOPE` (working id, not yet filed in a formal
tracker): `governor.check_budget()`'s `_descendant_total_tokens()`
(`src/second_brain/governor.py`) appears to sum worker-session token usage
across sessions that are not actual descendants of the session being
checked — a brand-new, never-before-used session id reported `used: 510,751`
against a `worker_tokens` cap of `120,000` (`config/governor.toml`) before
spawning a single worker of its own, and that figure grew by exactly the
volume of a later unrelated worker batch. Full evidence and reasoning in
`11-hub-and-dedup-proof-infeasibility.md`. Severity: **P2** (real,
reproducible, but requires a specific pre-condition — a `SECOND_BRAIN_HOME`
with substantial historical worker-token volume already recorded under
`state/sessions/` — and fails closed with a clear, non-silent
`INPUT_REQUIRED` message rather than corrupting data or misreporting a
result; not a correctness defect in delivered telemetry). Neither
`brainstem/prime-extension/src/index.ts` (worker-result observer) nor
`scripts/install-prime-extension.ps1`/`uninstall-prime-extension.ps1`
(installer defaults) — the two files this repair changes — are implicated;
`governor.py` and `budget-bridge.ts` are untouched by this repair. Carried
forward as release-hygiene backlog, matching how this campaign already
carries forward the pre-existing 18 TypeScript test failures, 9 ESLint
findings, and the `ledger-mirror`/`prefix_drift` extension_error as
documented, unresolved, non-blocking backlog.

## Gate result

**This repair's own P0/P1 gate: PASS.** Both target defects are fixed,
unit-tested, and live-proven against the deployed candidate. The one new
finding from this pass is a pre-existing, out-of-scope, non-blocking
defect in unrelated code, documented for the record per this campaign's
existing convention of recording (not silently absorbing) every genuine
finding.
