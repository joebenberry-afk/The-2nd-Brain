# Second Brain v3 — Orchestration-Free Roadmap

**Date:** 2026-09-23  
**Product boundary:** Harness-independent memory, context, knowledge, skills, and safe reuse. No Brain agent orchestrator.  
**Status:** Active candidate roadmap under the September 23 removal mandate; implementation and qualification are tracked separately in `M00-CAMPAIGN-REGISTER.md`. No production authorization.

## 1. Product goal

Make Second Brain inexpensive when it cannot help, and demonstrably useful when memory, knowledge, context, or procedural reuse can reduce repeated work.

The native harness decides who does work, which model is used, which tools may run, and when execution starts, stops, retries, or completes. Brain supplies the right permitted knowledge and preserves trustworthy memory. It does not own the task lifecycle.

Automatic context injection remains. Multiple agents can use one authorized knowledge base. Skills can become more discoverable, precise, reusable, and verifiable. None of those capabilities requires Brain to create agents, appoint a coordinator, or control their tools.

## 2. Architectural ownership

| Responsibility | Owner after removal |
|---|---|
| Agent creation, delegation, queues, retries, cancellation, completion | Native harness |
| Model/provider choice and agent-role configuration | User/native harness |
| Native tool permissions and execution isolation | Native harness and its supported security boundary |
| Canonical memory, retrieval, source knowledge, provenance | Brain |
| Context construction, injection, compaction continuity | Brain through a narrow host adapter |
| Skill discovery, approved content, recipes, provenance | Brain; execution remains with the host |
| Authorization for retained Brain data and privileged operations | Brain's retained permission/approval boundary |
| Usage/cost records | Brain may observe and aggregate supported evidence; it does not admit tasks |
| Index/cache/context/storage/local-compute limits | Brain for its own operations only |
| Host API differences | Thin compatibility adapters, not version-specific core behavior |

Correlation identifiers do not become privileged authority merely because they appear in a native event. Unknown usage and unknown provenance remain unknown. Core data integrity and approved-byte consumption are not removed with worker governance.

## 3. Explicit exclusions from all v3 plans

Remove coordinator recognition and custody improvements; protected worker issuance; driver/worker planes; agent or model routing; task admission; worker budget reservations; execution leases; completion/settlement/replay authority; native lifecycle supervision; agent scheduling/prefetch; worker recovery/resurrection; delegated coordinator hierarchies; and a multi-agent runtime.

Remove improvements to an orchestration handoff layer whose sole purpose is retaining those guarantees. Do not recreate them as a Brainstem executive, workflow engine, autonomous supervisor, resource governor, or cognitive operating system. Names do not change scope.

Preserve source/data lineage, memory authorization, and concurrent memory access even where their implementation previously shared files with orchestration. Retire the old feature, not unrelated data protections.

## 4. Development stages

The M00–M13 labels below map to the retrieved September 9 master roadmap. Later local plans may have reassigned responsibilities, especially M11/M12. Reconcile by capability against the actual active roadmap; preserve a documented mapping instead of silently renumbering history. These are modular increments, not a demand to create a tag for every stage.

### Stage 0 — Remove the redundant controller (M00 scope replacement)

Execute the accompanying removal mandate. Fix test-home isolation first. Remove both runtime and test-only governed behavior, retire obsolete tests and requirements, preserve applicable core protections, and independently review one frozen candidate.

**Finish:** One finite removal gate. No pending orchestration support commitment. No live activation implied.

### Stage 1 — Measurement and genuinely cheap runtime (M01, M02)

Capture native and Brain-enabled model-facing requests, full-turn timing, imports/startup, retrieval, injection, finalization, and resource usage. Keep native model and task settings matched so a model change cannot masquerade as a Brain improvement.

Implement the earliest useful local no-op decision, lazy initialization, bounded configuration reuse, and elimination of avoidable bridge/process work. A lifecycle component may manage Brain's own request processing or local resources; it may not become a native task/agent supervisor.

**Finish:** Controlled no-benefit requests add no Brain model-visible content or management calls and meet accepted local overhead budgets. Useful-memory negative controls establish that fast abstention did not simply stop recalling required knowledge.

### Stage 2 — Evidence-aware memory and safe reuse (M03, M04)

Represent source identity, revision, project scope, provenance, permissions, and freshness explicitly. Maintain one canonical memory authority with rebuildable views. Track dependencies so changed inputs invalidate affected derived knowledge and cached results without rebuilding everything.

A memory dependency graph describes evidence and derived data, not a distributed agent execution plan. Cache validation must cost less than the repeated work it avoids on the target workload.

**Finish:** Source, permission, corpus-membership, and relevant environment changes invalidate correctly; unchanged useful work is reused; acknowledged history survives interruption and upgrade.

### Stage 3 — Source discovery and precise retrieval (M05, M06)

Catalogue approved repositories, documents, mappings, assets, dumps, and existing project knowledge. Make their locations and useful access methods discoverable through natural requests. Compare suitable lexical, structural, and semantic retrieval operators using held-out project queries.

Discovery runs through permitted local indexing, ordinary host hooks, or explicitly invoked maintenance. Do not spawn Brain scout agents or add a discovery orchestrator.

**Finish:** Real domain tasks find and inspect the right permitted source; missing/stale/uncertain sources are reported honestly; wrong-project material is excluded; retrieval cost is measured.

### Stage 4 — Better context and durable continuity (M07)

Choose task-relevant exact, structured, extracted, or summarized views. Deduplicate within the actual recipient context without assuming that one agent's delivery reached every agent. Preserve required facts, constraints, and provenance through compaction and restart.

Retain context epochs and session/project correlation where needed. Those records describe memory delivery and recovery; they do not authorize dispatch or certify worker completion. Checkpoint acknowledged memory before reclaiming required context.

**Finish:** Less redundant context with no accepted loss of required information, no cross-project leakage, and correct recovery under native compaction/restart in the qualified host scope.

### Stage 5 — Skills and reusable procedural knowledge (M08, narrowed execution boundary)

Improve skill discovery, specificity, dependency declarations, approved-byte binding, retrieval precision, versioning, and evidence of usefulness. Turn recurring methods into concise recipes or host-invoked deterministic helpers with explicit inputs, outputs, effects, and validation.

Do not build a task scheduler or agent/workflow executor to run those recipes. The host performs tool actions under native permissions. Pure Brain transformations and authorized memory operations can remain local functions; they must not acquire agent lifecycle authority. A recalled command is not automatically permission to execute it.

**Finish:** Representative recurring tasks require less rediscovery and fewer unnecessary model/tool exchanges while preserving exact approvals, permissions, and output quality. Comparison is against competent native tooling, not an artificially weak baseline.

### Stage 6 — Consolidation and memory-only learning (M09, M10)

Merge duplicate knowledge without losing conflicting evidence. Separate durable facts, procedures, historical observations, and uncertain hypotheses. Improve invalidation, retrieval selection, representation choice, cache policy, and memory ranking through bounded offline evaluation.

Learning policies may choose how Brain retrieves or represents knowledge. They may not choose agents, assign models, dispatch work, grant tools, or control native execution. Model-assisted maintenance is explicitly invoked/authorized and accounted for, not an always-on autonomous agent campaign.

**Finish:** At least one retained learning/consolidation mechanism demonstrates net future benefit against an appropriate fixed baseline, including its construction, evaluation, and maintenance costs. Harmful or stale candidates are rejected or reversed.

### Stage 7 — Bounded storage/resources and portable adapters (retained M11/M12 responsibilities)

Bound Brain's own index/cache footprint, memory use, query work, context size, disk activity, and maintenance. Use retention policies and content reuse rather than accumulating redundant outputs and worktrees. Protected knowledge, required release evidence, and active work are excluded from indiscriminate cleanup. Do not create a new worktree for every measurement cell.

Prefetch, where justified, is limited to permitted memory/source reads and bounded local work. It does not speculate by launching agents or new paid model tasks. No shared agent-capacity reservation or workload scheduler remains.

Define stable core/adapter contracts for context requests, retrieval results, memory writes, delivery acknowledgments, and optional telemetry. Unsupported capabilities are explicit. Qualify the retained feature set on the intended primary host and a real second host, reusing evidence where appropriate. Do not make authenticated coordinator authority a portability prerequisite.

**Finish:** Retained core behavior is host-independent within declared contracts, resource use is bounded on the user's 16 GB system, and required second-host claims have actual host evidence. A synthetic adapter fixture alone cannot prove a live integration.

### Stage 8 — Integrated v3 qualification (M13, no new architecture)

Check interactions among no-op behavior, useful retrieval, reuse/invalidation, context continuity, skills, learning, storage, migration, and adapters on exact shipping candidates. Resolve retained blockers and document actual qualification boundaries.

**Finish:** The retained v3 capabilities work together, meet the frozen correctness and performance criteria, and have a current-state-safe activation/recovery plan. No late coordinator or multi-agent subsystem is introduced as one more prerequisite.

## 5. Performance contract

For a controlled fresh no-benefit request, require zero Brain-added model-visible messages, tool schemas, status wrappers, and extra management calls. Useful retained context from earlier turns is accounted separately; cached tokens are not zero tokens.

The earlier charter proposed warm whole-turn incremental local overhead of at most 10 ms median / 50 ms p95, with a separate incremental cold-start target of at most 100 ms p95. These remain proposals until explicitly frozen for evaluation, not demonstrated current performance. Do not grant each new component a separate full-turn allowance or silently relax a failing threshold.

For useful-memory tasks, measure verified task quality, total tokens, time, local resources, cache validation, retries where observable, and the construction/maintenance costs of the Brain mechanism. Native execution can be measured without being controlled by Brain. Account for gaps rather than inventing full coverage.

No specific speedup or storage reduction is promised by removal. The immediate guaranteed scope change is less product behavior to maintain; performance gains must be measured.

## 6. What changes in the earlier roadmap

| Earlier theme | Revised treatment |
|---|---|
| Coordinator authority and worker-plane qualification | Retired from product scope, not marked proven |
| Native/governed profile transition work | Replaced by a bounded removal and compatibility check |
| Fast-runtime lifecycle broker | Keep only Brain-local request/resource handling |
| Episode/worker budgets | Passive usage records where supported; no native task admission |
| Resource-aware scheduling | Brain-local query/cache/index/maintenance limits only |
| Executable procedures | Approved knowledge/recipes and host-invoked bounded helpers; no agent controller |
| Cheap learned policies | Retrieval, representation, invalidation, and cache choices only |
| Context/worker recovery | Memory and context recovery for native sessions; no worker resurrection |
| Host protocol and adapters | Retained memory/context/skills/data/telemetry contracts only |
| Multi-agent runtime / orchestration improvements | Removed entirely, not moved to a later prerequisite |
| Memory, skill, hook, integrity, activation security | Retained wherever the affected capability remains |

This is the active roadmap in the candidate branch. It replaces the main-checkout-only
`docs/requirements/Second_Brain_V3_Roadmap_2026-09-21.md`; that file is historical
and is not present in this candidate. The old capability labels map as follows:

| Old roadmap clause | Active destination | Change in acceptance subject |
|---|---|---|
| §3.1 authenticated coordinator lineage, §4.1 M00 | Stage 0 | Coordinator custody/issuance retired, not proved; retain source/data lineage and integrity. |
| §4.2 M01, §4.3 M02 | Stage 1 | Passive native-task attribution and Brain-local fast path; no settlement or management models. |
| §4.4–4.7 M03–M06 | Stages 2–3 | Retain provenance, invalidation, source discovery, and precise retrieval. |
| §4.8 M07 | Stage 4 | Retain memory/context recovery and recipient epochs; retire worker resurrection. |
| §4.9 M08 | Stage 5 | Retain approved recipes and host-invoked helpers; retire procedure execution as an agent controller. |
| §4.10–4.11 M09–M10 | Stage 6 | Retain offline memory policy learning; no agent/model choice. |
| §4.12 M11, §4.13 M12 | Stage 7 | Brain-local resource bounds and retained host adapters; no task reservations or worker settlement. |
| §4.14 M13 | Stage 8 | Integrated retained-capability qualification with applicable security findings. |

The older §6 trials remain research history, not authorization to run paid experiments.
Its 10 ms median / 50 ms p95 warm and 100 ms p95 cold targets remain proposed
until frozen before evaluation. Retained obligations do not disappear merely
because an old demonstration used a worker route.

## 7. Finite release boundary

V3 qualification covers five groups: request-neutral performance; correct and useful memory/reuse/retrieval; safe context/skill continuity; bounded resources and portable retained contracts; and exact-candidate release integrity with applicable findings resolved.

Individual modules keep concrete tests and measurable outcomes. This grouping does not waive them. It prevents unrelated orchestration guarantees from being smuggled back into the release contract.

Research and implementation remain modular. Optional research may fail without blocking the retained product; missing required memory capabilities and real safety defects cannot be relabeled optional merely to make a release pass. Production activation remains a separate decision from candidate development.

## Source provenance and limits

This replacement plan uses the user's September 23 candidate report and explicit removal direction; the retrieved `00_MASTER_ROADMAP.md` dated September 9, 2026; and `Second_Brain_v3_Performance_Charter_PROPOSED_2026-09-09.md`. The retrieved M00 campaign-register copy describes earlier September 22 work and does not establish the latest local native-profile state.

The main checkout's `Second_Brain_V3_Roadmap_2026-09-21.md` was inspected for this candidate revision: §3.1 assigned authenticated coordinator lineage, §4.2 required settlement spans, §4.8 worker recovery, §4.9 procedure execution, §4.12 worker reservations/scheduling, and §4.13 worker settlement portability. Those clauses are superseded by the stage mapping above, not silently treated as satisfied. Its memory, context, skill, source, safety, and measurable-performance clauses remain in scope as restated here. This candidate does not edit the historical main-checkout file.
