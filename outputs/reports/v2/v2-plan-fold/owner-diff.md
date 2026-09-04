# V2 plan ownership diff

Source: legacy plan at commit `05bea1e`. Rule: `KEEP` retains the named owner; `FOLD` moves the contract into an existing owner; `DELETE_FROM_PLAN` removes duplicate or unnecessary ownership. These are historical mappings, not new-module proposals.

## Modules and scripts

| Old owner | Class | Repository-true owner / reason |
|---|---|---|
| `src/second_brain/v2_common.py` | FOLD | `contracts.py` + `v2_policy.py` + `db.py`: canonical serialization/hashes, rollout policy, and migrations already exist. |
| `src/second_brain/v2_policy.py` | KEEP | Existing strict loader for `config/v2.toml`. |
| `src/second_brain/v2_reports.py` | DELETE_FROM_PLAN | Reports are verifier/phase outputs; no runtime report module is needed. |
| `src/second_brain/admission.py` | FOLD | `semantic.py` functions own earned-memory admission. |
| `src/second_brain/meta_memory.py` | FOLD | `reconsolidation.py` owns utility, lineage, and strategic forgetting. |
| `src/second_brain/retrieval_v2.py` | FOLD | `hybrid_retrieval.py` owns Retrieval 2.0. |
| `src/second_brain/brainstem.py` | KEEP | T7.4-approved new attention/budget/intervention coordinator. |
| `src/second_brain/control_plane.py` | FOLD | `contracts.py` owns packets; `capabilities.py` owns capability evidence. |
| `src/second_brain/learning.py` | FOLD | `credit.py` + `decisions.py` own causal credit and intervention decisions. |
| `src/second_brain/culture.py` | FOLD | `engram.py` + `crossmodel.py` own engrams and measured transfer/profile behavior. |
| `src/second_brain/knowledge_frontier.py` | FOLD | `frontier.py` owns frontier items and evidence updates. |
| `src/second_brain/rollout.py` | FOLD | `promotion.py` owns promotion, demotion, stage transitions, and rollback evidence. |
| `src/second_brain/v2_verifier.py` | FOLD | Extend `scripts/verify_v1_p4_qualification.py` into the single `scripts/verify_qualification.py`; no verifier library. |
| `src/second_brain/v2_cli.py` | FOLD | `cli.py` owns the `v2` command group. |
| `scripts/verify_v2_qualification.py` | FOLD | Same single-verifier cutover to `scripts/verify_qualification.py`. |
| `scripts/benchmark_v2.py` | DELETE_FROM_PLAN | Existing telemetry and paired-economics runners own measurement; add only a missing bounded scenario there. |

All 16 legacy implementation module/script proposals are classified: 2 `KEEP`, 12 `FOLD`, 2 `DELETE_FROM_PLAN`.

## Database tables

| Old table | Class | Repository-true owner / reason |
|---|---|---|
| `v2_candidates` | KEEP | Retained earned-memory candidate state. |
| `v2_memory_meta` | DELETE_FROM_PLAN | `memories` owns lifecycle, strength, stability, scope, and verification. |
| `v2_memory_utility` | DELETE_FROM_PLAN | `memory_activations` owns useful-use/outcome observations. |
| `v2_memory_lineage` | DELETE_FROM_PLAN | `memories` and semantic history own supersession/lineage. |
| `v2_retrieval_outcomes` | DELETE_FROM_PLAN | `memory_activations` owns use feedback; `decisions` owns selection/outcome provenance. |
| `v2_brainstem_decisions` | DELETE_FROM_PLAN | `decisions` owns choices/outcomes; `worker_tasks` owns execution lifecycle. |
| `v2_interventions` | KEEP | Retained immutable intervention/prediction state. |
| `v2_observations` | KEEP | Retained observed-result/prediction-error state. |
| `v2_engrams` | DELETE_FROM_PLAN | `engram.py` and canonical memory/artifact records own versioned engrams. |
| `v2_profile_observations` | DELETE_FROM_PLAN | `crossmodel.py` and existing `model_profiles` own measured profiles. |
| `v2_capabilities` | DELETE_FROM_PLAN | `harness_capabilities` owns observed harness support/evidence. |
| `v2_frontier_items` | KEEP | Retained structured frontier state. |
| `v2_rollout_events` | KEEP | Retained append-only feature-stage evidence. |
| `v2_qualification` | KEEP | Retained immutable phase/requirement qualification ledger. |

All 14 legacy table proposals are classified: 6 `KEEP`, 0 `FOLD`, 8 `DELETE_FROM_PLAN`. The retained set is exactly `v2_candidates`, `v2_interventions`, `v2_observations`, `v2_frontier_items`, `v2_rollout_events`, and `v2_qualification`.
