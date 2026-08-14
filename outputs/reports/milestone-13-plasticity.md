# Milestone 13 — Plasticity (Phase 13)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-12 (Cerebellum) — complete (PASS-WITH-FINDINGS; NITs documented, no code change needed).

## What changed

Shadow learning records: predictions with prediction-error flags, raw outcome
vectors (§42), prediction errors with salience, explicit credit events
(no auto-reward path exists — §43), hindsight bottleneck relabels (§45), and
an append-only utility log. Deterministic replay verified.

### Exact files

- `src/second_brain/migrations/0004_plasticity.sql` — predictions/outcomes/
  prediction_errors/credit_events (CHECK-constrained)
- `src/second_brain/plasticity.py` — record_*/hindsight_relabel/utility_update/
  replay; credit level REQUIRED (no defaults)
- `src/second_brain/cli.py` — `plasticity predict|outcome|credit|hindsight|utility`
- `tests/test_plasticity.py` — 25 tests incl. Hypothesis random-op replay determinism
- `outputs/reports/milestone-13-plasticity.md` (this file)

## Requirement-to-evidence (Phase 13 acceptance, plan §109)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Prediction events / outcomes / prediction errors / utility updates / hindsight relabeling | all five recorders live-demoed; hindsight relabel records a §45 training example when predicted != actual (live: localization -> environment) |
| 2 | Shadow learning — no automatic policy enforcement | records only; nothing mutates policy, skills, or routing; credit requires an explicit level argument (plan §43: task success never auto-rewards) |
| 3 | Replaying identical telemetry produces deterministic updates | live: same event sequence on two fresh brains -> identical row contents (modulo wall-clock created_at + autoincrement ids, by design); Hypothesis random-op replay determinism in tests |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (311 tests)
live: deterministic replay (2 fresh brains, 5-event sequence -> content-equal)
live: hindsight relabel (real: localization->environment), outcome vector, explicit credit, utility delta
```

## Deviations

1. `hindsight_relabel` writes the prediction row with prediction_error=0
   (expected==actual by construction) and the error signal lives in the
   prediction_errors row — recorded per worker design.
2. Timestamps in replay are wall-clock (not synthetic event time); replay
   determinism is defined over content modulo ids/ts.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: plasticity recorders, hindsight relabel, working-set
  session ids (real build sessions), utility log.
- How they were used: the Phase-1 PYTHONHOME surprise was relabeled
  localization->environment (a real prediction error from the build);
  Phase-6 scout received an explicit DIRECT credit with evidence; the scout
  utility delta (+1) is the first shadow utility record.
- Observed benefit: the build's own causal signals are now structured for
  Phase 14 replay/consolidation.
- Observed overhead: each record <5ms.
- Token/context effect: none (shadow).
- Failures or friction: replay content comparison first included timestamps
  (false mismatch) — clarified the determinism definition and fixed the
  comparison.
- Knowledge captured: 1 prediction error (localization->environment),
  1 outcome vector, 1 credit event, 1 utility delta.
- Memory/episode IDs: n/a (references episode environment-20260814-fb37901d).
- Candidate improvements: aggregate utility in Phase 14 sleep; attach
  transition timestamps to requirement statuses (removes the Phase-12 proxy).
- Promotion decision: plasticity -> SHADOW (records only; no policy
  application until Phase 14+ evidence).

## Rollback

- Git: revert this milestone's commits.
- Records are derived data (DB tables + plasticity/*.jsonl).

## Next gate

**Phase 14 — Replay / Sleep** (plan §110): `brainctl sleep` manual command;
conservative consolidation pass only (replay high-priority episodes, cluster,
verify provenance, strengthen semantic memory, detect contradictions, update
utility). Acceptance: no invented verified facts; all semantic updates
provenance-linked; candidate ideas remain candidate.


## Phase 13 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase13-independent-verification.md):
1. NIT — test count corrected to 311.
2. NIT — hindsight docstring corrected: the error signal lives in the
   prediction_errors row (the prediction row's expected==actual by
   construction), matching the documented design.
