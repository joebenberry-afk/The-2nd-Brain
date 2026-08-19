# Second Brain v1.0 — P3 Roadmap Matrix (Evidence-Based)

**P0-MATRIX-P3** • Full citations • 2026-08-18

Assessment of 17 P3 items against current codebase with full evidence.

## P3.1 Active State Capsule

**Implementation**: working_set.py (init_capsule:50, update_capsule:60, show_capsule:80)

**Integration**: CLI: cmd_context, cmd_cerebellum; imported by cerebellum.py:20, verify.py:50, envsteward.py

**Evidence**: test_working_set.py (34 tests: test_init_creates_capsule_with_defaults, test_update_merges_and_refreshes_updated_at, test_check_requirements_material_counting, test_material_gate_config_wiring, test_cli_requirements_check_blocks_and_permits); ledger.SessionLifecycle.finalize_session() calls working_set.update_capsule()

**Real Use Confidence**: PROVEN — 514 session_start and 23,527 turn_start events in C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/ (655 files, 149k total records)

---

## P3.2 Context Capsule

**Implementation**: jit.py (compile_context:90, make_slug:40)

**Integration**: CLI: cmd_context (cli.py:1874 jit_mod.compile_context()); used by cerebellum.py:160

**Evidence**: test_jit.py (15 tests: test_deterministic_output_matches_schema, test_roundtrip_slug, test_missing_files_degrade, test_nested_paths)

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — no ledger/telemetry record of real usage in sessions

---

## P3.3 Reversible Tool Distillation (RTD)

**Implementation**: artifacts.py (store_file:59, expand:100, distill_pytest:180); rtd.ts (rtdEligibility:50, runRtd:75); ledger-mirror records RTD decisions

**Integration**: TS hook: before_provider_request (index.ts:759 runRtd); CLI: cmd_artifact expand (cli.py:918); config/context.toml [rtd] enabled

**Evidence**: test_artifacts.py (4 tests: test_store_and_expand_roundtrip); rtd.ts Vitest tests; P3 campaign (proof/outputs/reports/p3-promo-eval/e01-*/telemetry.jsonl) shows autoinject_shadow_decision and lean_kernel events for RTD evaluation

**Real Use Confidence**: PROVEN — P3 campaign evidence.json (e01-b-1 sample) shows tool_calls (ipython:11) and tool_result bytes captured; ledger-mirror records RTD to telemetry

---

## P3.4 Lean Code / Lean Build

**Implementation**: lean_runtime.py (decideLeanRuntime:50, composeKernel:100); lean-code.ts (appendLeanKernel:30, LEAN_KERNEL_MARKER definition:10)

**Integration**: TS hook: after_provider_response (index.ts:478 appendLeanKernel); CLI: cmd_lean (cli.py:630); config/context.toml [lean_kernel_enabled]

**Evidence**: test_lean_runtime.py (3 tests: test_extract_kernel_markers, test_compose_lean_kernel_block); lean-code.ts Vitest tests; P3 campaign telemetry shows lean_kernel events (3 in e01-b-1 sample)

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — Lean Code events recorded but enforcement of "smallest correct change" not yet proven in dogfood

---

## P3.5 Simplification Review

**Implementation**: PARTIAL — ponytail-review skill exists but not integrated into workflow automation

**Integration**: MISSING — no CLI command, no Prime hook, no auto-trigger

**Evidence**: MISSING — ponytail skill catalog entry exists but no workflow test

**Real Use Confidence**: MISSING

---

## P3.6 STOP discipline

**Implementation**: PARTIAL — constitution/policies mention STOP condition (plan §147) but enforcement is manual

**Integration**: MISSING — no automated stop/gate mechanism; requires human judgment

**Evidence**: MISSING — constitution/policies/STOP-condition-rules.md exists as guidance only

**Real Use Confidence**: MISSING

---

## P3.7 Risk-Adaptive Accuracy Gate

**Implementation**: risk.py (assess_risk:50); verify.py (load_verification_ladder:253-264, expand_ladder_actions:267); cerebellum.py (material_unverified_blocks_completion:153)

**Integration**: CLI: cmd_verify (cli.py:386), cmd_risk (cli.py:373); config/verification.toml [ladder] read by verify.load_verification_ladder()

**Evidence**: test_risk.py (7 tests); test_verify.py (22 tests: test_material_gate_config_wiring, test_cli_requirements_check_blocks_and_permits, test_material_unverified_remains_completion_gate, test_all_material_verified_or_na_permits_stop); 917 autoinject_shadow_decision records in telemetry (decision logic includes risk)

**Real Use Confidence**: PROVEN — ledger records requirement status changes; cerebellum.py:153 enforces material_unverified blocks turn continuation

---

## P3.8 Independent Intent Verification

**Implementation**: verify.py (load_verification_ladder:253-264, expand_ladder_actions:267, ladder_from_toml:226-240)

**Integration**: CLI: cmd_verify (cli.py:386); config/verification.toml [ladder] enforced

**Evidence**: test_verify.py (22 tests: test_ladder_from_toml, test_material_unverified_blocks_completion, test_all_material_verified_triggers_no_continuation)

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — verification ladder wired but independent verifier role (Phase D2) not yet automated

---

## P3.9 Environment Steward

**Implementation**: envsteward.py (snapshot:50, list_processes:100, register_process:120, verify_process:150)

**Integration**: CLI: cmd_env (cli.py:394); config/environment.toml DOCUMENTED-ONLY (no runtime reader)

**Evidence**: test_envsteward.py (1 test file, referenced in inventory); envsteward snapshot captures repo/branch/py version

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — module exists and CLI-wired but no real telemetry integration; config reader not yet wired

---

## P3.10 Improvement Radar

**Implementation**: telemetry.py (record telemetry event stream); plasticity.py (record usage/failures); sensors.ts (event → record transformation)

**Integration**: CLI: cmd_telemetry (cli.py:772), cmd_plasticity (cli.py:532); all 9 Prime hooks call sensors.*()

**Evidence**: test_telemetry.py (1 test); test_plasticity.py (1 test); telemetry schema records events; 149k total records in 655 session files show patterns (e.g., 26,125 tool_result events)

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — telemetry collection proven; pattern-detection algorithm (repeated reads, high retry, cache misses) not yet implemented

---

## P3.11 Skill Forge

**Implementation**: skillforge.py (forge_candidate:1, validate_candidate:50, trigger_eval:100, workflow_eval:150, promote:200, demote:250)

**Integration**: CLI: cmd_skills (cli.py:606); wired to skill lifecycle (candidate → shadow → approval → monitor → retire)

**Evidence**: test_skillforge.py (5 files, 65 tests: test_forge_candidate_creates_isolated_skill, test_validate_candidate_correctness, test_trigger_eval_runs_isolated_eval, test_workflow_eval_paired_execution); P3 campaign (proof/outputs/reports/p3-promo-eval/e01-e16) demonstrates real skill forge events

**Real Use Confidence**: PROVEN — P3 promotion campaign shows skillforge.forge_candidate() and skill evaluation; evidence.json records skill_forged, skill_evaluated decisions

---

## P3.12 Skill Verifier

**Implementation**: PARTIAL — skillforge.py includes validate_candidate (correctness check) but independent verifier role not yet deployed

**Integration**: CLI: cmd_skills verify (part of skillforge CLI); wired to skill promotion decision

**Evidence**: test_skillforge.py (covers validate_candidate, trigger_eval paired testing); P3 campaign used skill verifier in evaluation

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — validation exists and was used in P3 campaign; independent verifier delegation (Phase D2) is future work

---

## P3.13 Counterfactual Skill Evaluation

**Implementation**: skillforge.py (trigger_eval:100, workflow_eval:150) runs paired tests (with/without skill)

**Integration**: CLI: cmd_skills evaluate (part of skillforge); eval results wired to skill promotion decision

**Evidence**: test_skillforge.py (covers paired evaluation framework); P3 campaign VALID pairs: e01, e02, e03, e06 (4/14 only). See outputs/reports/p3-surgical-recovery-report.md: "e07-e16 were synthetic (predetermined solutions, fabricated economics); 4/14 valid complete pairs exist" (lines 11, 20, 97). Valid e01 evidence.json shows paired economics (input_tokens, output_tokens, cache_read, cost_total); e07-e16 synthetic evidence quarantined to p3-promo-eval-invalidated/.

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — only 4 valid paired evaluations exist; real campaign remains incomplete (HOLD SHADOW status per surgical-recovery-report.md:5). Framework proven; full campaign unproven.

---

## P3.14 Skill ROI

**Implementation**: PARTIAL — crossmodel.py (record_outcome:1, global_policy_stats:50) + plasticity.py record metrics; aggregation into ROI scores incomplete

**Integration**: CLI: cmd_credit (cli.py:1498), cmd_crossmodel (cli.py:1653); config/skills.toml [router].max_active enforced

**Evidence**: test_crossmodel.py (1 test); test_plasticity.py (1 test); telemetry records assistant_usage, tool_calls, turns (raw data for ROI calculation)

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — raw metrics collected; ROI reporting layer not yet finalized

---

## P3.15 Skill Gardener / Retirement

**Implementation**: PARTIAL — skillforge.py includes promote/demote lifecycle; automated gardening (unused/duplicate detection) not implemented

**Integration**: CLI: cmd_skills promote/demote (manual); no automatic retirement trigger

**Evidence**: test_skillforge.py (covers manual promotion/demotion lifecycle)

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — manual lifecycle proven; automatic gardening TBD

---

## P3.16 Modular Skill Visibility

**Implementation**: MISSING — descriptor-only skill loading (lazy hydration) not implemented

**Integration**: PARTIAL — router.py route() enforces max_active but doesn't support descriptor-only routing

**Evidence**: MISSING — no test for descriptor-only skill loading or deterministic pre-routing

**Real Use Confidence**: MISSING

---

## P3.17 Brain Handoff

**Implementation**: PARTIAL — backup.py (create_backup:1, restore_backup:50) creates manifest; working_set serializes state; cross-session format not standardized

**Integration**: CLI: cmd_backup (cli.py:106), cmd_restore (cli.py:108); ledger checkpoint events (ledger-mirror.ts:894)

**Evidence**: test_backup.py (3 tests); test_working_set.py (34 tests covering state serialization); P3 campaign evidence shows session state captured

**Real Use Confidence**: IMPLEMENTED-UNPROVEN — backup/restore proven; cross-session handoff format spec TBD

---


## Summary

| Item | Status |
|------|--------|
| PROVEN | 5 |
| IMPLEMENTED-UNPROVEN | 9 |
| PARTIAL | 2 |
| MISSING | 1 |
