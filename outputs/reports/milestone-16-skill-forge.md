# Milestone 16 — Skill Forge (Phase 16)

Date: 2026-08-14 (UTC)
Specification: `The_Second_Brain_OS_V4_2_Self_Hosting_OneShot_Implementation_Plan.md`
Prior gate: milestone-15 (Reconsolidation) — complete (PASS-WITH-FINDINGS, reconciled).

## What changed

Episode -> candidate skill pipeline with all four §112 gates: structural
validation (§60 sections), trigger-boundary eval, workflow eval, regression
eval, and static security review. Shadow is gated on ALL of them; nothing
auto-installs or auto-promotes.

### Exact files

- `src/second_brain/skillforge.py` — forge_candidate/validate_candidate/
  trigger_eval/workflow_eval/regression_eval/security_review/shadow_candidate/
  list_*
- `src/second_brain/cli.py` — `skills forge|validate|eval|shadow|list` (eval
  and shadow require --cases; shadow runs all four gates)
- `tests/test_skillforge.py` — 28 tests + Hypothesis trigger determinism
- `tests/fixtures/skill-eval-cases.json` — eval fixture
- `skills/shadow/sqlite-migration-verifier/` — first real candidate (dogfooded)
- `outputs/reports/milestone-16-skill-forge.md` (this file)

## Requirement-to-evidence (Phase 16 acceptance, plan §112)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Episode -> pattern -> candidate | 2 real workflow episodes + 1 correction episode -> forged SKILL.md with merged triggers/counter-signals/procedure |
| 2 | Trigger boundaries | trigger eval: positive phrases, negative override ("...but documentation-only change" -> no_trigger), 4/4 on the real candidate |
| 3 | Workflow eval | structural procedure check on the real candidate (5-step loop present) |
| 4 | Regression eval | baseline cases pass (repeated positive + doc-only negative) |
| 5 | Security review | static heuristics (destructive commands, secrets, exfil, injection) — clean on the candidate |
| 6 | Shadow only, no auto-install | shadow_candidate requires all four gates (tightened during the live demo: it originally allowed shadow without evals — fixed + regression-tested); nothing promotes |

## Commands / checks actually run

```text
ruff/format/pyright/pytest -> green (368 tests)
live: forge sqlite-migration-verifier -> validate ok -> eval 4/4/True/pass/pass -> shadow
```

## Deviations

1. Live demo exposed and fixed two gate weaknesses: shadow accepted a
   candidate without trigger/regression evidence (cases now REQUIRED), and
   trigger phrases kept their "- " bullet prefix (stripped; case matching is
   now on the phrase text).
2. Workflow eval is structural (procedure execution remains the caller's
   job) — recorded honestly in the eval output's `note` field.
3. Forged procedure lines may double-number when a source lesson already
   had numbers (cosmetic; candidate review step).

## Dogfooding / Self-Hosting (v4.2 §95.1 template)

- Subsystems used: skill forge (candidate pipeline), episodes (sources),
  requirement ledger (gate record).
- How they were used: v4.2 Stage 7 — the sqlite-migration-verifier
  candidate was derived from TWO real repeated workflow episodes (migrations
  0002-0003 and 0004-0005 landings, identical five-step verification loop)
  plus the WAL-restore correction episode; all four evals passed with real
  boundary cases before shadow.
- Observed benefit: the build's most-repeated verification procedure is now
  a shadow skill with explicit trigger boundaries and provenance.
- Observed overhead: forge + evals <300ms total.
- Token/context effect: none (shadow; not loaded anywhere).
- Failures or friction: the two gate weaknesses above — found by dogfooding
  the tool on itself, fixed with regression tests.
- Knowledge captured: episodes success-20260814-025897e6 +
  success-20260814-7e49e733; candidate skills/shadow/sqlite-migration-verifier.
- Memory/episode IDs: as above.
- Candidate improvements: counterfactual eval (with/without candidate)
  belongs to Phase 18 credit assignment; promote gate later.
- Promotion decision: candidate -> SHADOW (earned by repeated real evidence;
  ACTIVE promotion requires Phase 23 policy-promotion evidence).

## Rollback

- Git: revert this milestone's commits. Candidate/shadow dirs are canonical
  (tracked): delete to forget.

## Next gate

**Phase 17 — Skill Router** (plan §113): sparse top-K routing, shadow route
first; compare model-natural routing vs Brainstem route. Acceptance: lower
trigger noise; no success regression.
