# Milestone 21 — Frontier Memory (Phase 21)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-20 (Cross-Model Memory) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

A manual review gate for risky policy changes: every activation-critical
change must clear an approve verdict; rejects are final; high-risk changes
are hard-gated (no review -> not activatable). Canonical files only.

### Exact files

- `src/second_brain/frontier.py` — frontier_review/require_review/gate_check/frontier_status/list_pending
- `src/second_brain/cli.py` — `frontier review|require|gate|status|pending`
- `tests/test_frontier.py` — 20 tests + Hypothesis gate-matrix cross-check
- `frontier/policy-active-routing*.md`, `frontier/pending/` — live records
- `outputs/reports/milestone-21-frontier-memory.md` (this file)

## Requirement-to-evidence (Phase 21 acceptance, plan §117)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Risky policy changes require a review entry before activation | live: `policy-active-routing` (real Phase 23 candidate) gated — no review -> ok=False; request_changes -> ok=False; approve -> ok=True |
| 2 | Reject is final | re-reviewing a rejected change raises BrainError (test-asserted) |
| 3 | Deterministic, no schema change | canonical JSON files; Hypothesis reference-implementation cross-check of the gate matrix |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (397 tests, collector count)
live: require (hard gate) -> gate blocked -> request_changes (blocked) ->
approve (cleared) -> status aggregation (approved=1)
```

## Deviations

1. request_changes clears only via a NEW review file
   (frontier/<id>-<n>.md), latest verdict wins; reject ends the sequence.
2. Gate is advisory at the CLI layer today (returns rc 1 when blocked);
   Phase 23 policy activation will CALL gate_check as a hard precondition —
   the real dogfood use.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: frontier memory, requirement ledger (gate record).
- How they were used: the ACTUAL policy change planned for Phase 23
  (activating skill routing for live sessions) was registered through
  require_review, reviewed request_changes -> approve with the rollback-hook
  condition attached — the Brain is reviewing its own future policy change.
- Observed benefit: promotion decisions now have a paper trail + a
  machine-enforced gate instead of an agent's unrecorded judgment.
- Observed overhead: <5ms per operation.
- Token/context effect: none yet (gate is consulted, not embedded).
- Failures or friction: none (one CLI key mismatch fixed during wiring).
- Knowledge captured: frontier review records for policy-active-routing.
- Memory/episode IDs: n/a.
- Candidate improvements: tie gate_check into the Phase 23 promotion path;
  notify reviewers via telemetry when a hold appears.
- Promotion decision: frontier -> ACTIVE-ADVISORY for policy changes
  (hard gate when Phase 23 activates routing).

## Rollback

- Git: revert this milestone's commits. Frontier records are canonical
  files; removing them re-opens gates (documented behavior).

## Next gate

**Phase 22 — Immune System** (plan §118): rollback trigger detectors,
auto-rollback only in canonical, guarded situations. Acceptance: detected
regressions get rolled back when the rollback trigger matches.
