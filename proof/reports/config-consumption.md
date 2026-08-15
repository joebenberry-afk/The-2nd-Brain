# Configuration-consumption audit

Generated for v4.3 Phase 0 against the current checkout. `Operative` means a
mutation changes current runtime behavior. `doctor.check_config` parsing alone
does not make a policy key operative.

| Config | Key | Runtime reader | Tested mutation? | Operative? |
|---|---|---|---|---|
| brain.toml | schema_version | doctor.check_config (parse only) | parse | no |
| brain.toml | brain.name | none | no | no |
| brain.toml | db.path | db.db_path | no | no; canonical path is hard-coded relative to home |
| brain.toml | db.journal_mode | db.connect | no | no; runtime uses WAL constant |
| brain.toml | db.synchronous | db.connect | no | no; runtime uses NORMAL constant |
| brain.toml | db.foreign_keys | db.connect | no | no; runtime enables foreign keys unconditionally |
| brain.toml | backup.dir | paths.backups_dir | no | no; runtime uses `backups` |
| brain.toml | backup.include_db | none | no | no |
| brain.toml | backup.include_config | none | no | no |
| brain.toml | backup.include_constitution | none | no | no |
| brain.toml | backup.include_projects | none | no | no |
| brain.toml | git.categories | none | no | no |
| context.toml | schema_version | doctor.check_config (parse only) | parse | no |
| context.toml | governor.green_until_pct | none (PLANNED; monitor.py:164 uses hardcoded 50/80 boundaries) | no | no |
| context.toml | governor.yellow_until_pct | none (PLANNED) | no | no |
| context.toml | governor.orange_until_pct | none (PLANNED) | no | no |
| context.toml | governor.actions | none (PLANNED) | no | no |
| context.toml | read_ledger.track | working_set uses fixed JSON fields | no | no |
| context.toml | working_set.dir | paths/session_dir | no | no |
| context.toml | working_set.files | working_set uses fixed filenames | no | no |
| context.toml | capsule.min_update_interval_seconds | none | no | no |
| context.toml | rtd.enabled | Prime extension uses env gate `SECOND_BRAIN_RTD` only (INFORMATIONAL here) | no | no |
| context.toml | rtd.threshold_chars | rtd.parseThreshold: env `SECOND_BRAIN_RTD_THRESHOLD` (highest) -> this file -> default 8000 | yes: brainstem/prime-extension/tests/rtd.test.ts threshold-ladder tests | yes |
| context.toml | rtd.max_distill_chars | none (INFORMATIONAL) | no | no |
| context.toml | rtd.whitelist_tools | none (INFORMATIONAL; eligibility fixed in rtd.ts source constants) | no | no |
| context.toml | rtd.whitelist_commands | none (INFORMATIONAL; eligibility fixed in rtd.ts `RTD_COMMAND_PREFIXES`) | no | no |
| context.toml | reserve.task_execution_pct_min | none | no | no |
| context.toml | reserve.verification_reserve_pct | none | no | no |
| context.toml | reserve.retrieved_memory_pct_max | semantic.load_retrieval_config (retrieval token budget = pct of 200k context assumption) | yes: tests/test_retrieval_budget.py::test_retrieved_memory_pct_max_caps_token_budget | yes |
| context.toml | reserve.degrade_order | none | no | no |
| learning.toml | schema_version | doctor.check_config (parse only) | parse | no |
| learning.toml | modes.shadow | none | no | no |
| learning.toml | modes.advisory | none | no | no |
| learning.toml | modes.active | none | no | no |
| learning.toml | prediction_error.signals | none | no | no |
| learning.toml | hindsight.enabled | none | no | no |
| learning.toml | credit.levels | credit module constants | no | no |
| learning.toml | credit.only_strong_evidence_updates_utility | none | no | no |
| learning.toml | promotion.min_sessions | promotion does not load TOML | no | no |
| learning.toml | promotion.min_projects | promotion does not load TOML | no | no |
| learning.toml | promotion.prefer_multiple_models | promotion does not load TOML | no | no |
| learning.toml | promotion.require_no_unacceptable_regressions | promotion does not load TOML | no | no |
| retrieval.toml | schema_version | doctor.check_config (parse only) | parse | no |
| retrieval.toml | scoring.components | none (term on/off is the search_memories(score_terms=...) parameter; the TOML list is documented-only) | no | no |
| retrieval.toml | scoring.max_results | semantic.load_retrieval_config -> search_memories top_k (post-ranking result cap; default 3) | yes: tests/test_retrieval_budget.py::test_top_k_trims_to_highest_scoring_rows / test_retrieval_toml_weights_reorder_results | yes |
| retrieval.toml | scoring.log_all_components | none | no | no |
| retrieval.toml | scoring.weights.title_boost_exact | semantic.RetrievalWeights -> _relevance_score | yes: tests/test_retrieval_budget.py::test_retrieval_toml_weights_reorder_results (grade_scores; same loader) | yes |
| retrieval.toml | scoring.weights.title_boost_partial | semantic.RetrievalWeights -> _relevance_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.relevance_cap | semantic.RetrievalWeights -> _relevance_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.bm25_relevance_scale | semantic.RetrievalWeights -> _relevance_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.freshness_half_life_days | semantic.RetrievalWeights -> _freshness_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.freshness_max_penalty | semantic.RetrievalWeights -> _freshness_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.decision_boost_per_hit | semantic.RetrievalWeights -> _decision_value_score | yes (same loader; decision test restores rank order) | yes |
| retrieval.toml | scoring.weights.decision_boost_cap | semantic.RetrievalWeights -> _decision_value_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.negative_penalty_per_contradiction | semantic.RetrievalWeights -> _negative_transfer_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.negative_penalty_cap | semantic.RetrievalWeights -> _negative_transfer_score | yes (same loader) | yes |
| retrieval.toml | scoring.weights.token_free_limit | semantic.RetrievalWeights -> _token_cost_penalty | yes (same loader) | yes |
| retrieval.toml | scoring.weights.token_penalty_cap | semantic.RetrievalWeights -> _token_cost_penalty | yes (same loader) | yes |
| retrieval.toml | scoring.weights.token_penalty_saturation | semantic.RetrievalWeights -> _token_cost_penalty | yes (same loader) | yes |
| retrieval.toml | scoring.weights.grade_scores | semantic.RetrievalWeights -> _trust_score | yes: tests/test_retrieval_budget.py::test_retrieval_toml_weights_reorder_results (VERIFIED demoted -> TESTED reorders) | yes |
| retrieval.toml | scoring.weights.status_scores | semantic.RetrievalWeights -> _trust_score | yes (same loader) | yes |
| retrieval.toml | lateral_inhibition.deduplicate | none | no | no |
| retrieval.toml | lateral_inhibition.surface_contradictions | none | no | no |
| retrieval.toml | decay.states | reconsolidation constants | no | no |
| retrieval.toml | decay.protected | none | no | no |
| verification.toml | schema_version | doctor.check_config (parse only) | parse | no |
| verification.toml | ladder.LOW | none | no | no |
| verification.toml | ladder.MEDIUM | none | no | no |
| verification.toml | ladder.HIGH | none | no | no |
| verification.toml | ladder.CRITICAL | none | no | no |
| verification.toml | intent_verifier.fresh_context | none | no | no |
| verification.toml | intent_verifier.backward_reconstruction_first | none | no | no |
| verification.toml | requirement_ledger.statuses | working_set constants | no | no |
| verification.toml | requirement_ledger.material_unverified_blocks_completion | working_set._material_gate_blocks | yes: test_working_set.py::test_material_gate_config_wiring | yes |
| environment.toml | schema_version | doctor.check_config (parse only) | parse | no |
| environment.toml | track.session_start | envsteward does not load TOML | no | no |
| environment.toml | track.during | envsteward does not load TOML | no | no |
| environment.toml | track.shutdown | envsteward does not load TOML | no | no |
| environment.toml | process_ownership.fields | none | no | no |
| environment.toml | process_ownership.never_kill_ambiguous | none | no | no |
| skills.toml | schema_version | doctor.check_config (parse only) | parse | no |
| skills.toml | lifecycle.stages | skillforge constants | no | no |
| skills.toml | lifecycle.adoption | none | no | no |
| skills.toml | lifecycle.scopes | promotion/router constants | no | no |
| skills.toml | quality.required_sections | skillforge constants | no | no |
| skills.toml | gardener.sweep | none | no | no |
| skills.toml | router.max_active | router._router_max_active (per-call read; CLI `--max-active` overrides; invalid/absent -> 3) | yes: tests/test_router.py::test_router_max_active_honors_skills_toml / test_router_max_active_explicit_override_beats_config | yes |
| sleep.toml | schema_version | doctor.check_config (parse only) | parse | no |
| sleep.toml | engine.mode | CLI/manual implementation | no | no |
| sleep.toml | engine.conservative_pass | none | no | no |
| sleep.toml | engine.creative_dream_pass | none | no | no |
| sleep.toml | replay.priorities | sleep uses fixed priorities | no | no |
| sleep.toml | replay.interleave_older_cases | none | no | no |
| sleep.toml | dream.outputs_are_candidates_only | none | no | no |
| sleep.toml | dream.never_verified_facts | none | no | no |

## Scope decision

The campaign does not pretend these descriptive TOML values are executed
behavior. The operative gates are tested as shown (verification
material_unverified_blocks_completion; skills.toml router.max_active; now
context.toml rtd.threshold_chars). Retrieval claims are
narrowed to the current substring search until a separately reviewed scorer is
implemented and wired into an automatic ACTIVE path.
