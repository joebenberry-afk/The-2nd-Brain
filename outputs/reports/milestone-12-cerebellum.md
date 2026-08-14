# Milestone 12 — Cerebellum / Predictive Workflow (Phase 12)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-11 (Metacognitive Monitor) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Deterministic workflow-progress assessment: three expected-state templates
(Scout shrinks candidates; tests discriminate hypotheses; verification closes
requirements) plus looping detection that flags stalled exploration from the
read/requirement ledgers. Advisory only.

### Exact files

- `src/second_brain/cerebellum.py` — assess_state/assess_workflow/eval_cerebellum;
  FIXED_BASELINE_REPEATS=3 baseline; events in plan §40 shape
- `src/second_brain/cli.py` — `cerebellum assess|eval`
- `tests/test_cerebellum.py` — 15 tests
- `tests/fixtures/workflows.json` — 12 labeled workflows (6 looping / 6 healthy)
- `outputs/reports/milestone-12-cerebellum.md` (this file)

## Requirement-to-evidence (Phase 12 acceptance, plan §108)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Expected-state templates | 3 templates implemented as deterministic rules; events carry rule/expected/actual |
| 2 | Detect nonprogress | looping = same (path,hash) x2 + no new paths + no status change; stalls via templates |
| 3 | Advisory only | report commands; no mutation anywhere |
| 4 | Detects planted looping EARLIER than fixed thresholds alone | live eval: cerebellum=1.000 vs fixed=0.833 (n=12); all looping cases flagged at read 2 vs fixed at 3/5 or never; two cases the fixed rule never flags |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (279 tests)
live: cerebellum eval -> cerebellum=1.000 fixed=0.833 n=12 (early-detection table shown)
live: cerebellum assess build-phase7-accuracy -> progressing
```

## Deviations

1. "No requirement status change since first read" uses a status proxy
   (any status != unverified counts as change) — the ledgers do not record
   transition timestamps yet; recorded, not hidden.
2. Fixture is hand-crafted; real-trajectory calibration follows as later
   phases produce ledgered sessions.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: cerebellum (eval + assess), working-set ledgers (the
  build's own phase-7 session), requirement ledger.
- How they were used: the build's own phase-7 read/requirement ledgers were
  assessed (progressing — correct: that phase completed its gate); the eval
  proves the acceptance inequality.
- Observed benefit: a cheap deterministic stall detector exists for future
  phases' sessions.
- Observed overhead: assess <10ms (pure ledger reads).
- Token/context effect: none (advisory).
- Failures or friction: one unused-parser ruff catch (cbe) fixed.
- Knowledge captured: n/a new.
- Memory/episode IDs: n/a.
- Candidate improvements: record transition timestamps in the requirement
  ledger (Phase 13 plasticity) to remove the status proxy.
- Promotion decision: cerebellum -> ADVISORY (manual assess); ACTIVE
  monitoring awaits telemetry-side wiring.

## Rollback

- Git: revert this milestone's commits. Nothing active to disable.

## Next gate

**Phase 13 — Plasticity** (plan §109): prediction events, outcomes,
prediction errors, utility updates, hindsight relabeling; shadow learning;
acceptance: replaying identical telemetry produces deterministic updates.
