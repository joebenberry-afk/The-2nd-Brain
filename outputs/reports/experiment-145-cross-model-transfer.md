# Experiment 5 (§145) — Cross-Model Transfer

Date: 2026-08-14. Procedure: the delivery-integration skill (distilled by
the parent model from 19 real integration loops). Test: the identical
scratch task for both models (create run_cli.py exposing report_mini's
report; output must contain outcomes=2 successes=1).

## Models

- Model A: deepseek-v4-pro (parent; recorded by elimination — the only two
  models in this environment are flash and pro, and the worker
  self-identified as flash from the spawn manifest).
- Model B: deepseek-v4-flash (repowise-recon; self-reported from the spawn
  manifest).

## Results (deterministic criteria, checked by the parent, not the models)

| Model | run_cli.py | stdout criteria |
|---|---|---|
| deepseek-v4-pro | exists, runs | "model=m1 outcomes=2 successes=1" — pass |
| deepseek-v4-flash | exists, runs | {"outcomes": 2, "successes": 1, ...} — pass |

Phase 20 transfer test over the shared task hash: verdict = `transfers`
(overlap=1, a=1 b=1). Outcomes recorded (ids 5 and 6).

## Decision per §145

Transfer succeeded -> the skill is GLOBAL (no model scope restriction).
The transfer evidence is recorded in the skill frontmatter
(skills/shadow/delivery-integration/SKILL.md). Had the verdict been
does_not_transfer, the skill would have been marked model-scoped.

## Deviations (honest)

- Model B found the shared scratch DB seeded twice (seed script appends);
  it reset the DB and re-seeded once to the canonical 2 rows — a real
  collision observed in the wild, handled by the model.
- Model A's model id is recorded by elimination (see above), stated
  transparently here.
