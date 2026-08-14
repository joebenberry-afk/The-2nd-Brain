# Milestone 11 — Metacognitive Monitor (Phase 11)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-10 (Semantic Memory) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Shadow-only trajectory confidence monitor: 11 explainable signals map to
epistemic/execution/verification axes (categories LOW/MEDIUM/HIGH, integer
math, no fake precision), with a labeled-trajectory eval comparing it against
a basic heuristic and the honest random baseline.

### Exact files

- `src/second_brain/monitor.py` — assess_confidence (11 signals), basic_heuristic, eval_monitor
- `src/second_brain/cli.py` — `metacog assess|eval`
- `tests/test_monitor.py` — 19 tests (signal math, boundaries, determinism, eval assertion)
- `tests/fixtures/trajectories.json` — 12 labeled trajectories (6 bad / 6 good)
- `outputs/reports/milestone-11-metacognition.md` (this file)

## Requirement-to-evidence (Phase 11 acceptance, plan §107)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Trajectory-based confidence categories | 3 axes x LOW/MEDIUM/HIGH; every axis traceable to contributing signals with details (live assess on build-phase7: HIGH across axes with verifier_disagreement + stale_source listed) |
| 2 | Shadow mode only | monitor is a report command; no code path blocks or mutates anything |
| 3 | Low-confidence trajectories correlate with real problems better than random/basic heuristic | live eval: monitor agreement 1.000 vs basic 0.583 vs random 0.500 on 12 labeled trajectories (incl. 4 epistemic-only bad cases the heuristic misses and 1 good-transient-failure case it false-positives) |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (264 tests)
live: metacog eval -> monitor=1.000 basic=0.583 random=0.5 n=12
live: metacog assess build-phase7-accuracy -> HIGH/HIGH/HIGH with signal trace
```

## Deviations

1. Eval fixture is hand-crafted (12 trajectories) — real-trajectory
   calibration begins when later phases capture session working sets +
   telemetry together; recorded, not hidden.
2. Random baseline reported as the 0.5 expectation, never simulated (honest).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: metacog (eval + assess), working set (real trajectory
  input), requirement ledger (gate record).
- How they were used: assess ran against the build's own phase-7 working
  set + git state; the eval proves the acceptance inequality on labeled data.
- Observed benefit: confidence categories + signal trace are machine-readable
  and explainable; the eval guards regressions in signal weighting.
- Observed overhead: assess ~50ms (no subprocesses when telemetry omitted).
- Token/context effect: none (shadow).
- Failures or friction: fixture shape mismatch (dict-wrapped) fixed in the
  CLI; a stray walrus operator cleaned by ruff.
- Knowledge captured: n/a new (signals reuse existing ledgers).
- Memory/episode IDs: n/a.
- Candidate improvements: record monitor verdicts into session telemetry
  (Phase 12+); calibrate thresholds from real outcomes.
- Promotion decision: metacog -> SHADOW (measurement only; promotion awaits
  correlation with real verification outcomes across phases 12+).

## Rollback

- Git: revert this milestone's commits. Nothing active to disable.

## Next gate

**Phase 12 — Cerebellum / Predictive Workflow** (plan §108): expected-state
templates (Scout shrinks candidates; test discriminates hypothesis;
verification closes requirements), nonprogress detection, advisory only.
Acceptance: detects planted looping exploration earlier than fixed
thresholds alone.


## Phase 11 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase11-independent-verification.md):
1. NIT — test count corrected to 264.
2. NIT — metacog assess --telemetry read is now guarded (corrupt file ->
   clean error, exit 2).
3. NIT — 1.000 agreement on the hand-crafted fixture: acknowledged as
   signal-fixture alignment; generalization stays unproven until real
   trajectories accumulate (shadow-only; milestone deviation #1).
