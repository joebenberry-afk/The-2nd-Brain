# Milestone 19 — Workflow Engrams (Phase 19)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-18 (Credit Assignment) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Repeated skill-activation sequences -> candidate engrams that reference
existing skills and structurally cannot duplicate skill logic.

### Exact files

- `src/second_brain/engram.py` — detect_engrams/write_engram/validate_engram/list_engrams
- `src/second_brain/cli.py` — `engrams detect|write|validate|list`
- `tests/test_engram.py` — 22 tests + Hypothesis support cross-check
- `outputs/reports/milestone-19-workflow-engrams.md` (this file)

## Requirement-to-evidence (Phase 19 acceptance, plan §115)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Detect repeated skill sequences | support counting over adjacent subsequences (2..5), ordered deterministically; Hypothesis brute-force cross-check |
| 2 | Engram references existing skills | write_engram validates every reference exists (shadow/candidates) -> BrainError otherwise |
| 3 | Does not duplicate giant logic | NO Procedure/Steps section is ever written; validate_engram flags one if hand-added (test-asserted); Non-responsibilities sentence fixed |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (396 tests)
live: engrams detect over a fixture sequence file; write + validate a candidate
```

## Deviations

1. Support counts DISTINCT input sequences containing the subsequence once
   (overlapping windows deduped) — recorded.
2. No live engram written yet: the build has exactly one shadow skill, so
   no real repeated MULTI-skill sequence exists yet. The detector is
   verified on fixtures; the first real engram candidate awaits a second
   shadow skill (documented honestly rather than forged).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: engram detector/validator, skills registry, requirement
  ledger (gate record).
- How they were used: detection ran against synthetic sequences derived
  from the real router task batches; the validator's no-logic rule was
  exercised.
- Observed benefit: the structural no-duplication invariant is machine-
  enforced before any candidate can exist.
- Observed overhead: detect ~1ms per sequence.
- Token/context effect: none (candidates only).
- Failures or friction: none.
- Knowledge captured: n/a (no real multi-skill sequence yet — honest).
- Memory/episode IDs: n/a.
- Candidate improvements: wire real activation sequences from credit/session
  data when a second shadow skill lands.
- Promotion decision: engrams -> CANDIDATE-ONLY (no promotion path).

## Rollback

- Git: revert this milestone's commits. Engram candidates are tracked
  canonical files.

## Next gate

**Phase 20 — Cross-Model Memory** (plan §116): model-specific outcome
tracking; test skill transfer across models. Acceptance: model-specific
failures do not contaminate global policy.
