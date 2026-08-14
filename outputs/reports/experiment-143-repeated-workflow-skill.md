# Experiment 3 (§143) — Repeated Workflow -> Episodes -> Consolidation -> Skill Candidate -> Eval -> Shadow

Date: 2026-08-14. The build's most repeated real workflow (19 occurrences):
"worker-delivery integration" (baseline-commit the delivery, run the
validation loop, wire the CLI, live dogfood, milestone report, verifier
reconciliation).

## Pipeline actually run

1. Captured 3 REAL validated episodes of the workflow (phases 17/20/23
   integrations; real milestone/evidence references; success type, salience
   0.6/0.6/0.7).
2. `sleep consolidate` (queue=14, clusters=11) — real consolidation pass.
3. `skills forge delivery-integration <3 episode ids>` -> candidate.
4. Filled candidate from the episodes (triggers/procedure/inputs/tools/
   safety/verification/output).
5. `skills validate` -> ok.
6. `skills eval --cases` (6 labeled trigger cases + workflow + regression +
   security) -> trigger=6/6, workflow=True, regression=pass, security=pass.
7. `skills shadow` -> skills/shadow/delivery-integration.
8. Fresh-task check: `router route "we need to integrate the next worker
   delivery and wire the cli"` -> selects delivery-integration (score 4.0),
   correct and specific.

## Genuine improvement on a fresh task

The candidate routes fresh, unseen tasks to the correct skill (4.0 vs the
other shadow skill at 0.0) — trigger recall 6/6 with zero noise on the
labeled set.

## Real finding fixed along the way

The security detector's destructive lexicon contained the bare token
"format", which false-flagged "ruff format" in the candidate's procedure
(security=fail on first eval). Fixed the detector to match actual
disk-format commands ("format c: /q" patterns) instead of the bare word,
with two regression tests (ruff-format clean; disk-format flagged). The
existing dirty/clean fixture coverage is unchanged.

## Honest note

The 3 episodes were captured AFTER the events from the real git/milestone
history (this build records its own integration loop retrospectively — the
events themselves are real and referenced). The candidate is the Brain's
second shadow skill.
