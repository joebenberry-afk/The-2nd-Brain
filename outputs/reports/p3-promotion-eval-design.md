# P3 Promotion-Evidence Campaign — Eval Design + Fixture Freeze Pack (Worker A)

Plan: Second_Brain_P3_Lean_Code_Promotion_Evidence_Plan.md (§5, §6, §7, §14, §22).
Branch `brain/p3-lean-code` @ 7008da2. AutoInject ACTIVE (untouched). Lean
kernel/skill FROZEN (see §10). No commits; no arm runs; no deployment.

## 1. Diagnosis — why the previous P3-E tasks were near-minimal for BOTH arms

The t01-t18 set produced near-identical minimal footprints in both arms
(window-2: 34/34 minimal, savings within noise, median per-pair input delta
+359 tokens). Root causes, cited:

1. **The task prompts encoded the minimal path** (fixtures/lean-code-tasks/*/TASK.md):
   every prompt carried explicit constraints that IS the lean answer —
   "do not modify app.js and do not add files" (t01), "do NOT modify test.js"
   (t03/t04/t05/t07/t11/t12/t13/t16), "do not create any script or tool file"
   (t08), "The repo intentionally has NO dependencies ... Do NOT add any"
   (t06), "do not extract a shared fee engine" (t04). The arm was TOLD the
   expected solution class, so there was no decision to make — both arms
   complied and tied.
2. **Acceptance gates were SHAPE checks, not behavior checks** (JUDGE.md):
   `git diff --name-only` exactly one allowed file (t01/t03/t13/t14/t17/t18),
   "no ?? entries" (t01/t04/t05/t06/t08/t12/t16). Overbuild was FAILED at
   acceptance, so it was never measured as a cost; both arms were forced to
   the same minimal diff.
3. **Tiny surface**: fixtures were 2-6 files / ~30-100 LOC. There is no room
   to overbuild 5-10x on a 50-line repo; footprint ratios were measured on a
   near-empty decision space.
4. **Oracles shipped complete + arms forbidden to touch them**: fixtures
   contained the full acceptance tests (test.js/verify.js) and arms were told
   not to modify them — no test-depth decision, no under/over-testing signal.
5. **One-decision tasks**: most tasks had a single shallow decision (one
   config key, one char fix, one rename); the tree was "do the minimal thing
   or fail", not "choose among several acceptance-passing engineering levels".

Consequence: the eval measured compliance with encoded minimality, not Lean
behavior on opportunity-rich tasks. The promotion campaign therefore needs
USER-STYLE requests (no encoded constraints), behavior-only acceptance,
bigger repos with existing capabilities to reuse/abuse, and shape/diff/LC
recorded as METRICS — never as gates (except risk-appropriate gates on E13).

## 2. Task set (14; E1-E16 minus E4/E5)

E4 (premature-abstraction temptation) and E5 (legitimate abstraction) are
covered by the two new skill-eval regression cases (anti-overbuild ≈ E4,
anti-laziness ≈ E5) which live in the permanent `brainctl skills eval`
mechanism. Keeping them as arm-run tasks too would double-test the same
lesson; the arm set keeps one task per remaining category:

| id | category (plan §6) | fixture |
|---|---|---|
| e01 | E1 config instead of code | deploy-profiles |
| e02 | E2 existing function extension | price-formatting |
| e03 | E3 existing tool composition | log-pipeline |
| e06 | E6 dependency temptation | customer-sort |
| e07 | E7 legitimate dependency | jsonc-config |
| e08 | E8 new-tool temptation | call-count-analysis |
| e09 | E9 legitimate new tool | release-table |
| e10 | E10 small preparatory refactor | net-amount |
| e11 | E11 unrelated cleanup temptation | greet-trim |
| e12 | E12 already-minimal | math-double |
| e13 | E13 high-risk change | crash-safe-store |
| e14 | E14 live-source vs stale memory | debug-toggle |
| e15 | E15 requirement ledger incomplete | order-validation |
| e16 | E16 stop-after-proof | title-config |

Opportunity tasks (≥8 required): e01,e02,e03,e06,e08,e10,e11 = 7 by the
§6 letter; e16 is also opportunity-shaped (optional overwork after proof),
and e07/e09 are anti-laziness opportunities — 10 of 14 carry genuine
solution-space branching.

## 3. Fixture format (NEW — different from t01-t18)

Per fixture dir `tests/fixtures/lean-opportunity-tasks/<id>-<slug>/`:

- **TASK.md** — the USER-STYLE request only (natural phrasing, no acceptance
  text, no constraints, no file lists, no "do not modify X"). The arm gets
  exactly this + the repo.
- **tests/** — realistic in-repo test files (oracle) that FAIL at baseline and
  define done by behavior. Arms see them (real repos have tests).
- **JUDGE.md** — deterministic commands for the analysis phase: step 0
  restores pristine oracle files from the fixture source (anti-tamper), then
  behavior commands (exit codes), then METRIC captures (git diff --numstat,
  --name-only, porcelain) recorded as evidence — NOT gates, EXCEPT e13 where
  the risk-appropriate atomic-write pattern is part of acceptance.
- **CARD.md** — the internal evaluation card (plan §7 fields). NEVER shown to
  arms: task_id, user-style request, repo baseline, acceptance, current
  reusable capabilities, risk level, known legitimate solution classes,
  known unjustified expansion classes, metrics.

## 4. Anti-overbuild + anti-laziness skill-eval cases (plan §5)

Added to `tests/fixtures/skill-eval-cases.json` (existing shared format):
trigger cases + regression baselines that a lean-code whose trigger boundary
drifts would FAIL:

- **anti-overbuild** (≈E4): an implementation request describing a plausible
  unnecessary wrapper/manager around existing capability — expected
  `trigger` (Lean must engage and steer to reuse; a lean-code whose positive
  triggers no longer fire on extension/config work fails the case) +
  regression baseline.
- **anti-laziness** (≈E5): an implementation request where a NEW abstraction
  is genuinely justified (stable contract, 3+ call sites) — expected
  `trigger` (Lean must NOT suppress creation; a lean-code whose negative
  triggers wrongly fire on "extract/abstraction" fails the case) + regression
  baseline.
- plus lean-specific no_trigger boundary cases (pure explanation must not
  trigger) and the existing security texts stay shared.

Expected `brainctl skills eval lean-code` result: security pass; the NEW
cases predict exactly (trigger/trigger/no_trigger); the pre-existing
migration-verifier cases predict no_trigger against lean-code (different
domain — reported as-is, not tuned).

## 5. Acceptance rubric (plan §10 + §12 gates)

Per pair: acceptance PASS/FAIL (judge exits); metrics collected: files
touched, added/deleted lines, new files, new deps/tools/modules, LC codes,
input/output/cache_read/cache_write/cost, turns, tool_calls, wall_ms,
AutoInject packet tokens (separate), judge exits, arm self-report evidence.
Promotion gates per plan §12 (correctness non-inferior, protected values,
verification depth, high-risk adequacy, no LOC gaming, opportunity-task
savings with justification allowed) — evaluated by the driver after both
arms run; this design doc does not pre-judge.

## 6. Counterbalance schedule (plan §9)

Pairs alternate: odd-numbered tasks (e01,e03,e06,e08,e10,e12,e14,e16)
baseline-first; even-numbered tasks (e02,e07,e09,e11,e13,e15) candidate-first.
Provider cache fields (cache_read/cache_write) reported separately per arm;
no savings claim from warm-cache order.

## 7. Freeze declaration (plan §4/§14)

- lean kernel sha256 = 0af4076fb0bb1137f640f2c69f7a28825d2fdab53e95011916eb984e6c620122
  (865 chars, byte-stable) — MUST remain byte-identical.
- lean skill sha256 = fbc6dd65868e2e71... (record full value at freeze time;
  do not modify skill body).
- lean state = candidate (inert); AutoInject = ACTIVE; RTD = SHADOW (not
  expanded in this campaign).
- HEAD = 7008da2 (brain/p3-lean-code).
- Brain isolation: P3 freeze backup (existing mechanism) between arms.
- After this document is written, NOTHING in it may change without
  invalidating the campaign (plan §14).

## 8. Fixture index + validation

(14 fixtures; each validated BOTH ways: JUDGE fails on the unmodified
fixture, passes on the reference minimal solution — see validation run log.)

## 9. Fixture index (14) — card summaries (full cards live in each CARD.md)

| id-slug | category | risk | legitimate classes (any pass acceptance) | unjustified classes (metrics only) |
|---|---|---|---|---|
| e01-deploy-profiles | E1 config vs code | LOW | config entry (+tiny fallback tweak) | manager class, CLI flag machinery, new config format |
| e02-price-formatting | E2 extend existing fn | LOW | extend formatPrice in place; local sign helper | duplicate formatCredit/Money class/strategy |
| e03-log-pipeline | E3 compose existing tools | LOW | compose filter|stats (+minimal stdin support; tiny npm script ok) | new error-report tool, framework, dep |
| e06-customer-sort | E6 dependency temptation | LOW | stdlib comparator (toLowerCase/localeCompare) | lodash/underscore, new sorting module |
| e07-jsonc-config | E7 legit dependency | LOW | use listed jsonc-simple (one require) | hand-rolled stripper, new parser dep, preprocessing |
| e08-call-count-analysis | E8 new-tool temptation | LOW | one-liner / node -e -> analysis.txt | committed analysis tool with args, CLI command, dep |
| e09-release-table | E9 legit new tool | LOW | single-purpose make_table.js (+test) | generic table engine, plugin system, dep |
| e10-net-amount | E10 prep refactor | LOW | extract round2 + fix; fix with expression once | module rewrite, strategy, duplicating the fix |
| e11-greet-trim | E11 cleanup temptation | LOW | fix greet only | modernize legacy.js (measured creep), rename helpers |
| e12-math-double | E12 already-minimal | LOW | 2-line double() | refactor/rename/reorganize |
| e13-crash-safe-store | E13 high-risk | HIGH | temp+rename atomic write (+fsync note) | journal subsystem, transaction wrapper, dep |
| e14-debug-toggle | E14 live source vs stale | LOW | settings.debug=true | read debug_mode (fails), dual-key, doc "fix" |
| e15-order-validation | E15 ledger incomplete | MEDIUM | both REQ checks + run verify.js | stop after REQ-1, modify verify.js |
| e16-title-config | E16 stop-after-proof | LOW | config edit + test + stop | README/docs rewrite, extra tests, extra verifier |

## 10. Anti-overbuild + anti-laziness skill-eval cases (plan §5) — ADDED

`tests/fixtures/skill-eval-cases.json` (shared file, existing format) gained:
- **trigger_cases +6** (lean-code): anti-overbuild x2 (implementation + plausible
  wrapper/manager/dep — MUST trigger), anti-laziness x2 (justified
  extraction/reusable tool — MUST trigger), no_trigger boundaries x2 (pure
  explanation / pure research — must NOT trigger).
- **regression_baselines +2**: anti-overbuild + anti-laziness — MUST STAY
  triggers (a lean-code whose trigger boundary drifts FAILS).
- security texts unchanged (shared).

`brainctl skills eval lean-code` result (exact):
`trigger=10/14 workflow=True regression=fail security=pass`
- security=pass ✓; all 6 new trigger cases predict exactly; both new
  regression baselines pass; the 4 trigger failures + 1 regression failure
  are the PRE-EXISTING migration-verifier cases (restore/WAL texts) which
  correctly predict no_trigger for lean-code — cross-skill noise in the
  shared fixture, not a lean-code defect. The CLI `--cases` flag exists for
  per-skill files if the campaign wants a lean-only file later (not built
  now — no new file per scope). The kernel/skill were NOT tuned.

## 11. Acceptance rubric (evaluator use)

Per pair: acceptance = all JUDGE exit codes 0 (oracle restored pristine
first). Metrics per arm: files touched, added/deleted lines, new files, new
deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
exits, arm report. Opportunity scoring: legitimate-class solutions score
Lean-consistent; unjustified-class solutions that still pass acceptance are
recorded as expansion evidence (tokens/context cost measured, not assumed).

## 12. Counterbalance schedule (plan §9)

Odd tasks (e01,e03,e06,e08,e10,e12,e14,e16): baseline-first, candidate-second.
Even tasks (e02,e07,e09,e11,e13,e15): candidate-first, baseline-second.
cache_read/cache_write reported per arm; no warm-cache savings claims.

## 13. Freeze declaration (plan §4/§14) — CAMPAIGN IS FROZEN AFTER THIS LINE

- lean_kernel_sha256 = 0af4076fb0bb1137f640f2c69f7a28825d2fdab53e95011916eb984e6c620122 (865 chars, byte-stable) — MUST remain byte-identical.
- lean_skill_sha256 = fbc6dd65868e2e71... (skill body frozen; verify full value before execution).
- lean_state = candidate (inert); autoinject = active; rtd = shadow (not expanded).
- lean runtime gate: config/skills.toml currently carries `[lean] eval =
  "advisory"` in the working tree (leftover P3-E re-run flip, uncommitted,
  parent-managed). The promotion campaign arms REQUIRE the flip per arm:
  baseline arms `eval = "off"` (or absent), candidate arms `eval =
  "advisory"` (env SECOND_BRAIN_LEAN overrides). Worker B verifies the
  switch; this doc freezes the PROCEDURE (flip between arms), not the current
  working-tree value.
- head = 7008da2 (brain/p3-lean-code).
- brain_snapshot = existing P3 freeze backup (restore between arms per §8 isolation).
- task set, task cards, JUDGE acceptance, rubric, counterbalance schedule:
  FROZEN. Any change invalidates the campaign and requires a clean restart
  from this document (plan §14: no rewriting prompts after interim numbers,
  no adding/removing tasks after seeing results, no kernel tuning).

## 14. Validation log (Worker A)

- 14/14 fixtures validated BOTH ways: JUDGE fails on the unmodified fixture
  (real gap) and passes on the reference minimal solution.
- Sanity test tests/lean-opportunity-fixtures.test.ts (5 tests) run ONLY it:
  5/5 pass.
- pytest tests/test_router.py: 16/16 pass (router unaffected by the
  skill-eval-case additions — the cases are data).
- No full suites run; no commits; no arm runs; no deployment.
