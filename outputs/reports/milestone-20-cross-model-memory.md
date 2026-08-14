# Milestone 20 — Cross-Model Memory (Phase 20)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-19 (Workflow Engrams) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Model profiles + model-scoped skill outcomes (caller-recorded), a transfer
test across models on overlapping task hashes, and a global-policy
aggregator that structurally excludes unreliable model profiles.

### Exact files

- `src/second_brain/migrations/0006_model_profiles.sql` — model_profiles + model_skill_outcomes
- `src/second_brain/crossmodel.py` — record_model/record_skill_outcome/model_skill_report/transfer_test/global_policy_stats
- `src/second_brain/cli.py` — `models add|record|report|transfer|policy`
- `tests/test_crossmodel.py` — 26 tests incl. contamination guard + Hypothesis
- legacy-test bumps: backup fabricated-migration renumber (0007, asserts v7), episodes v1-brain drop-list
- `outputs/reports/milestone-20-cross-model-memory.md` (this file)

## Requirement-to-evidence (Phase 20 acceptance, plan §116)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Model-specific outcome tracking | outcomes carry model_id + task_hash; per-model report (live: flash 3 outcomes 1 success f1 0.333; pro 1/1 f1 1.0) |
| 2 | Transfer test across models | live: same task recorded for both models -> verdict `transfers` (a=1 b=1); no overlap -> `no_data` |
| 3 | Model-specific failures do not contaminate global policy | live: flash dropped to 1/3 -> EXCLUDED from global_policy_stats (rate 0.333 < 0.5); global success_rate stays 1.000; threshold is tested at the boundary |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (400 tests)
live: models add (2 profiles) -> record 4 outcomes -> transfer verdict +
policy guard exclusion (flash excluded at 0.333, pro included at 1.0)
```

## Deviations

1. Live DB migration 0006 is applied on first open (schema now v6).
2. Two integration fixes required during wiring: read paths did not ensure
   migration on the pre-existing live DB (fixed: `_outcome_rows` now calls
   `_ensure_migrated`); CLI used wrong response keys (details->tasks,
   overlap->overlap_count, included_models->models_included) — fixed.
3. `models add` added to CLI because outcomes require a known profile.
4. Recovery incident (honest record): during wiring the parent corrupted
   the untracked worker delivery with a broken docstring splice; the worker
   re-delivered the module. Procedure change: worker deliveries are now
   committed as a baseline BEFORE any parent edits (already applied here).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: cross-model memory, the real shadow skill, requirement
  ledger (gate record).
- How they were used: outcomes for the real migration-verifier skill were
  recorded for the two models actually used by this build
  (deepseek-v4-pro/flash), a real transfer test ran on the shared task, and
  the contamination guard was exercised with real failure rows.
- Observed benefit: model failures are structurally walled off from global
  policy — the acceptance inequality is enforced by code, not convention.
- Observed overhead: each operation <5ms.
- Token/context effect: none (shadow).
- Failures or friction: the three integration fixes + the recovery incident
  (Deviation 4).
- Knowledge captured: model profiles for deepseek-v4-pro/flash in the live
  DB; 4 real outcomes.
- Memory/episode IDs: n/a.
- Candidate improvements: auto-infer model ids from telemetry when the
  extension is installed (needs the Prime API, later phase).
- Promotion decision: cross-model memory -> SHADOW (caller-recorded only).

## Rollback

- Git: revert this milestone's commits. Migration 0006 is NOT reversible
  (additive tables only — safe to leave; rollback restores pre-0006 code).

## Next gate

**Phase 21 — Frontier Memory** (plan §117): manual review gate for policy
changes that feel risky. Acceptance: risky policy changes require a review
entry before activation.
