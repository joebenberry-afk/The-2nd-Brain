# Milestone 15 — Reconsolidation / Forgetting (Phase 15)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-14 (Replay / Sleep) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Retrieval/activation bookkeeping, contradicted->labile reconsolidation,
HOT/WARM/COLD/ARCHIVED heat states with protected-memory decay rules.
Forgetting is advisory: heat changes only, never destroys history.

### Exact files

- `src/second_brain/migrations/0005_reconsolidation.sql` — memory_activations,
  memory_retrievals, memories heat/count columns
- `src/second_brain/reconsolidation.py` — record_retrieval/record_activation/
  apply_heat/decay_pass (protected: verified-current + constitution/security-
  titled; never auto-ARCHIVED)
- `src/second_brain/cli.py` — `reconsolidation retrieval|activation|heat|decay`
- `tests/test_reconsolidation.py` — 22 tests + Hypothesis count consistency
- `outputs/reports/milestone-15-reconsolidation.md` (this file)

## Requirement-to-evidence (Phase 15 acceptance, plan §111)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Activation tracking | retrieval/activation rows live-demoed (correct outcome on the WAL memory); counts consistent under Hypothesis |
| 2 | Strength | contradicted -> COLD + labile (plan §49 reconsolidation event); correct -> successful count |
| 3 | Labile state / supersede | contradicted memories enter labile for review; heat never touches versions/files (test-asserted) |
| 4 | hot/warm/cold/archive | heat transitions enforced (HOT only verified/tested-current; ARCHIVED never current) |
| 5 | Forgetting advisory | decay dry-run default; live demo decayed 0 (recent + protected memories); never auto-ARCHIVED |
| 6 | Stale memory loses hot priority / critical protected memory does not decay / history recoverable | decay_pass rules + protected set + file-untouched tests |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (333 tests)
live: retrieval + correct activation on mem-29557f93448f; decay dry-run (0 decays)
```

## Deviations

1. Decay reference time = last_retrieved_at else created_at (retrievals only
   start being recorded now — recorded, not hidden).
2. TTLs are config defaults (hot 7d, warm 30d), not yet wired to
   retrieval.toml.

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: reconsolidation records, semantic memory (targets), decay
  pass, requirement ledger (gate record).
- How they were used: the first real retrieval + activation cycle was
  recorded for the WAL memory during Phase 14 consolidation follow-up;
  decay demonstrated advisory-only on live data.
- Observed benefit: memory utility is now measurable (retrieval/success/
  contradiction counts) — groundwork for retrieval scoring (Phase 15+ / §26).
- Observed overhead: each record <5ms.
- Token/context effect: none (advisory).
- Failures or friction: none beyond deviations.
- Knowledge captured: 1 retrieval + 1 correct activation (mem-29557f93448f).
- Memory/episode IDs: mem-29557f93448f; session build-phase14.
- Candidate improvements: wire TTLs to retrieval.toml; heat-based JIT
  filtering (Phase 16+).
- Promotion decision: reconsolidation -> ADVISORY (manual commands; decay
  requires --apply).

## Rollback

- Git: revert this milestone's commits. Heat/count changes are DB data
  (restorable from backup).

## Next gate

**Phase 16 — Skill Forge** (plan §112): episode -> pattern -> candidate
skill -> eval -> shadow; no auto-install. Acceptance: candidate has trigger
boundaries, workflow eval, regression eval, security review.
