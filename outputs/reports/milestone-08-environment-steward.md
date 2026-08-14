# Milestone 08 — Environment Steward (Phase 8)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-07 (Accuracy) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Environment snapshots (plan §74) and PID-reuse-safe process ownership
(plan §75) with advisory cleanup that never touches anything it does not own.

### Exact files

- `src/second_brain/envsteward.py` — snapshot (git/env/tools/repowise/lockfiles),
  process registry with PowerShell start-time identity, verify_process,
  cleanup_owned (dry-run default; token + identity + fresh-verify guards)
- `src/second_brain/cli.py` — `env snapshot`, `processes register|list|verify|cleanup`
- `tests/test_envsteward.py` — 17 tests (incl. PID-reuse detection via
  monkeypatched probe; Hypothesis registry consistency)
- `outputs/reports/milestone-08-environment-steward.md` (this file)

## Requirement-to-evidence (Phase 8 acceptance, plan §104)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Owned process tracking | live: spawned owned sleep process -> registered with verified start-time identity -> verify True |
| 2 | PID reuse-safe identity | start_time equality required; unit tests prove a reused PID with different start time fails verify; records without start_time are identity_verified=false and never killed |
| 3 | Worktree tracking | live snapshot shows worktrees + branch/HEAD/dirty |
| 4 | Dependency mutation reporting | lockfiles/package-manager/language heuristics in snapshot (reported, not enforced — advisory) |
| 5 | No unrelated process killed | live: dry-run killed nothing (process alive); --kill terminated ONLY the registered pid; skipped=0, unknown=0; code paths never kill unverified/foreign-token records |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (212 tests)
live: env snapshot on the build repo (branch/head/dirty/worktrees/tools correct)
live: process register/verify/dry-run/kill cycle on a real owned sleep process
```

## Deviations

1. Process start-time via PowerShell Get-CimInstance (no new pip dependency;
   plan allows the smallest sufficient mechanism; psutil rejected per stdlib-
   first policy).
2. `children` field reports "not visible from Python" — agent-spawn visibility
   needs the Prime extension side (deferred; recorded, not hidden).
3. Dry-run reports would-kill entries inside `killed` with `dry_run: true`
   flags (cosmetic naming; semantics correct).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: env steward (snapshot of the build repo), process registry
  (owned demo process), requirement ledger (Phase 8 gate record).
- How they were used: the build repo snapshot is stored in the working set
  (state/sessions/build-phase8-env/environment.json); the kill-cycle proved
  the safety acceptance on a real process.
- Observed benefit: environment state now machine-readable per session;
  cleanup safety is demonstrated, not asserted.
- Observed overhead: snapshot ~0.6s (PowerShell-free except process probes).
- Token/context effect: n/a (no context injection).
- Failures or friction: none beyond the recorded deviations.
- Knowledge captured: snapshot + ownership records; E-candidates for Phase 9
  (environment episodes).
- Memory/episode IDs: n/a (Phase 9 next).
- Candidate improvements: wire snapshot into the Prime extension
  session_start (Phase 8 extension hook); children visibility via extension.
- Promotion decision: env/processes -> ADVISORY (manual commands; cleanup
  requires explicit --kill).

## Rollback

- Git: revert this milestone's commits.
- Process registry is derived data under state/ownership/ (delete = forget).

## Next gate

**Phase 9 — Episodic Memory** (plan §105): capture, episode files, episode DB
rows, salience, prediction-error, provenance; multi-agent-safe unique writes.
Design + 9 real dogfood episodes in outputs/plans/phase9-episodic-design.md.


## Phase 8 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase8-independent-verification.md):
1. NIT — task_text parameter finally dropped from risk.assess_risk (the
   earlier fix had missed the multi-line signature; now removed for real,
   21 risk tests green).
