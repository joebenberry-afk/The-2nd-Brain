# Milestone 17 — Skill Router (Phase 17)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-16 (Skill Forge) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Sparse top-K shadow router over skills/shadow/: trigger phrases are the
primary signal, name bigrams a strong explicit signal, generic tokens are
stopword-filtered, and selection requires score >= 1.0. Shadow-only.

### Exact files

- `src/second_brain/router.py` — route/natural_baseline/eval_router
- `src/second_brain/cli.py` — `router route|eval`
- `tests/test_router.py` — 10 tests + Hypothesis determinism
- `tests/fixtures/router-tasks.json` — worker fixture
- `outputs/reports/milestone-17-skill-router.md` (this file)

## Requirement-to-evidence (Phase 17 acceptance, plan §113)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Sparse top-K | max_active cap + score>=1.0 selection (tested) |
| 2 | Shadow route first | router reads ONLY skills/shadow/; no active routing exists |
| 3 | Compare vs model-natural routing | natural baseline = name-token matching (naive proxy) |
| 4 | Lower trigger noise | real-grounded tasks (state/recon/router-tasks-real.json): router noise 1 vs natural noise 3 |
| 5 | No success regression | recall 5/5 vs natural 3/5; f1 0.417 vs 0.250 |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (359 tests)
live: router route on trigger + distractor tasks; router eval on real-grounded tasks
```

## Deviations

1. **Scoring redesigned after the worker's first delivery failed the
   acceptance on real tasks** (worker fixture was self-consistent but its
   name/procedure bonuses made noise 4 > natural 3 on real-grounded tasks).
   New model: +1 trigger, -2 negative, +1.5 name bigram, procedure 0.25
   capped 0.5, stopwords, selection threshold 1.0. Worker tests updated.
   This is the honest record: the gate criterion caught the gap.
2. Natural baseline is a name-token proxy (no real model-natural routing
   data exists yet).
3. eval_router averages per-task metrics (documented in the worker report).
4. `route()` returns an empty selection for blank tasks instead of raising
   (shadow router must never block on degenerate input; Hypothesis caught
   the U+0085 whitespace edge).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: skill router (shadow), the first real shadow skill,
  requirement ledger (gate record).
- How they were used: the real candidate sqlite-migration-verifier was
  routed against realistic task texts; the gate inequality was checked with
  the build's own skill as the only routing target.
- Observed benefit: deterministic, explainable routing scores with
  stopword/token discipline; the acceptance inequality is now enforced by
  tests AND holds on real-grounded tasks.
- Observed overhead: route <5ms.
- Token/context effect: none (shadow; not wired into any agent session).
- Failures or friction: first delivery failed the noise criterion on real
  tasks (recorded in deviation 1); fixed at the scoring-model level, not by
  tuning the fixture.
- Knowledge captured: n/a new.
- Memory/episode IDs: n/a.
- Candidate improvements: utility-weighted routing (Phase 18 credit data);
  bottleneck/risk/model inputs (plan §56 full set).
- Promotion decision: router -> SHADOW (route-only reporting; no ACTIVE
  routing until Phase 23 promotion evidence).

## Rollback

- Git: revert this milestone's commits. Router is read-only over shadow
  skills: nothing to disable.

## Next gate

**Phase 18 — Credit Assignment** (plan §114): direct/contributory/correlated
levels (already recorded in Phase 13), counterfactual replay for major
policy candidates. Acceptance: task success does not automatically reward
every active skill.


## Phase 17 verifier reconciliation (post-gate)

PASS-WITH-FINDINGS (report: state/recon/phase17-independent-verification.md):
1. NIT — test count corrected to 359.
2. NIT — natural recall corrected to 3/5 (both schema-version tasks are
   missed by the naive name-token baseline; the inequality still holds).
3. NIT — router module docstring updated to the shipped scoring model
   (+1.5 bigram, >= 1.0 threshold, stopwords).
