# Milestone 07 — Accuracy (Phase 7)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-06 (Scout) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Deterministic, explainable Risk Controller (plan §35) and Intent Verifier
briefs (plan §37-38) with anti-confirmation-bias ordering: the diff precedes
the requirements and solver reasoning is structurally excluded.

### Exact files

- `src/second_brain/risk.py` — 9 signals, 0..2 points each, thresholds
  LOW<3/MEDIUM<6/HIGH<9/CRITICAL, user-criticality raises only
- `src/second_brain/verify.py` — brief builder: Backward Reconstruction ->
  Diff (truncated 400 lines) -> Requirements -> Constraints -> Validation
  Evidence -> §37 questions; EXCLUDED_CAPSULE_FIELDS enforced
- `src/second_brain/cli.py` — `risk assess`, `verify build-brief`
- `src/second_brain/working_set.py` + cli — requirement gate now honors
  verification.toml (gate flag separate from blocks)
- `tests/test_risk.py`, `tests/test_verify.py` — 33 tests
- `outputs/reports/milestone-07-accuracy.md` (this file)

## Requirement-to-evidence (Phase 7 acceptance, plan §103)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Detect planted requirement/test mismatch | Fresh-context reviewer eval BRIEF A: REJECT. Backward reconstruction first; REQ-001 flagged as contradicted by the patch; the planted narrow oracle test identified as codifying the violating behavior (state/recon/phase7-eval-results.md) |
| 2 | No major false blocking on low-risk tasks | Fresh-context reviewer eval BRIEF B: APPROVE. Docs-only change; lighter evidence check judged appropriate; no false block |
| 3 | Risk controller | live demo: Phase 8 touch-set scored MEDIUM(5) with explainable signals (centrality, concurrency); 17 risk unit tests |
| 4 | Independent fresh context | the retained reviewer received only briefs + repos (no solver reasoning — asserted: planted decision text absent from brief) |
| 5 | Start HIGH-risk only | verifier runs manually via `verify build-brief`; nothing auto-blocks LOW/MEDIUM (requirement gate honors config; risk does not auto-gate) |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (198 tests)
live: risk assess on real Phase 8 touch-set -> MEDIUM (explainable)
live: two eval briefs built; ordering + exclusion asserted in-process
fresh-context eval by retained reviewer: A REJECT, B APPROVE
```

## Deviations

1. Risk signal weights are starting heuristics (documented constants) — plan
   §35 lists signals, not weights; calibration awaits telemetry (Phase 8+).
2. `risk assess` does not auto-gate anything: HIGH/CRITICAL tasks get a
   printed recommendation to run `verify build-brief`; enforcement stays
   human/lead-controlled (plan: "start HIGH-risk only" — met by default scope).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: working set (gate record), requirement ledger (eval
  requirements verified with reviewer evidence), verify briefs (the eval
  itself), risk controller (live demo on the next phase's own touch-set).
- How they were used: the Phase 7 acceptance criteria were recorded as 2
  critical requirements BEFORE the eval; the fresh-context reviewer's verdicts
  became their evidence; `requirements check` now passes 0/2 unverified.
- Observed benefit: gate evidence is machine-checkable and provenance-linked
  (brief paths + reviewer report); the brief's anti-bias ordering worked —
  the reviewer independently reconstructed the planted intent first.
- Observed overhead: brief build <1s; risk assess ~0.3s (git probes).
- Token/context effect: verifier brief is ~40 lines — the reviewer needed no
  repo exploration to judge the patch.
- Failures or friction: first eval attempt had an empty diff (scenario had
  committed the change) — scenario fixed to working-tree diff; brief label
  bug ("gate off" when nothing unverified) fixed with a separate gate flag.
- Knowledge captured: 2 eval verdicts + reviewer reasoning in
  state/recon/phase7-eval-results.md.
- Memory/episode IDs: n/a (episodic memory = Phase 9, next).
- Candidate improvements: risk weights calibrated from telemetry; verifier
  brief could include the risk verdict (Phase 8+).
- Promotion decision: verify/risk -> ADVISORY (manual commands); no ACTIVE
  promotion without cross-task repetition.

## Rollback

- Git: revert this milestone's commits.
- Nothing active to disable (all manual commands).

## Next gate

**Phase 8 — Environment Steward** (plan §104): environment snapshots, PID
reuse-safe process registry, safe owned cleanup; measurement -> advisory ->
safe cleanup; acceptance: no unrelated process killed.
