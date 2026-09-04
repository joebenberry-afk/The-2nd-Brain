# Second Brain v2.0 Repository-True Implementation Plan

> Reconciled from commit `05bea1e` on 2026-09-04. Repository code, migrations, and verified P0-P6 behavior outrank the legacy ownership sketch.

## Goal

Complete the local-first Cortex + Brainstem v2 campaign without creating parallel owners, duplicate tables, a second database, or adapter-owned canonical state. New adaptive behavior remains OFF or SHADOW until current evidence satisfies the existing promotion boundary.

## Invariants

- Keep one canonical Brain database and the repository's current module boundaries.
- Reuse P0-P6 implementations; extend them only where a phase below names a remaining contract.
- Preserve constitutional and user-authored authority. Learned state begins as candidate or limited-authority state.
- Missing provider measurements remain `null` with provenance; never synthesize zeroes.
- Stale, tampered, incomplete, cross-project, or unsafe evidence fails closed for mutation and promotion.
- Every persistent addition is deterministic, idempotent, backup/restore-safe, doctor-visible, and independently verifiable.
- Core correctness remains local-first and does not require a hosted vector store, hosted embedding service, GPU, daemon, or premium model.

## P0-P6 inheritance: do not recreate

| Existing capability | Repository-true owner | Plan treatment |
|---|---|---|
| Semantic memory, evidence, authority, freshness inputs, versions, and strength/stability | `semantic.py`, `freshness.py`, `memories` | Extend in place; no second memory domain. |
| Lexical/hybrid retrieval, budgets, deterministic ordering, and abstention | `hybrid_retrieval.py`, `semantic.py` | Extend the existing cascade; no parallel retriever. |
| Reconsolidation and useful-use activation history | `reconsolidation.py`, `memory_activations` | Reuse the activation ledger; do not add utility/meta mirrors. |
| Decision provenance, rollout stage, choices, and outcomes | `decisions.py`, `decisions` | Append decision kinds/fields only when the existing schema cannot represent the retained contract. |
| Canonical packets, hashes, handoff envelopes, worker lifecycle, and leases | `contracts.py`, `handoff.py`, `worker_protocol.py`, `worker_tasks` | Reuse canonical serialization and worker state. |
| Harness capability evidence | `capabilities.py`, `harness_capabilities` | Extend capability vocabulary in place. |
| Credit, engrams, cross-model profiles, frontier review, and promotion | `credit.py`, `engram.py`, `crossmodel.py`, `frontier.py`, `promotion.py` | Extend the current governed lifecycle. |
| V2 configuration and qualification baseline | `v2_policy.py`, `config/v2.toml`, `scripts/verify_v1_p4_qualification.py` | Keep policy; evolve the verifier rather than adding a second verification library. |
| Low-friction CLI/adapters, telemetry, action cache, and context controls | `cli.py`, adapters, `telemetry.py`, `action_cache.py`, `autoinject.py` | Treat P0-P6 behavior as the V2-B' base. |

## Historical module reconciliation

These rows are historical mappings, not implementation proposals.

| Legacy owner | Action | Repository-true owner / reason |
|---|---|---|
| `src/second_brain/v2_common.py` | FOLD | `contracts.py`, `v2_policy.py`, and `db.py` already own canonical JSON/hashes, rollout policy, and migration execution. |
| `src/second_brain/v2_policy.py` | KEEP | Existing strict `config/v2.toml` loader and rollout vocabulary. |
| `src/second_brain/v2_reports.py` | DELETE_FROM_PLAN | Qualification/report artifacts are outputs of phase commands and the independent verifier; no runtime report owner is needed. |
| `src/second_brain/admission.py` | FOLD | Earned-memory functions belong in `semantic.py`. |
| `src/second_brain/meta_memory.py` | FOLD | Utility, lineage, and strategic forgetting belong in `reconsolidation.py`. |
| `src/second_brain/retrieval_v2.py` | FOLD | Retrieval 2.0 extends `hybrid_retrieval.py`. |
| `src/second_brain/brainstem.py` | KEEP | Approved by T7.4 as the new attention/budget/intervention coordinator. |
| `src/second_brain/control_plane.py` | FOLD | Packet contracts belong in `contracts.py`; observed capability state belongs in `capabilities.py`. |
| `src/second_brain/learning.py` | FOLD | Causal credit and intervention decisions belong in `credit.py` and `decisions.py`. |
| `src/second_brain/culture.py` | FOLD | Workflow engrams and measured transfer/profile behavior belong in `engram.py` and `crossmodel.py`. |
| `src/second_brain/knowledge_frontier.py` | FOLD | Frontier items and evidence updates extend `frontier.py`. |
| `src/second_brain/rollout.py` | FOLD | Stage transition, promotion, demotion, and rollback evidence extend `promotion.py`. |
| `src/second_brain/v2_verifier.py` | FOLD | Extend `scripts/verify_v1_p4_qualification.py` into `scripts/verify_qualification.py`; keep verification independent and read-only. |
| `src/second_brain/v2_cli.py` | FOLD | Add the `v2` command group directly to `cli.py`. |
| `scripts/verify_v2_qualification.py` | FOLD | One cutover verifier is `scripts/verify_qualification.py`, evolved from the existing P4 verifier. |
| `scripts/benchmark_v2.py` | DELETE_FROM_PLAN | Use existing telemetry and paired-economics runners; add a bounded scenario only if a named proof cannot be derived there. |

## Database reconciliation

The complete retained v2 table set is exactly:

1. `v2_candidates`
2. `v2_interventions`
3. `v2_observations`
4. `v2_frontier_items`
5. `v2_rollout_events`
6. `v2_qualification`

No other `v2_*` table is authorized by this plan. Add the six tables through the next repository migration numbers at implementation time; do not reuse the legacy migration numbers now occupied by P0-P6 work.

| Legacy table | Action | Repository-true owner / reason |
|---|---|---|
| `v2_candidates` | KEEP | New bounded earned-memory candidate state. |
| `v2_memory_meta` | DELETE_FROM_PLAN | `memories` already owns memory lifecycle, strength, stability, scope, and verification state. |
| `v2_memory_utility` | DELETE_FROM_PLAN | `memory_activations` already owns useful-use and outcome observations. |
| `v2_memory_lineage` | DELETE_FROM_PLAN | `memories` plus semantic version/history records already own supersession and lineage. |
| `v2_retrieval_outcomes` | DELETE_FROM_PLAN | `memory_activations` owns use feedback and `decisions` owns selection/outcome provenance. |
| `v2_brainstem_decisions` | DELETE_FROM_PLAN | `decisions` owns bounded decisions/outcomes; `worker_tasks` owns execution lifecycle. |
| `v2_interventions` | KEEP | New immutable prediction/intervention state. |
| `v2_observations` | KEEP | New immutable observed-result and prediction-error state. |
| `v2_engrams` | DELETE_FROM_PLAN | `engram.py` and canonical memory/artifact records own versioned engrams; no duplicate DB authority. |
| `v2_profile_observations` | DELETE_FROM_PLAN | `crossmodel.py` and the existing `model_profiles` state own measured model/harness profiles. |
| `v2_capabilities` | DELETE_FROM_PLAN | `harness_capabilities` already owns observed harness support and evidence. |
| `v2_frontier_items` | KEEP | New structured active-learning frontier state. |
| `v2_rollout_events` | KEEP | New append-only feature-stage transition evidence. |
| `v2_qualification` | KEEP | New immutable phase/requirement qualification ledger. |

## Phase 1 — V2-0

**Owners:** `v2_policy.py`, `config/v2.toml`, current migrations, existing evidence commands, and the qualification verifier cutover.

**Already satisfied by P0-P6:** isolated worktree practice; one Brain database; strict SHADOW/OFF policy defaults; canonical JSON and hashes; migration runner; doctor, backup/restore, telemetry, decisions, and P4 qualification foundations.

**Remaining work:**

- Capture a current baseline manifest containing source identity, tree state, runtime/dependency identities, enabled harnesses/features, schema fingerprint, nullable measurements, and exact gate evidence references.
- Introduce only the six retained tables using unoccupied migration versions, with fresh/reopen/repeat/backup/restore proof.
- Record unavailable metrics as `{ "value": null, "source": "..." }`.
- Do not tag v2 until every later phase is independently qualified.

**Gate:** baseline identity and schema are reproducible; no duplicate table or migration owner exists.

## Phase 2 — V2-A' Trusted Retrieval/Freshness

**Owners:** `semantic.py`, `freshness.py`, `hybrid_retrieval.py`, existing repository fingerprints, and `decisions.py`.

**Already satisfied by P0-P6:** FTS/hybrid fallback, deterministic scoring and budgets, evidence grades, authority ceilings, contradiction signals, repository freshness checks, abstention, and decision provenance.

**Remaining work:** close only measured gaps in stale repository-fact invalidation, authority protection, project transfer, diverse top-k, contradiction surfacing, deterministic ties, and no-use abstention. Any new signal must flow through current retrieval result and decision contracts.

**Gate:** trusted/fresh retrieval beats or safely abstains against the recorded V2-0 baseline without changing v1-safe defaults.

## Phase 3 — V2-B' Low-Friction I/O

**Owners:** `cli.py`, existing adapters, `autoinject.py`, `action_cache.py`, `telemetry.py`, `handoff.py`, and context/working-set owners.

**Already satisfied by P0-P6:** adapter bridges, bounded context injection, action-cache dependency proofs, session/handoff envelopes, telemetry validation, CLI JSON conventions, and conservative missing-capability behavior.

**Remaining work:** expose only the missing low-friction `v2` inspection/qualification operations in `cli.py`; reuse existing adapter and packet boundaries. No adapter may own canonical memory, policy, engram, frontier, or causal truth.

**Gate:** equivalent operations work through the current CLI and real supported harness paths without transcript replay or a second command module.

## Phase 4 — Earned Memory

**Owner:** `semantic.py`; persistence: `v2_candidates` plus existing `memories`.

**Already satisfied by P0-P6:** semantic validation, evidence provenance, origin authority, duplicate detection, contradiction preservation, lifecycle state, and immutable version history.

**Remaining work:** add bounded candidate submission, friction/evidence scoring, deterministic dedupe, authority ceilings, and OFF/SHADOW/ACTIVE admission gates as functions in the existing semantic owner. Only ACTIVE admission may call the existing semantic-memory mutation path.

**Gate:** repeated regressions can earn a candidate; duplicate facts dedupe; conflicting facts remain distinct; severe scoped facts are retained; protected authority cannot be escalated; OFF writes nothing and SHADOW never creates a semantic memory.

## Phase 5 — Meta-Memory

**Owner:** `reconsolidation.py`; persistence: `memory_activations` and `memories`.

**Already satisfied by P0-P6:** activation recording, strength/stability fields, reconsolidation actions, history, supersession, and guarded forgetting.

**Remaining work:** aggregate explicit used/success/verified signals into bounded strength/stability updates; retrieval or injection alone cannot strengthen memory. Keep the complete evidence-preserving action set in `reconsolidation.py`: narrow, update, split, merge, supersede, demote, archive, and leave-unresolved. Every relationship retains lineage and evidence refs rather than overwriting history; extend existing explanation behavior rather than adding storage mirrors.

**Gate:** unused retrieval cannot self-reinforce; useful evidence can strengthen; verified/protected memory cannot be silently downgraded. Narrow/update/split/merge/supersede/demote/archive/leave-unresolved all preserve evidence and lineage. Archived memories remain discoverable in history/explanation but are excluded from default retrieval.

## Phase 6 — Retrieval 2.0

**Owner:** `hybrid_retrieval.py`, with `semantic.py` and `reconsolidation.py` inputs; decision evidence in `decisions` and use feedback in `memory_activations`.

**Already satisfied by P0-P6:** exact/lexical/hybrid candidates, explicit score components, hard filters, contradiction attachment, deterministic ordering, token limits, and fallback behavior.

**Remaining work:** add utility, stability, task similarity, scope transfer, redundancy/diversity, and attributable outcome inputs to the current cascade. Keep stable `(score desc, authority desc, memory_id asc)` ordering and record omitted reasons without a new outcomes table.

**Gate:** bounded explanations reproduce selection; stale/unsafe candidates fail closed; diverse useful results fit the budget; no useful result yields zero memory injection.

## Phase 7 — Brainstem

**Owner:** new approved `brainstem.py`; integrations remain with `governor.py`, model routing, `jit.py`, `capabilities.py`, `decisions.py`, and `worker_protocol.py`.

**Already satisfied by P0-P6:** task signals, token/provider/cache budgets, capability tiers, deterministic model routing, worker leases, verification policy, and bounded context primitives.

**Remaining work:** coordinate task classification, attention budgets, intervention selection, safe fallback, isolated scout choice, and context compilation without absorbing those owners. Persist durable choices in `decisions`; keep execution lifecycle in `worker_tasks`.

**Gate:** deterministic replay matches; budgets never exceed limits; unavailable capability/quota data degrades conservatively; context order is protected refs, task evidence, verified decisions, selected memories, then optional procedures.

## Phase 8 — Causal Learning

**Owners:** `credit.py` and `decisions.py`; retained persistence: `v2_interventions` and `v2_observations`.

**Already satisfied by P0-P6:** immutable decision inputs, outcomes/rewards, credit classes, evidence validation, and candidate-only adaptive boundaries.

**Remaining work:** require a baseline/counterfactual, expected metric direction/range, horizon, confidence, evaluator, and evidence refs. Preserve predicted/observed payloads, compute bounded prediction error/surprise, and assign only the repository credit classes `DIRECT`, `CONTRIBUTORY`, `CORRELATED`, or `UNRELATED_NEGATIVE`. Produce inert candidates only; correlation alone is explicitly non-promotable.

**Gate:** controlled positive and negative cases assign the four credit classes correctly; `CORRELATED` evidence alone cannot satisfy promotion; tampered/stale evidence is ineligible; predictable outcomes do not trigger reflection; no observation directly activates a change.

## Phase 9 — Engrams/Culture

**Owners:** `engram.py` and `crossmodel.py`; canonical artifacts remain under existing engram/memory stores.

**Already satisfied by P0-P6:** candidate engrams, bounded skill references, cross-model profiles, transfer checks, routing evidence, and governed promotion.

**Remaining work:** detect repeated workflows, build bounded versioned candidates, evaluate teacher/student execution against a baseline, record measured model/harness compatibility, and respect quotas. Reuse existing profile and artifact ownership; do not add a DB mirror.

**Gate:** candidates require support and evidence; incompatible transfers refuse; profile fields remain measured or null; routing cannot promote an engram.

## Phase 10 — Universal Control Plane

**Owners:** `contracts.py` and `capabilities.py`; bridges in `handoff.py`, `worker_protocol.py`, and existing adapters.

**Already satisfied by P0-P6:** canonical JSON/hashing, bounded handoff envelopes, task/result packet primitives, harness capability observations, worker state/leases, and adapter translation boundaries.

**Remaining work:** extend the current versioned task/result contracts only for genuinely missing v2 fields; negotiate from observed capabilities; reject unknown schema versions, identities, oversized fields, false capabilities, and transcript payloads. Exercise real installed-host entrypoints rather than test-only adapters; record an honest unavailable-host result when a required host is not installed and never substitute a mock.

**Gate:** a real rich-capability harness to limited-capability harness handoff, and the reverse direction, preserve canonically equivalent decisions/evidence/unresolved work through installed-host entrypoints. False capabilities are rejected, unavailable hosts are reported as unavailable, no mock stands in for a host, and no adapter owns canonical state.

## Phase 11 — Frontier

**Owner:** `frontier.py`; retained persistence: `v2_frontier_items`.

**Already satisfied by P0-P6:** manual review, evidence binding, frontier status, promotion linkage, and local experiment/economics primitives.

**Remaining work:** add bounded structured unknowns, evidence for/against, expiry, confidence, candidate experiments, and deterministic information-gain/cost/risk ranking to the current frontier owner. Prefer existing telemetry, deterministic inspection, local experiments, cheap models, then premium work unless risk requires escalation.

**Gate:** stale evidence cannot authorize an experiment or promotion; deterministic ties are stable; risky/expensive low-information experiments are refused.

## Phase 12 — Self-Improvement Proof

**Owners:** `promotion.py`, `frontier.py`, existing rollback/immune owners, `scripts/verify_qualification.py`; retained persistence: `v2_rollout_events` and `v2_qualification`.

**Already satisfied by P0-P6:** evidence-gated promotion/demotion, frontier approval, rollback/immune records, telemetry, backup/restore, and the existing independent P4 verifier.

**Remaining work:** rename and extend the existing verifier as the single read-only qualification entry point. Derive checks independently from files/database; validate artifact hashes, source commit, migration/schema, phase gates, economics, privacy, recovery, successful promotion, refusal, and rollback. Use existing telemetry and paired-economics runners for representative scale/performance measurements. Run an event-count burn-in spanning restart/reopen, compaction and handoff, contradiction handling, adaptive decisions, and intervention outcomes. Append rollout and qualification evidence; never let a report authorize its own promotion.

**Gate:** every phase has current evidence; a real governed improvement promotes only when all guards pass; a failed guard refuses or rolls back. Current representative scale/performance results and the complete event-count burn-in are mandatory, together with recovery, security, and economics checks, before any v2 tag.

## Mechanical completion checks

- The twelve phase headings above appear once and in the declared order.
- The historical module table classifies every legacy implementation module/script as `KEEP`, `FOLD`, or `DELETE_FROM_PLAN`.
- The historical table table classifies all fourteen legacy table proposals.
- The only retained v2 tables are the six enumerated under Database reconciliation.
- Folded legacy paths occur only in the clearly labeled historical reconciliation table and are never creation or modification targets.
- No implementation task creates a competing retrieval, meta-memory, control-plane, learning, culture, frontier, rollout, verifier-library, or CLI module.
