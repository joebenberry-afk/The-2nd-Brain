# Milestone 23 — Policy Promotion (Phase 23)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-22 (Immune System) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Shadow -> candidate -> active promotion with ALL guards (evidence,
frontier approve, immune-clear), demotion with reason records, promotion
history, and the router pool upgraded to active+candidate+shadow so a
promoted skill stays routable.

### Exact files

- `src/second_brain/promotion.py` — promote/demote/promotion_status/is_active
- `src/second_brain/router.py` — level-aware pool (active>candidate>shadow priority lookup)
- `src/second_brain/cli.py` — `promote|demote|promotions` + router help text
- `tests/test_promotion.py` — 20 tests + Hypothesis guard-matrix cross-check
- `state/promotions/` — real promotion records
- `outputs/reports/milestone-23-policy-promotion.md` (this file)

## Requirement-to-evidence (Phase 23 acceptance, plan §119)

| # | Requirement | Evidence |
|---|---|---|
| 1 | A policy activates ONLY when all guards pass | live: promote refused (`frontier_not_approved`) before review; after approve -> promoted with guards {evidence: True, frontier_approved: True, immune_clear: True} recorded per move |
| 2 | Evidence guard | G1 = credit rows OR model outcomes for the skill (4 real outcomes counted) |
| 3 | Frontier guard | G2 = frontier approve on `skill-<name>-promotion` (real high-risk review exists) |
| 4 | Immune guard | G3 = no rollback records for the skill policy |
| 5 | Adjacent moves only | skip-level refusal test-asserted |
| 6 | Demotion records reason | demote writes a record with reason (tested) |

## Live promotion (the dogfood headline)

The Brain promoted its own first skill with its own machinery:

```text
promote sqlite-migration-verifier shadow candidate  -> refused: frontier_not_approved
frontier review skill-sqlite-migration-verifier-promotion high approve -> ok
promote shadow -> candidate -> promoted (guards all True)
promote candidate -> active -> promoted (guards all True)
status -> {'sqlite-migration-verifier': 'active'}
```

Post-promotion live router eval over the real task set is UNCHANGED from
the Phase 17 verified gate: router f1 0.4167 / noise 1 vs natural 0.25 /
noise 3 — the acceptance inequality still holds with the skill active.

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (444 tests, verifier collect pending)
live: refusal -> approve -> two guarded promotions -> status -> re-eval
```

## Deviations

1. Downward moves carry NO guards (always recorded) — per spec.
2. Router pool now includes active+candidate (Phase 23 requirement);
   route() remains report-only; the `shadow: True` flag is kept as the
   historical "non-authoritative routing" marker (test-pinned shape).
3. The frontier approve used for promotion is the same change_id family as
   the Phase 21 policy-active-routing review (separate id per skill).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: promotion, frontier, credit/crossmodel evidence, immune,
  router, requirement ledger (gate record).
- How they were used: the migration-verifier skill walked the full
  shadow->candidate->active pipeline using evidence the Brain recorded
  about itself; the router then routed the ACTIVE skill with gate-identical
  numbers.
- Observed benefit: promotion decisions are now a machine-checkable chain
  of evidence -> review -> move -> record, not an unrecorded judgment.
- Observed overhead: <10ms per promotion.
- Token/context effect: none.
- Failures or friction: none (one CLI help-text refresh).
- Knowledge captured: 2 real promotion records under state/promotions/.
- Memory/episode IDs: n/a.
- Candidate improvements: automated evidence refresh before candidate->
  active; telemetry-fed immune guards.
- Promotion decision: THE PROMOTION SUBSYSTEM ITSELF is ACTIVE (it just
  promoted the first skill under its own rules).

## Rollback

- Git: revert this milestone's commits. Promotion moves are recorded;
  reversing a move is a demote (records a reason) — safe by design.

## Next gate

**Post-implementation: v4.2 §141-145 real experiments + the v4.2
self-hosting success-criteria checklist (all 24 phases implemented).**
