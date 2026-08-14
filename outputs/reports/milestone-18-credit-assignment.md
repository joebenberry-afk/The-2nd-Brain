# Milestone 18 — Credit Assignment (Phase 18)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-17 (Skill Router) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Explicit-only credit assignment (direct/contributory/correlated) with a
structural NO-AUTO-REWARD invariant, credit aggregation reports, and a local
counterfactual evaluator that routes each task with and without a skill
(no filesystem mutation).

### Exact files

- `src/second_brain/credit.py` — assign_credit/credit_report/counterfactual_eval/eval_skill_credit (recommendations only, inert)
- `src/second_brain/router.py` — `skills` override parameter (backward-compatible)
- `src/second_brain/cli.py` — `credit assign|report|counterfactual`
- `tests/test_credit.py` — 24 tests incl. the no-auto-reward invariant + Hypothesis consistency
- `outputs/reports/milestone-18-credit-assignment.md` (this file)

## Requirement-to-evidence (Phase 18 acceptance, plan §114)

| # | Requirement | Evidence |
|---|---|---|
| 1 | direct / contributory / correlated | all three levels assignable explicitly; kind inference (skill/memory/tool/scout/verification/policy); unknown subject -> clean error |
| 2 | Task success does not automatically reward every active skill | invariant TEST: outcome recorded + N skills routed -> zero credit rows unless assign_credit is called; assign_credit is the ONLY writer |
| 3 | Counterfactual replay for major policy candidates | live: sqlite-migration-verifier with/without routing over 12 real tasks -> 6 affected / 6 unaffected |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (374 tests)
live: assign (direct+contributory), report aggregation, counterfactual 6/12 affected
```

## Deviations

1. counterfactual `delta_tools` is 0/unobservable from the Python side
   (honest field, documented).
2. eval_skill_credit produces RECOMMENDATIONS only (inert text) — no writes.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: credit assignment, router, the shadow skill, requirement
  ledger (gate record).
- How they were used: the scout build session received an explicit DIRECT +
  CONTRIBUTORY credit (real evidence from Phase 6); the first
  counterfactual evaluated the real migration-verifier skill on 12 real
  task texts.
- Observed benefit: credit is now auditable per subject/session; the
  no-auto-reward invariant is machine-enforced rather than a policy note.
- Observed overhead: report/assign <5ms; counterfactual ~2ms/task.
- Token/context effect: none (shadow).
- Failures or friction: two CLI field-name mismatches fixed live (total,
  report shape).
- Knowledge captured: credit events for scout; counterfactual report in
  state/ownership? no — credit reports under outputs/verification? (worker
  report path) — see credit report file.
- Memory/episode IDs: n/a.
- Candidate improvements: utility-weighted credit aggregation (Phase 23);
  real outcome deltas need live A/B tasks.
- Promotion decision: credit -> SHADOW (records + recommendations only).

## Rollback

- Git: revert this milestone's commits. Credit events are DB data.

## Next gate

**Phase 19 — Workflow Engrams** (plan §115): detect repeated skill sequences;
candidate-only. Acceptance: engram references existing skills; does not
duplicate giant logic.


## Phase 18 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase18-independent-verification.md):
1. MAJOR — the audits-relocation commit left two worker tests asserting the
   old reports path (RED at HEAD): fixed (tests now assert outputs/audits).
2. NIT — test count corrected to 374.
3. NIT — eval_skill_credit note tightened: no credit events are written;
   the counterfactual report file IS written (documented).
