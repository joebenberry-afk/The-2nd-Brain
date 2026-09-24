# Second Brain — master roadmap from v2.1 to v3

**Date:** 2026-09-09  
**Status:** Proposed implementation roadmap; every module starts NOT_STARTED.  
**Scope:** Transform the supplied research into separately shippable versions, not a one-shot campaign.  
**Product goal:** An evidence-backed incremental memory compiler that removes repeated discovery and computation while preserving correct, source-backed results.

> **Reader's note (2026-09-21).** This register links fourteen module documents
> (`modules/M00_*.md … M13_*.md`) and several companion files (`releases/00_ENTRY.md`,
> `docs/roadmap/second-brain-v3/`, the research inputs) that **exist nowhere in this
> repository**. That absence is recorded, not an oversight: `README.md` decision **D-4**
> declares them `NOT_YET_AUTHORED / SOURCE_UNAVAILABLE` and forbids reconstructing or inventing
> them, and the v3 roadmap remains the bounded operative source where that substitution was
> authorized. Twenty-one links in this file therefore lead nowhere *on purpose* — do not chase
> them, and do not read their targets as work that was lost.

## 1. What v3 is—and why it needs intermediate releases

V3 is the integrated system in which experience can become a reusable fact view, source-location map, cached computation, context projection, executable procedure or cheap selection policy. It uses one canonical authority and multiple rebuildable views. Its main model should spend effort on new uncertainty rather than repeatedly maintaining infrastructure or reconstructing known procedures.

This follows the supplied synthesis, especially §§3–10 and §16; it is not a claim that those mechanisms have already been built. The design combines incremental build systems, query optimization, memory views, procedure compilation, biological cue/replay inspiration and offline policy learning. **Implementation difficulty is not a rejection criterion.** Hardware feasibility, host/API access, correctness, and demonstrated lifetime value still determine whether a particular technique becomes a default. [SYN §§1–3, 14–16]

The version sequence exists because each layer needs the evidence and interfaces of the previous layer. A fast cache with wrong invalidation is dangerous. A context compiler without recovery can lose requirements. A learning loop over unreliable measurements can optimize the wrong behavior. None of those problems is solved by trying to code everything in one continuous run.

**Every minor release has a usable outcome. V3 is the qualification of their integration, not permission to start another rewrite.**

## 2. Release map

| Stage | Release theme | Modules | User-visible result |
|---|---|---|---|
| Entry | Qualify the actual v2 parent | M00 | One verified source/runtime/state baseline; unfinished v2 correctness is closed without expanding it into v3. |
| v2.1 | Fast and request-neutral runtime | M01, M02 | Ordinary no-benefit requests keep native-like latency and add no Brain model-facing tokens or management calls. |
| v2.2 | Incremental evidence and reusable computation | M03, M04 | Changed sources invalidate affected knowledge and results; unchanged valid work is reused instead of rediscovered. |
| v2.3 | Discoverable sources and intelligent retrieval | M05, M06 | The agent locates mappings, assets, dumps and project knowledge automatically, including naturally worded requests. |
| v2.4 | Compiled context and reliable continuity | M07 | Context is task-specific and deduplicated without losing details, obligations or recovery after compaction/restart. |
| v2.5 | Executable procedural memory | M08 | Validated recurring workflows run as checked programs, with model calls reserved for genuine semantic decisions. |
| v2.6 | Consolidation and offline policy learning | M09, M10 | Expensive experience and selective research produce reusable knowledge and cheap policies with demonstrated future savings. |
| v2.7 | Predictable resources and portable integration | M11, M12 | Workers share bounded resources and one memory authority; OMP plus a real second host use the same knowledge/procedures. |
| v3.0 | Qualified incremental memory compiler | M13 | All previous capabilities work together, preserve acknowledged history, and meet measured performance/quality/resource goals. |

Version labels denote planned `v2.1.0` through `v2.7.0` and `v3.0.0` releases. They do not create tags or certify that v2.0 has already been approved. Patch versions remain available for narrow repairs. A release candidate is a candidate, not a reason to mark production complete.

### Why this particular split

**2.1 is execution, not a new memory algorithm.** It establishes attributable measurements and removes the repeat-startup/no-op penalty. A reusable interpreter and a native implementation are compared rather than assuming either is best.

**2.2 makes reuse trustworthy.** It adds typed evidence/revisions, temporal distinctions and a dependency-aware computation graph. This is the basis for avoiding repeated work without stale results.

**2.3 makes knowledge findable.** It combines a source-capability catalogue with query-plan selection. It directly addresses the agent forgetting that mappings, assets or dumps are available. Local semantic retrieval receives a real comparative prototype; a particular model is not predetermined.

**2.4 governs what the model actually sees.** It chooses exact/structured/extracted/summary views, tracks recipient context epochs and provides recoverable compaction. It optimizes total work, including later page-ins, rather than just the first packet's size.

**2.5 turns remembered methods into computation.** A checked procedure can perform several deterministic operations without another model interpretation for each step. Its effects, dependencies and verification are explicit.

**2.6 converts expensive experience into cheap future decisions.** Selective consolidation creates candidates; offline optimization evaluates and distills policy choices. Both construction cost and useful reuse must be demonstrated.

**2.7 is integration and operational predictability.** Shared resource budgets, measured cache/prefetch choices and a real second-host proof complete the platform boundary. The core feature set freezes here.

**3.0 proves the whole system.** The final phase is cumulative evidence, interactions, migration, recovery and workload economics. It contains no new memory architecture.

## 3. Entry conditions: do not inherit an imaginary baseline

M00 must identify the actual repository, installed extension/runtime, canonical state, schema, active configuration and release evidence. The research inspected a historical snapshot, `6baea51b0be3ac7108ca6deafe5665ab8cca0852`; it did not establish the user's current installation. Prior reports about resumed-session schema failure or unfinished evidence must be checked against newer records, not automatically assumed current. [SYN §1]

Where v2 is already qualified, reuse its baseline and skip redundant repair. Where a real v2 defect remains, finish it through the existing closure scope. Do not introduce graph storage, embeddings or procedure compilation to close an unrelated ledger issue. M00's first packet is read-only; repairing or migrating live data needs a separately approved packet.

An isolated algorithm prototype can be researched while closure is pending. That does not authorize installing it or calling it v2.1. Production progression requires a trustworthy parent and a recovery route.

## 4. The implementation modules

Each module file contains a strong goal, existing-code integration points, proposed interfaces, four bounded work packets, adverse tests, a design decision, migration/rollback, measurements, exclusions and an evidence-based finish condition.

| Module | Target | Implementation responsibility | Technical prerequisites |
|---|---|---|---|
| [M00](modules/M00_baseline_closure_and_roadmap_admission.md) | ENTRY | Baseline closure and roadmap admission | Qualified-source discovery only |
| [M01](modules/M01_attributable_performance_and_correctness_laboratory.md) | 2.1 | Attributable performance and correctness laboratory | M00 |
| [M02](modules/M02_request_neutral_fast_runtime_and_lifecycle_broker.md) | 2.1 | Request-neutral fast runtime and lifecycle broker | M01 |
| [M03](modules/M03_versioned_evidence_objects_and_rebuildable_memory_views.md) | 2.2 | Versioned evidence objects and rebuildable memory views | M02 |
| [M04](modules/M04_incremental_memory_build_graph_and_safe_reuse.md) | 2.2 | Incremental memory build graph and safe reuse | M03 |
| [M05](modules/M05_source_capability_catalogue_and_prospective_cues.md) | 2.3 | Source capability catalogue and prospective cues | M04 |
| [M06](modules/M06_retrieval_query_planner_and_selective_semantic_operators.md) | 2.3 | Retrieval query planner and selective semantic operators | M05 |
| [M07](modules/M07_fidelity_aware_context_compiler_and_recipient_residency.md) | 2.4 | Fidelity-aware context compiler and recipient residency | M06 |
| [M08](modules/M08_typed_executable_procedural_memory.md) | 2.5 | Typed executable procedural memory | M07 |
| [M09](modules/M09_selective_consolidation_and_prospective_memory_learning.md) | 2.6 | Selective consolidation and prospective memory learning | M08 |
| [M10](modules/M10_offline_policy_optimization_and_cheap_deployed_selectors.md) | 2.6 | Offline policy optimization and cheap deployed selectors | M09 |
| [M11](modules/M11_resource_aware_scheduling_cache_policy_and_safe_prefetch.md) | 2.7 | Resource-aware scheduling cache policy and safe prefetch | M10 |
| [M12](modules/M12_portable_core_integration_and_dual_host_qualification.md) | 2.7 | Portable core integration and dual-host qualification | M11 |
| [M13](modules/M13_integrated_v3_acceptance_and_release_convergence.md) | 3.0 | Integrated v3 acceptance and release convergence | M12 |

There are **14 modules and 56 work packets**. A packet is a reviewable scope boundary, not an estimate of hours or a guarantee of one commit. Split an oversized packet further without expanding its release scope. Existing implementations can satisfy parts of a module after source and evidence verification; these plans do not require rebuilding a feature simply because it has a new module label.

## 5. Dependency graph and parallel work

```text
M00 baseline
  -> M01 measurement -> M02 fast runtime                         [2.1]
  -> M03 evidence -> M04 incremental graph                       [2.2]
  -> M05 sources/cues -> M06 retrieval planner                    [2.3]
  -> M07 context compiler                                       [2.4]
  -> M08 procedure compiler                                     [2.5]
  -> M09 consolidation -> M10 cheap learned policies             [2.6]
  -> M11 resources/cache/prefetch -> M12 host integration         [2.7]
  -> M13 cumulative qualification                               [3.0]
```

The graph is intentionally a conservative **integration order**. It does not mean research must be serialized. For example, after M01 establishes the measurement method, a worker may prototype a compact encoder while M02 is being implemented. After M03 defines evidence semantics, procedure-IR or context-fidelity fixtures can be designed against those contracts. Integration and live activation still wait for the declared dependencies and release approval.

Maintain one production release train and one owner for each mutating worktree/scope. Independent research uses isolated fixtures and explicit resource budgets. Do not spawn several writers into the same canonical state or run paid speculative campaigns merely because the roadmap lists them.

A second-harness capability audit begins at M00 and its contract is exercised from M02 onward. M12 is the final real-host integration proof, not the first time portability is considered. This prevents a late rewrite of the execution boundary.

## 6. The release cycle—repeat it, do not skip it

For each minor version:

1. **Read and bind:** pin the last accepted release plus actual installed state; read only the selected release/module and relevant contracts.
2. **Research and prototype:** compare the named alternatives on common fixtures; distinguish published claims from reproduced local behavior.
3. **Implement one packet:** test the chosen narrow slice, commit or preserve a bounded patch, and record exact evidence and remaining uncertainty.
4. **Integrate and qualify:** run affected regressions, required real-host tests and release-specific workload comparisons under shipping defaults.
5. **Promote deliberately:** approve/tag/deploy the candidate only after the owner accepts its receipt. Preserve a current-state-safe recovery route.
6. **Use and observe:** dogfood normal tasks and close regressions before activating the next release's behavior. A pass in an isolated fixture is not a substitute for required operational observation.

The owner controls progression. Finishing a packet does not authorize the next module or release. The execution prompt ends at a checkpoint with a proposed next packet. Tests and independent review are sized to changed dependencies and risk, not repeated ceremonial full audits of unchanged evidence.

## 7. What is mandatory versus what is a research choice

### Required capability spine

The following outcomes define v3: a real fast/no-op execution path; evidence/revision-aware reuse; automatic source discovery and useful retrieval; fidelity-aware context with correct recovery; executable recurring procedures; selective consolidation plus a genuinely beneficial cheap learned policy; resource-bounded operation; and actual portable core behavior in OMP plus a second host.

A mechanism may be replaced by a superior approach that satisfies the same interface and evidence contract. For example, the dependency engine may be Salsa-inspired or a purpose-built DAG. But it must actually support safe incremental reuse. Calling a proposed design “too difficult” is not a reason to omit the capability.

### Mandatory comparison, conditional production selection

The reused-interpreter/native fast-path comparison and local semantic-retrieval comparison must be performed. They are not just optional reading assignments. The exact native binding, encoder, index and ranking implementation ship only after their measured trade-offs are known. A native prototype losing to a reused interpreter is a valid research result, provided the winner satisfies the required budgets.

Similarly, compare context representations, procedure execution against strong native tooling, and consolidation/learning against fixed policies. A named paper's algorithm is not a requirement to import its entire stack.

### Parallel frontier research

The experimental track file preserves learned compression, richer multi-vector/graph operators, alternative compiled bindings, aggressive speculative reads, model-internal neural memory, local serving/KV reuse and heavyweight learned memory policies. None is rejected for implementation effort. Each has a specific experiment and hardware/API boundary. Their success may join the appropriate version when it does not disrupt the release, or a later extension after v3.

**Optional research can fail without blocking v3. A missing required core outcome cannot be relabeled optional to make v3 pass.** Neural model-internal memory is not required for a portable external memory compiler. [SYN §§11–12, 15–16]

## 8. Performance and quality trajectory

The inherited proposed no-op contract is strict: no Brain-added model-visible message, tool schema, status wrapper or extra model call on a genuinely irrelevant fresh request. Retained context from an earlier useful turn is accounted separately. Cached tokens are not zero tokens. [CHARTER §2]

For 2.1, retain the proposed **<=10 ms median / <=50 ms p95 warm whole-turn local overhead**, with **<=100 ms p95 incremental cold time to first dispatch** as a separate target. These are proposals to freeze before evaluation, not claims of current performance. Live provider time needs paired uncertainty and a predeclared parity margin; it is not controlled by local code alone. [CHARTER §3]

Every later release must keep the accepted no-op contract and measure its full contribution, not grant itself another 50 ms per component. Gains on long tasks cannot average away simple-task regressions.

For useful-memory work, aim for reductions in **total tokens and time through verified completion**, after including preparation, workers, retries, background learning, cache validation and future recovery. No universal percentage improvement is promised. Each capability's target population, comparison, material improvement threshold and correctness non-inferiority margin are frozen by M01 and the owning experiment before its holdout is inspected.

The first rollout of a useful operator can add context while still reducing total work. Zero gross injection is mandatory only for the genuine no-benefit path. A pointer is not free knowledge: expansion costs count.

The full method is in [02_MEASUREMENT_AND_ACCEPTANCE.md](02_MEASUREMENT_AND_ACCEPTANCE.md). Any source-freshness, wrong-project, permission, acknowledged-state or material-requirement failure is a hard rejection in the relevant acceptance suite. Observing zero failures does not prove zero probability in all future use.

## 9. Compatibility and incremental migration

Keep public 2.x APIs, CLI behavior and stored knowledge compatible while moving internals behind stable facades. Introduce a proposed `FastDecision`/snapshot boundary in 2.1; extend canonical object/view semantics in 2.2; add planner/projection/procedure interfaces subsequently. Avoid requiring a new giant schema for the first fast-path experiment.

Use expand → isolated backfill/rebuild → shadow comparison → one-owner cutover → retire duplicate internals. Derived snapshots are not independent sources of truth. Unknown legacy provenance remains unknown; it must not be fabricated during migration.

A rollback must preserve the most recently acknowledged work. Restoring an old database blindly can lose everything written since that backup. Where an old binary cannot safely read the current schema, use a validated compatible export or forward repair. Do not claim a destructive downgrade is a successful recovery.

Only v3 may remove an explicitly deprecated public interface, and only with migration/compatibility evidence. The detailed security/migration plan is [03_MIGRATION_SECURITY_AND_ROLLBACK.md](03_MIGRATION_SECURITY_AND_ROLLBACK.md).

## 10. Finite v3 acceptance boundary

V3.0.0 is eligible only when all of the following are evidenced in the actual shipping configuration:

- **No-op economics:** exact request neutrality and accepted local/cold budgets, with useful-recall negative controls and matched live-host parity.
- **Valid reuse:** source, corpus-membership, environment and permission changes invalidate affected results; uncertainty reconciles safely; useful unchanged work is measurably reused.
- **Findable knowledge:** automatic discovery and actual inspection of approved domain sources, including a real mapping/dump use case and held-out natural wording.
- **Context continuity:** recipient-specific deduplication, required fidelity, durable coverage-before-reclaim and actual compaction/restart/worker recovery.
- **Executable experience:** the three declared procedure families operate under effect/permission contracts and demonstrate fewer avoidable coordination calls against a strong native control.
- **Useful learning:** selected consolidation repays its costs; at least one evidence-backed cheap policy produces real benefit and is promoted; harmful/stale alternatives are refused or reversed.
- **Portable operation:** OMP full profile and one real second host share the same source authority, task/procedure semantics, isolation and recovery, with unsupported capabilities explicitly declared.
- **Release integrity:** cumulative and interaction tests, upgrade/recovery rehearsal, resource bounds on the actual 16 GB machine, resolved critical findings, and owner approval.

M13 checks these outcomes; it does not invent new ones. All experimental tracks receive a disposition—promoted, rejected, continuing research or hardware/API blocked. No automatic v2.8, v2.9 or “one more prerequisite subsystem” is introduced. A genuine newly discovered blocker is repaired as a bounded dependency change, with the effect on the finish line made explicit.

This is a milestone roadmap, not a calendar promise. Calendar estimates should come from M00's actual code delta and the first measured packets. Difficulty affects scheduling and decomposition, not whether a valuable technique is considered.

## 11. Immediate next step

Authorize **M00.1 only** using [FIRST_SESSION_PROMPT.md](FIRST_SESSION_PROMPT.md). Its output is a read-only entry report: actual baseline, unresolved obligations, contract map, evidence that can be reused, and the exact next bounded packet. It performs no live migration or feature activation.

After baseline admission, begin M01 rather than installing all research techniques at once. The first practical win is a request-neutral runtime; each subsequent release adds a durable piece of the v3 architecture.

## Sources and status of claims

**[SYN]** [Supplied architecture research dossier](research/input_architecture_research.md), especially §§1, 3–16. Preserved as planning input; published results and historical project reports are not newly reproduced here.  
**[CHARTER]** [Supplied performance charter](research/input_performance_charter.md), §§2–7. Numerical budgets remain proposed acceptance targets.  
**[SRC]** [Preserved 61-source register](research/input_source_register.json); the [implementation map](04_RESEARCH_TO_IMPLEMENTATION_MAP.md) assigns every source to a module or experimental track. Owners verify relevant primary-source versions before building a dependency on them.
