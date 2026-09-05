# Final P1 Repair — Release Decision

## Candidate

- Branch: `brain/v2-omp-final-p1-repair`
- Evidence HEAD: `7cbc3ba06ff36230eb58db2554848ec254b7cf13` (plus this report
  and its siblings, committed after)
- Branch point: `0b2aaf9788c8df6f174bd738377333f10364fd20`
  (`brain/v2-omp-qualification`, the prior HOLD documentation HEAD)
- OMP: `18.1.10` (`C:\Users\assas\.bun\bin\omp.exe`)
- Deployed extension: `~/.omp/agent/extensions/second-brain`, manifest
  SHA-256 `c5aa134ea5987576d1554cb8fea32c62752f33ec938154a95138907faab03882`
  (byte-exact to source commit `7cbc3ba`'s `brainstem/prime-extension/{src,types}`)
- Adapter build fingerprint:
  `100575fea2a92d55fe948a41f6cd67960d5626927c14eaaf0bf5d9d511cb5335`

## Scope and disposition

This repair pass targeted exactly two defects
(`00-starting-state.md`): `P1-OMP-WORKER-AUTODELIVERY` and
`P1-OMP-INSTALLER-DEFAULT`. **Both are fixed, unit-tested, and live-proven
against the deployed candidate:**

- Worker-result auto-delivery: 12/12 unit tests pass
  (`03-worker-regression-results.md`); live 8-worker batch captured 8/8 real
  completions via `message_end`/`async-result` with zero `hub` polling
  (`10-live-8worker-autodelivery-proof.md`).
- Installer/uninstaller default path: 2 new unit tests pass
  (`04-installer-regression-results.md`); live install
  (`08-deploy-verification.md`) and rollback (`14-rollback-proof.md`) both
  resolved `~/.omp/agent/extensions` with zero explicit override, both
  byte-exact.
- Zero new regressions: full extension suite unchanged at 650 passed / 18
  pre-existing failures; TypeScript typecheck clean; ESLint findings
  unchanged at 9, all in untouched files; 8/8 focused Python identity tests
  pass (`05-verification-results.md`).
- One new, non-blocking, out-of-scope finding documented for the record:
  `P2-GOVERNOR-BUDGET-LEDGER-OVERSCOPE`
  (`11-hub-and-dedup-proof-infeasibility.md`).

## Overall v2.0.0 release gate

Per `17-release-gate-checklist.md`, gates 22 (sustained burn-in) and 23
(final clean-candidate regression) in
`OMP_V2_QUALIFICATION_MATRIX.md` remain **HOLD**, unchanged by this repair:
they require a sustained, multi-session live campaign under available
provider quota, which is explicitly outside this repair's declared
two-defect scope and was not attempted here. All other gates (0-21, 24)
remain PASS; gate 12 (worker result lifecycle) improves from a conservative
lower-bound PASS to a fully-resolved PASS as a direct result of this
repair.

## Decision

**HOLD.** `v2.0.0` is **not tagged**. This repair's own two defects are
fully closed and release-ready in isolation, but the plan's mandatory-gate
rule ("every mandatory row must be PASS before a `v2.0.0` tag") is not
satisfied while gates 22/23 remain open. No tag was created or pushed.

## What would change this decision

A future pass resuming gates 22/23 specifically (further live sessions
under available provider quota to close the worker-launch, worker-result,
compaction, and project-switch count minima, plus a clean final-regression
rerun) can now proceed without the previously-blocking
`P1-OMP-WORKER-AUTODELIVERY` undercount distorting its worker-result counts,
and without `P1-OMP-INSTALLER-DEFAULT` causing silent deployment-target
misses — both root causes this repair eliminates. The
`P2-GOVERNOR-BUDGET-LEDGER-OVERSCOPE` finding should be triaged before any
large-scale future live campaign against this same `SECOND_BRAIN_HOME`, as
it will otherwise re-trip and block further worker spawns once the
ledger's cumulative worker-token volume crosses `config/governor.toml`'s
`[budgets] worker_tokens` cap again.

## Qualified Release SHA

**NONE** (unchanged — no tag created this pass).
