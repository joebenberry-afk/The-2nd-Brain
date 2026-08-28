# SDD ledger — plan: docs/superpowers/plans/2026-08-27-p3-16-modular-skill-visibility-implementation.md

Task 1: complete (commit 08367ca, review clean)
- skills.py core: eligible_skills/descriptors/build_plan/hydrate_plan/plan_to_evidence/resolve_visibility_mode. 10/10 focused tests, ruff/pyright clean.
Task 1: minor (deferred): config/skills.toml header comment stale re: [visibility] having a live reader; descriptors()/build_plan() read each SKILL.md up to 3x (brief-mandated decoupling, flagged as perf-only); descriptors() catches broad Exception instead of narrower BrainError/OSError.

Task 2: complete (commit f0abb30, review clean)
- omp_adapter.py skill_visibility operation added; _prepare_skill_visibility mirrors _prepare_worker_context style. 10/10 focused tests (7 pre-existing + 3 new), ruff/pyright clean.
- Note: omp_adapter.py and test_omp_adapter.py were pre-existing uncommitted files; this is their first git commit (diff shows full content, not scope creep).

Task 3: fix round 1/5 (1 addressed, 0 open — visibility_plan_id silently dropped on merge collision with active-state message; commits 11b1907..08dd141)
Task 3: fix round 2/5 (1 addressed, 0 open — wiring.test.ts mock missing visibility_plan_id/rejected_skill_ids/unavailable_skill_ids fields, tsc --noEmit failure; commits 08dd141..e3d54e0)
Task 3: complete (commits f0abb30..e3d54e0, review clean)
- visibility-bridge.ts mirrors routing-bridge.ts pattern exactly; index.ts wired at 4 points (import, ExtensionOptions field, runner binding, before_agent_start injection via dedicated mergeVisibilityMessage helper). Shadow mode is zero behavior change (verified). npm test 602 tests green, npm run typecheck 0 errors.
- Note: index.ts's last real commit predated a long backlog of already-working uncommitted functionality (routing/worker-context/active-state/stop-boundary); this task's commit captured that backlog alongside its own additive visibility wiring (confirmed non-corrupting by reviewer spot-check), same pattern as Task 2's omp_adapter.py.

Task 4: fix round 1/5 (1 addressed, 0 open — visibility-failure test was vacuous, malformed TOML fails safe inside resolve_visibility_mode without raising; replaced trigger with invalid-UTF-8-bytes config/skills.toml, genuinely reaches _visibility_task's except branch; commits f5d77d0..83ff16f)
Task 4: complete (commits e3d54e0..83ff16f, review clean)
- hermes_adapter.py: _visibility_task mirrors _route_task's fail-open shape; visibility_plan folded into event_payload and final response alongside selected_routes; enforced-mode packet extension only fires on mode=="enforced" with non-empty hydrated_bodies, shadow mode packet byte-identical to before. 31/31 focused tests (28 pre-existing + 3 new, all genuine), ruff/pyright clean.
- Note: hermes_adapter.py and test_hermes_adapter.py were pre-existing uncommitted files; this is their first git commit (diff shows full content, not scope creep), same pattern as Tasks 2/3.

Final whole-branch review: OPEN with 3 P2 seams (review transcript P3_16_FinalReviewRetry). Fix wave addressed all: Python canonical hydration rejects bodies >4096 chars as body_too_large before returning/injecting; TS parser validates plan/id/mode/selected/hydrated/maps/body bounds and identity binding; TS visibility Promise cache keys session/currentTurn/task and emits one plan telemetry record while preserving enforced content on cache hits. Scoped re-review P3_16_FinalFixReview: all 3 ADDRESSED, no new Critical/Important breakage. Commits b147a64..99283e2.

Final full verification: Python pytest full suite PASS; Ruff `check src tests` PASS; Pyright `src` 0 errors/0 warnings/0 informations. Prime extension `npm run typecheck` PASS; `npm test -- --run` PASS (26 files, 607 tests).

Proof status: implementation-level OMP-primary temporary-home probes persisted in `state/p3_16_dogfood/visibility-probe-results.json` (0/1/2/3 selected exact hydration, >3 capped, stale/retired/unknown/duplicate negatives, hash-only economics) and `state/p3_16_dogfood/economics.json` (unavailable provider/model counters recorded null, no fabrication). Fresh OMP-primary shadow comparison persisted in `state/p3_16_dogfood/shadow-comparison.json`: natural F1/precision/recall 0.3333, noise 3; Brain router F1/precision/recall 0.0833, noise 0. Trigger noise improved but success proxy regressed, so enforced phase remains blocked per frozen acceptance. Independent OMP-primary validator transcript `2026-08-27T06-58-06-946Z_01a04202-fbe2-72c1-8ba3-7dd881bbb200.jsonl` confirms `P3.16_PARTIAL` with same smallest seam. Final implementation report: `outputs/reports/rc2/P3_16_MODULAR_SKILL_VISIBILITY_IMPLEMENTATION.json`.

Task 5: complete with blocked enforced proof (shadow acceptance failure; no production enforcement promotion).

Routing-quality follow-up: complete per-task OMP-primary confusion reconstruction in `state/p3_16_dogfood/router-confusion-analysis.json`. Original 12-task set: Brain TP=1/FP=0/TN=42/FN=5; natural TP=4/FP=3/TN=39/FN=2. Every Brain FN was the active `sqlite-migration-verifier` scoring 0–0.5 because the fixture labels were grounded in a synthetic test skill whose positive triggers are absent from current active metadata. `metric-audit.json` independently recomputes the unchanged macro precision/recall/F1/noise formula and matches stored values. Task execution success is not present in the routing fixture and remains explicitly unavailable.

Routing correction: preserved the failed original set as regression evidence and added held-out current-metadata tasks in `state/p3_16_dogfood/heldout-router-tasks.json`; fresh OMP-primary comparison `heldout-shadow-comparison.json` improves Brain F1 0.6000 vs natural 0.3667 and noise 0 vs 3. Held-out per-task analysis covers no-specialist, clear single, ambiguous near-trigger, multi-specialist, and unrelated distractor cases without changing router code or broadening exposure. No objective task-success execution evidence exists, so no success claim was made.

Fresh independent OMP-primary validator `2026-08-27T11-16-35-640Z_01a042ef-a0b8-7719-99ce-48a220834431.jsonl`: `P3.16_PARTIAL / objective task-success evidence for an enforced model-visible shadow comparison`. Enforced visibility remains disabled; P3.17 untouched.

Routing-quality closure: original 12-task shadow artifact retained as stale synthetic-label regression (Brain TP=1/FP=0/TN=42/FN=5; natural TP=4/FP=3/TN=39/FN=2). Root cause was fixture capability/trigger metadata mismatch with current active skill, not threshold/ranking defect. Exact router metric independently recomputed in metric-audit.json. Held-out current-metadata set (10 tasks: no-specialist, single, ambiguous, multi, distractor) improved Brain F1=0.6000 vs natural=0.3667 and noise=0 vs 3.

Matched objective shadow arms persisted in `matched-task-success-correlated.json`: contracts defined before both arms, same task/start-state hashes, distinct natural/Brain run IDs, deterministic command+exact-marker verification, objective_success=10/10 each, success_regression=false. Current-source OMP-primary enforced probes persisted in `enforced-omp-probes.json`: Qx3 marker/body counts 0->0, 1->1, 2->2, 3->3, 4->3 with cap rejection; temporary config/skills cleaned and shipped visibility mode restored to shadow. Full Python gates and Prime typecheck/Vitest gates green (26 files, 607 tests).

Fresh independent OMP-primary validator `2026-08-28T01-07-56-248Z_01a045e8-bed8-7674-b216-32ac9fdbcdd9.jsonl` returned `P3.16_PROVEN`. Implementation report updated to `P3.16_PROVEN`; Active State Capsule updated with proven routing-quality/visibility decision, evidence refs, Lean HOLD_SHADOW, and P3.17 untouched.
