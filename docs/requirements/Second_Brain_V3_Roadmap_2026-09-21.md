# Second Brain — v3 Development Roadmap
## From the closed OMP campaign to a faster, leaner, more useful Brain

**Date:** 21 September 2026  
**Status:** Proposed research and implementation roadmap; not an implementation result, release approval, paid-run authorization, or production-change authorization.  
**Development arrangement:** OpenCode is the external engineering environment. OMP remains the primary runtime being improved and tested. This is not a mandate to resume the separate OpenCode-adapter campaign.  
**Planning lineage:** Reconciles the 9 September performance charter and M00–M13 master roadmap with the owner’s latest campaign-closure reports. Retains the v2.1 → v2.7 → v3.0 progression. [P1–P5]

> **Product objective:** Make Brain inexpensive when irrelevant and demonstrably useful when relevant. Convert past work into reliable context, reusable computations, executable procedures, and cheap decisions instead of repeatedly asking a model to reconstruct it.

---

## 1. Starting position and limits of this roadmap

### 1.1 The reported baseline

The latest closure supplied by the owner reports a measured OMP subject of `bd4f8eae5f0d2d29c7d644ecfb8225b37ed9aa2a`, a separate evidence/tooling successor `7ee797e`, unchanged production, and five demonstrated current-subject native clauses. `unavailable_hosts_reported_unavailable` remains explicitly undemonstrated, not passed, waived, or retired. The scoped successor issuance remains `READY_TO_RECORD`, not canonically recorded. [P5]

The final unavailable-host adjudication is important: an internal structured-async telemetry signal accompanied a successful real operation, not a caller-visible typed refusal for an unavailable required execution path. It must not later be summarized as a successful refusal test. [P5]

The earlier 55-fresh / 2-reverified / 11-carried classification and the appendix’s 7-current / 61-carried-only classification describe different evidence representations. Neither can be substituted for the other, added together, or treated as a percentage of v3 completion.

These are supplied campaign facts, not a fresh inspection of the user’s machine. M00 confirms the actual source, runtime, state, configuration, and applicable authority before implementation. It does not repeat the closed campaign without a concrete contradiction.

**Readiness to develop is not universal release qualification.** Isolated v3 work may proceed after bounded admission without inventing full v1/v2 economics, portability, or production approval. Any still-applicable release hold remains applicable to release; it need not stop unrelated, permitted offline engineering.

### 1.2 What is preserved

Keep the sealed measured subject, historical evidence, canonical state, production installation, and current ownership/settlement protections intact. New runtime changes receive new identities and relevant qualification. An evidence-tooling change is not a runtime measurement.

The remaining host limitation is not the opening task. Revisit it only when a selected new feature, supported-host contract, or release obligation actually depends on the missing behavior. Do not manufacture a reachable failure solely to improve a freshness counter.

### 1.3 How this document relates to earlier plans

The earlier master already defines 14 modules and 56 work packets. This document adds implementation priorities, experiments, resource discipline, and updated entry conditions; it does not claim to replace every original module file or reproduce missing packet text. Preserve original requirement and packet IDs when mapping work. The individual module documents must be located before their packets are executed. [P1, P4]

The previous conversational “v3.0 observability → v3.5 portability” outline was a thematic sketch. It should not become a second competing release register. In this roadmap, **v3 development is the whole program; v3.0 is the integrated finish line**, with usable intermediate releases.

---

## 2. Product contract and scorecard

### 2.1 The intended experience

For a task that does not need Brain, the native request should pass through without Brain-specific prompt text, additional tool descriptions, or management model calls. For a task that needs memory, Brain should provide the smallest sufficient current context, locate relevant sources, reuse still-valid work, and recover unfinished obligations. A small request such as “continue” may need substantial recovery; prompt length is not a relevance oracle. [P2]

A native four-second response should remain approximately four seconds when Brain contributes nothing useful. Three seconds requires an actual saving elsewhere. We cannot promise a particular provider response time by reducing local overhead alone.

### 2.2 Initial performance targets

These are inherited **proposed acceptance targets**, not measured achievements. Bind them before candidate evaluation. A revised target requires an explicitly versioned decision, not a quiet relaxation after failure. [P2]

| Dimension | Target or acceptance principle |
|---|---|
| Fresh, no-benefit model request | Same substantive request and tool surface as matched native control; zero Brain-added model-visible tokens |
| No-benefit orchestration | Zero additional management model calls or agent-directed round trips |
| Warm, whole-turn local overhead | At most 10 ms median and 50 ms p95 additional blocking time, across all Brain stages combined |
| Cold startup | At most 100 ms p95 additional time to first dispatch, including discovery and initialization |
| Hosted completion | Matched practical parity on no-benefit tasks; paired uncertainty and a predeclared regression margin |
| Useful-memory tasks | Net reductions in total tokens and verified-completion time on declared representative workload classes, with no accepted quality regression |
| Routine gross overhead | Retain the earlier roughly ≤5% aspiration where applicable; do not substitute it for strict fresh no-op neutrality |
| Correctness | No new stale reuse, cross-project leakage, permission bypass, or lost acknowledged progress in required adversarial tests |
| Resources | Explicit CPU, private-memory, disk, queue, worktree, and maintenance budgets on the confirmed 16 GB laptop |
| Storage | Bounded temporary growth and safe lifecycle management; retained unique evidence remains available and integrity-checked |

No-benefit and useful-memory classes must pass separately. A large saving on a long task cannot hide a failing simple-task budget.

### 2.3 Measure the complete task

Use the root task plus every descendant, retry, cancellation, tool call, verification step, and attributable maintenance job. Separate logical input, cached input, output, exposed reasoning usage, actual provider cost, and subscription quota. A subscription call with no marginal invoice still consumes a resource; unknown quota attribution stays unknown.

Do not add a provider’s reasoning-token subset a second time if already included in output. Deduplicate usage by actual request/attempt identity, not by matching prompt text. Do not sum nested timing spans or confuse first visible output with verified completion.

Cached input is not absent input. OpenAI and DeepSeek expose provider-specific caching behavior; adapters must preserve and interpret the relevant versioned usage fields rather than pretend that one universal cache rule applies. [R2, R3]

### 2.4 Product outcomes beyond latency

Track correction retention, recovery of unfinished obligations, source-discovery success, unnecessary repeated reads, model coordination calls, context page-ins, invalidation errors, and evidence-supported completion. A citation that exists but does not support the claim is a failure, not a retrieval success.

Keep quality, safety, latency, tokens, money, and local resources separately visible. Do not encode a critical safety failure as a small cost penalty that a sufficiently fast policy can profitably ignore.

---

## 3. Architecture: extend the existing Brain

### 3.1 One authority, several derived representations

Retain the existing canonical event/state/evidence authority. Use derived, rebuildable representations for lexical indexes, embeddings, source catalogues, task capsules, dependency graphs, cached results, and compiled procedures. The logical representation can be richer without creating a second owner of project truth. [P3, P6]

**Version-independent authority (M00-CORD-02, owner decision 2026-09-22).**
Brain Core derives coordinator authority from an authenticated, normalized
runtime-lineage contract (`episode_id`, `runtime_instance_id`,
`parent_runtime_instance_id`, `root_runtime_instance_id`, optional `attempt_id`).
Harness adapters translate host facts into that contract; they never select the
coordinator by model, provider, role text, harness version, or implementation
class. The proven root runtime instance becomes the episode coordinator once,
durably, before privileged work. A child retains its root identity for correlation
but not its authority. Rebinds require proof of the same root; missing or
unauthenticated lineage fails closed. Same normalized evidence must yield the
same Core decision across OMP versions and different harness adapters; actual
adapter qualification still requires real host-origin evidence, not a synthetic
fixture alone. The detailed M00 gate and present host-origin blocker are recorded
in the candidate's `docs/intake/M00-CAMPAIGN-REGISTER.md`.

Conceptual flow:

```text
OMP event or user task
  → existing permission / ownership / lifecycle controls
  → cheap relevance and recovery decision
  → validated reuse or selected retrieval plan
  → task-specific context / checked procedure
  → native OMP execution and verification
  → durable required state + selective optional capture
```

This is a dataflow description, not a request for six services.

### 3.2 Reuse inventory before implementation

Map each module onto current code. Historical research identified `action_cache.py`, `hybrid_retrieval.py`, `vmem.py`, AutoInject, Brainstem control, skills, and evidence/governance as reuse candidates. Their present interfaces, active configuration, and coverage must be inspected; an old source excerpt is not proof that an advertised capability is active today. [P3]

Extend the current telemetry, budget, state, and skill lifecycles. Introduce a new subsystem only when a named capability cannot be implemented by a bounded extension, with the duplication and migration costs explicitly reviewed.

### 3.3 Minimum semantic contracts

Adapt existing types rather than impose a new database schema. Reusable knowledge needs identity and revision, project and permission scope, exact source locator, measured or observed subject, observation time, applicability, dependencies, and a distinction between observed facts, inference, conflict, and supersession. Late ingestion of historical evidence must not silently replace newer applicable evidence.

Reusable computations additionally need tool/environment versions, input and corpus-membership dependencies, relevant configuration, and validation cost. Context delivery needs recipient identity, context epoch, and delivered revision. Procedures need preconditions, allowed effects, limits, and completion evidence.

These semantics must remain distinct even when stored compactly or mapped onto existing fields.

### 3.4 Process and language choices

Start with the existing Python/TypeScript architecture. Compare a lifecycle-owned reused interpreter, an in-host snapshot fast path, and a small compiled/native kernel at the same execution boundary. Account for serialization, process ownership, startup, idle memory, and failure recovery—not just the body of one function.

A small persistent process may be justified; a cold process on every hook is not a principle. Conversely, an always-on daemon or a Rust rewrite is not an achievement by itself. Select the measured winner while preserving local autonomy and one canonical authority. [P2, P3]

---

## 4. Delivery sequence

| Release / module | Engineering outcome | Dependency |
|---|---|---|
| Entry — M00 | Actual baseline and existing-capability map; no new qualification loop | Latest closure and current repository |
| v2.1 — M01–M02 | Attributable measurements and request-neutral fast path | Admitted baseline |
| v2.2 — M03–M04 | Versioned evidence and dependency-safe reuse | Stable measurement/runtime boundary |
| v2.3 — M05–M06 | Automatic source discovery and selective retrieval | Validity-aware evidence and reuse |
| v2.4 — M07 | Fidelity-aware context and reliable continuation | Findable, current knowledge |
| v2.5 — M08 | Executable recurring procedures and automatic skill use | Context, effects, and dependencies |
| v2.6 — M09–M10 | Selective consolidation and useful cheap learned policies | Reliable outcomes and procedure traces |
| v2.7 — M11–M12 | Resource-aware operation and one real second-host proof | Stable core semantics |
| v3.0 — M13 | Integrated performance, quality, recovery, and release qualification | Feature-complete integrated candidate |

This is the inherited integration sequence, not a rule that all research must be serial. Storage safeguards and basic resource caps begin immediately. Second-host capability discovery begins at entry. Their complete adaptive implementation and qualification occur later. [P1]

### 4.1 M00 — bounded entry, not another campaign

**Research question.** What useful work already exists, what actually runs, and what is the smallest new delta needed for the performance program?

**Implementation plan.** First perform the existing M00.1 read-only admission. Verify repository path, full HEAD, worktree status, installed manifest, runtime/configuration/state identity, schema versions, active versus shadow features, applicable release authority, and recovery route. Read the latest closure and its final unavailable-host adjudication. Map M00–M13 against implemented, tested, staged, and operational capabilities without conflating those statuses.

Record current 16 GB hardware headroom and identify available second-host hooks without installation. Identify the correct successor source for development; do not reset a worktree to an old SHA just because the plan names it. Keep unrelated dirty work intact.

**Deliverable.** One concise admission/reuse map and the precise next bounded measurement packet. It should identify concrete contradictions, not list every historical unverified clause as a new blocker.

**Exit.** The next packet has a known subject, interfaces, allowed write locations, resource limits, and source of truth. A real contradiction affecting that packet is named; the closed campaign is otherwise reused. M00.1 stops before implementation, consistent with the original entry instruction. [P4]

### 4.2 v2.1 / M01 — attributable performance laboratory

**Research goal.** Explain where overhead comes from and make later improvement claims falsifiable.

**Techniques.** Correlated root-task/request/span identities, monotonic local clocks, matching request captures, component ablations, controlled local replay, and randomized paired live trials. OpenTelemetry’s trace/span model is a useful vocabulary; mapping existing telemetry to it does not require a new collector, server, or telemetry stack. [R1]

**Implementation plan.** Instrument startup, extension loading, environment/configuration resolution, relevance decisions, retrieval, validation, context rendering, provider dispatch, workers, tools, verification, settlement, and finalization. Record actual model requests immediately before dispatch, with credentials excluded and sensitive captures held only in approved private locations. Preserve substantive ordering and content; only explicitly listed transport-only identifiers may be normalized for neutrality comparison.

Build four controls: native OMP, inert extension with equivalent packaging, pinned current Brain, and candidate Brain. Maintain equivalent non-Brain settings, model, effort, and relevant safety restrictions. A native control for a memory task must still have reasonable access to the same underlying sources; do not construct an artificially helpless baseline.

Make a small task corpus and deterministic oracles. Extend existing accounting rather than create a new ledger. Add instrumentation-disabled measurements to quantify observer overhead.

**Exit tests.** Root-plus-child usage reconciles; missing usage stays unknown; failures and cancellations remain included; nested spans are not double-counted; cold and warm runs are separately reproducible; the real request-difference report includes tool schemas. Produce a ranked bottleneck report, not a performance verdict from two samples.

### 4.3 v2.1 / M02 — request-neutral execution

**Research goal.** Remove unnecessary Brain work before introducing more sophisticated retrieval.

**Mandatory comparison.** Existing cold bridge versus reused interpreter versus bounded in-host/compiled decision path. Use the same required behavior, inputs, failure cases, and accounting. A compiled candidate losing is a useful result; refusing to compare it solely because it is harder is not. [P1]

**Implementation plan.** Make no-benefit decisions from bounded, already-available state. Reuse validated configuration, lazily load rich functionality, coalesce redundant reads, and avoid spawning Python just to establish that nothing changed. Preserve an escalation path for ambiguous recovery-dependent tasks. The runtime must not consult a model to decide whether it needs Brain on ordinary no-benefit turns.

Move only optional aggregation, index maintenance, and report generation off the response path. Required progress, ownership, and completion records remain durable before their acknowledgements. SQLite WAL can permit concurrent readers and a writer, but not unlimited writers; long readers and checkpoint behavior still matter. Do not alter durability settings to manufacture a latency gain. [R4, R5]

Keep required safety controls separate from optional memory. If the shipping host profile necessarily adds model-visible Brain schemas, report that as an unresolved request-neutrality issue; do not remove required controls or use a non-shipping profile to claim success.

**Exit tests.** Exact substantive neutrality on fresh no-benefit cases; no false bypass on required-memory controls; inherited warm/cold budgets; safe lifecycle-owned shutdown and bounded idle resources; matched live parity when the provider campaign is explicitly authorized. Local replay alone does not prove hosted latency.

### 4.4 v2.2 / M03 — evidence objects and rebuildable views

**Research goal.** Make evidence useful across time without allowing a historical observation to impersonate current truth.

**Implementation plan.** Extend current object/revision and provenance contracts. Keep exact source material addressable, with compact structured views derived from it. Distinguish an observation’s subject from the artifact issuing or referencing it. Preserve conflicts and applicability intervals. Make indexes and summaries rebuildable from canonical material.

Reuse the new evidence-append behavior where applicable, but do not assume its qualification-artifact schema is automatically the right schema for all runtime memory. Integrate semantics through compatibility mappings rather than migrate everything into one giant record type.

**Tests.** Rebuild from preserved source; late historical import; conflicting statements; changed permission; missing source; partial evidence under one key; tampered references; export/import that preserves unknown provenance as unknown.

**Exit.** The runtime can retrieve the correct current or historical view with supported provenance, and derived views cannot become independent truth owners.

### 4.5 v2.2 / M04 — incremental memory build graph

**Research goal.** Save repeated work without stale reuse or more bookkeeping than the work being saved.

**Techniques.** Explicit dependencies, reverse invalidation edges, content identities, query/corpus revisions, and red-green-style recomputation. Build-system research provides a model for comparing dependency-driven execution; Salsa documents retaining downstream results when re-execution produces an unchanged value. These are mechanisms to prototype, not a requirement to adopt a particular framework. [R6, R7]

**Implementation plan.** Start with one high-frequency existing action-cache use case. Bind reusable results to relevant tracked, staged, dirty, and untracked inputs; file additions/deletions; source-set membership; parser/tool/test versions; configuration; permissions; and environment. Add negative-cache invalidation: “no matching file exists” depends on the searched source set, not just files found previously.

Treat file watchers as invalidation hints, not sole truth. Reconcile after lost events, restarts, ambiguous state, and overflow. Retain valid downstream results when a revalidated derived value is unchanged. Recompute rather than validate when validation is more expensive. Validate before reuse at the actual effect boundary when concurrent changes could matter.

**Experiment.** Full recomputation versus coarse invalidation versus dependency-aware reuse on repeated repository and source-discovery tasks. Measure validation overhead, work avoided, stale-result failures, and end-to-end completion.

**Exit.** Unchanged work is measurably reused; relevant changes invalidate it; corpus additions and permission changes are caught; uncertainty falls back safely; unrelated edits do not force complete rediscovery.

### 4.6 v2.3 / M05 — source discovery and prospective cues

**Research goal.** Make the agent find existing mappings, dumps, assets, tests, and project knowledge without being reminded of their location.

**Implementation plan.** Extend the existing repository/source catalogue with concise descriptors: source owner, approved root or endpoint, build/version, searchable concepts, supported inspection operation, exact locator convention, freshness dependency, and access limit. Descriptors point to authoritative domain stores; they do not copy the whole SZ knowledge base into Brain.

Use cheap event/task cues: project switch, relevant file change, known entity, requested continuation, or an unresolved obligation becoming actionable. Resolve to an existing supported inspector. Read-only discovery must not silently trigger database migration, bulk extraction, network scans, or game-runtime access.

**Dogfood workload.** In a fresh session, ask a natural question requiring an existing SZ mapping/dump/asset reference. Brain must discover and inspect the approved source, return the exact build-scoped reference, and decline inappropriate reuse after a build mismatch. Use Basic Upscaler source/evidence navigation as another project family, not as permission to run new game experiments.

**Exit.** Held-out natural wording finds the right source and actual evidence. Merely injecting “mappings exist” or returning a directory name is insufficient. Wrong-project and missing-source controls remain explicit.

### 4.7 v2.3 / M06 — selective retrieval planner

**Research goal.** Choose the least expensive retrieval plan that supplies enough current evidence.

**Mandatory comparison.** A well-tuned lexical/exact baseline against a genuine compact local semantic prototype and a selective hybrid. SQLite FTS5 supplies local full-text search and ranking facilities. SimpleMem’s current paper combines structured, lexical, and semantic representations, but also uses model-based compression/planning; we should compare the representation ideas without importing an extra model call into every Brain request. [R8, R9]

**Implementation plan.** Begin with project and permission eligibility, then exact references/symbols and lexical retrieval. Use semantic expansion, bounded relations, temporal filters, or reranking only where measured need justifies them. Test stable rank fusion and diversity selection against existing scoring rather than installing every retrieval backend.

Add a no-result/abstain route, compact contradiction surfacing, deterministic tie-breaking, and explicit freshness checks. Calibrate the planner against difficult paraphrases and exact identifiers. Keep indexes derived from the same evidence objects. A local encoder is a comparative prototype, not a mandatory always-loaded GPU dependency.

**Metrics.** Required-evidence recall, top-k precision, stale/wrong-project eligibility, contradiction detection, false abstention, injected tokens, p95 latency, index construction/refresh cost, and RAM under concurrent work.

**Exit.** Useful recall and task completion improve or preserve required quality within budgets. Always-hybrid must not win by ignoring its build cost; lexical-only must not win by dropping hard memory cases. A mechanism may remain unselected, but the required retrieval outcome cannot be declared optional.

### 4.8 v2.4 / M07 — context compiler and continuity

**Research goal.** Supply the smallest sufficient working context while preserving the ability to recover exact evidence and all unfinished obligations.

**Implementation plan.** Extend existing VMem, capsules, and compaction hooks. Support exact, structured, extracted, and summarized views with explicit fidelity requirements. Keep exact values, negation, constraints, permissions, unresolved findings, and evidence locators protected. Allocate optional context by predicted task value and redundancy, not by blindly truncating the longest messages.

Track delivery per recipient and context epoch. “Delivered once” is not proof that a resumed or compacted agent still has it. Rehydrate after actual loss and suppress duplicates only when the relevant revision remains resident. Measure cumulative context across a task, not just the first small packet. A pointer that causes several extra model round trips may be worse than a slightly larger initial packet.

Preserve stable provider prefixes where appropriate; evaluate the complete request and cache impact rather than assuming that any smaller prompt is automatically cheaper or faster. [R2, R3]

**Experiment.** Current context policy, exact bounded excerpts, structured capsules, and selected summaries on compaction/restart, contradiction, later-detail, and worker handoff workloads. Compare total completion cost, page-ins, omissions, and recovery.

**Exit.** Real OMP compaction/restart/worker recovery preserves acknowledged progress and material requirements without transcript replay. Required material is durably covered before reclamation. No language-model summary is treated as universally lossless.

### 4.9 v2.5 / M08 — executable procedural memory

**Research goal.** Turn validated recurring workflows into checked execution, not merely a larger collection of prose skills.

**Implementation plan.** Reuse existing skill discovery, promotion, reversible tool distillation, and verification. Represent a selected procedure through typed inputs, scope, preconditions, dependency references, permitted effects, bounded steps, approval requirements, output contract, and completion evidence. Deterministic steps execute without a model reinterpreting each one; semantic ambiguity returns to the model through a narrow interface.

Candidate pilot workflows are source discovery/inspection, changed-code verification planning, and verified continuation/handoff. Reconcile these candidates against the original M08 module’s three declared families before selecting them; this document does not silently rename that retained acceptance requirement.

Implement automatic selection with a supported no-match route. A procedure must reject incompatible builds, changed assumptions, excessive scope, or insufficient authority. Read-only and mutating effects remain separate. Idempotency and retry semantics must be explicit; a script is not safe just because it was used successfully once.

**Strong controls.** Compare against existing native scripts and native parallel tools as well as prose skills. Do not show value only by contrasting with an unnecessarily chatty agent. Attribute compiler, selection, verification, and maintenance costs.

**Exit.** The declared procedure families work on held-out natural tasks and adverse inputs with fewer avoidable coordination calls and no weakened verification. A novel one-off task must still proceed normally rather than be forced into an ill-fitting procedure.

### 4.10 v2.6 / M09 — selective capture and consolidation

**Research goal.** Retain useful experience without summarizing every turn or continuously rewriting memory.

**Implementation plan.** Capture structured events cheaply at meaningful changes: a correction, disconfirmed hypothesis, verified repair, repeated failure, dependency change, new authoritative source, or newly actionable blocker. Preserve exact supporting evidence. Treat a single surprising event as a candidate for investigation, not an automatic general rule.

Rank consolidation candidates using recurrence, severity, likely future need, source stability, and estimated work avoided. Compare no consolidation, fixed scheduling, and value-selected preparation. Preserve the earlier fast-acquisition/slow-integration idea as an engineering inspiration, not a literal two-database biological model. [P3]

Demote rarely useful views from expensive indexes/resident caches without destroying unique required evidence. Keep user corrections and safety-critical obligations protected independently of frequency.

**Lifetime test.** Charge preparation, invalidation, refresh, and storage/interference costs to the later reuse sequence. In any one consistent unit, break-even reuse requires:

```text
N > construction_cost / (cost_without_reuse - cost_with_reuse - maintenance_per_use)
```

The denominator must be positive. Track tokens, time, money, and local resources separately rather than pretending this equation proves a universal scalar value.

**Exit.** Selected consolidated knowledge demonstrably repays its preparation over held-out repeated tasks, handles corrections, and can be demoted or reversed when stale or harmful.

### 4.11 v2.6 / M10 — offline policy learning, cheap runtime

**Research goal.** Let expensive investigation improve cheap runtime choices rather than add a paid supervisor to every event.

**Techniques.** Compare fixed rules, small decision tables/classifiers, and offline search over retrieval plans, representation choices, cache admission, or procedure triggers. GEPA is a research comparator for feedback-driven offline optimization, not proof that prompt evolution will automatically solve Brain’s routing or produce a useful deployed policy. [R10]

**Implementation plan.** Learn from properly attributed traces after M01–M09 provide trustworthy semantics. Log candidate choice, available alternatives, observed outcome, and selection probability when exploration is used. Do not reconstruct historical propensities after the fact or claim causality from co-occurrence.

Separate train/calibration/held-out tasks by time or project where appropriate. Keep evaluation criteria outside the optimizer’s write authority. Deploy the selected policy as a cheap bounded function, with versioning and a deterministic fallback. Policies may select optional work within permissions; they cannot rewrite permissions, trust, acceptance criteria, or ownership rules.

**Exit.** At least one cheap learned policy shows a real held-out benefit over a strong fixed policy and is promoted through the existing governed lifecycle. Demonstrate rejection or reversal of a harmful/stale alternative. If no candidate meets the retained core learning requirement, report that requirement unfinished; do not relabel it optional to declare v3 complete. [P1]

### 4.12 v2.7 / M11 — resource-aware workflow and storage

**Research goal.** Keep the user’s machine responsive and Brain’s cost bounded as work and stored history grow.

**Start now, complete here.** Initial campaigns already need output quotas, owned worktree limits, queue bounds, and no unapproved paid maintenance. M11 completes the adaptive policies; it is not permission to defer basic safeguards until the end.

**Implementation plan.** Extend the existing Brainstem/resource governor with root-task budgets shared by workers, reservations for in-flight calls, bounded deterministic jobs, and foreground priority. Keep the main model/effort fixed during core Brain comparisons; later model or effort routing is a separately measured policy. Prefer same-model effort adjustment where useful before introducing frequent main-loop switching.

Compare simple LRU with S3-FIFO-style admission/eviction on Brain traces. S3-FIFO’s probationary filtering is a relevant cache technique, but its systems results do not establish lower Brain tokens or latency. Evaluate complete costs. [R11]

Restrict speculative preparation to known, authorized, side-effect-free reads whose inputs and snapshot are already identified. Cancel or demote it under pressure. No speculative writes, secret uploads, or paid model calls. Count unused prefetch and foreground interference.

**Storage lifecycle.** Classify data as protected source/evidence, rebuildable derived state, or disposable execution material. Prefer content-addressed immutable artifacts and manifests referencing shared content. Use compression for cold material only with exact recovery checks. Identify references from historical manifests, active tasks, retained snapshots, and recovery requirements before garbage collection.

Do not delete a worktree because its TTL expired. Verify ownership, process settlement, no unpreserved dirty/untracked work, retained commits/patches, and evidence references. Use supported worktree lifecycle commands. `git worktree prune` removes stale administrative information; it is not a general cleaner for existing worktree directories. [R12]

A finite disk cannot preserve unlimited unique history forever. The honest guarantee is bounded disposable/derived growth, explicit protected retention, and admission backpressure before capacity exhaustion—not a promise that the repository can never grow.

**Exit.** Constrained-memory, disk-pressure, crash/restart, cancellation, leaked-process, and concurrent read/write tests preserve required state. Growth follows the declared retention policy; no safety evidence or unmerged work disappears. Cold archives reconstruct exactly. Foreground task quality and latency remain acceptable on the actual 16 GB machine.

### 4.13 v2.7 / M12 — portable core, one real second host

**Research goal.** Verify that the core does not depend on an OMP-only assumption while keeping OMP the primary runtime.

**Implementation plan.** Inspect the second-host capability boundary at M00 and exercise adapter-independent interfaces from M02 onward. At this stage select one already available, authorized second host based on actual lifecycle access and existing adapter work. Using OpenCode to edit OMP does not by itself qualify OpenCode as a Brain runtime.

Reuse existing adapters. Test shared canonical authority, project isolation, task/context identity, real retrieval and capture, compaction/restart behavior, supported procedure execution, and ownership/settlement for any advertised worker capability. Declare unsupported functions instead of simulating them behind a “universal” label.

Do not wait until this stage to discover that the context compiler depends on a private OMP hook. Do not open a third harness campaign or a desktop-control framework as a prerequisite.

**Exit.** OMP and one real second host demonstrate the retained portable-core outcomes under declared supported profiles. A restricted profile must not silently omit a mandatory outcome. Where the existing unavailable-host limitation matters to a claimed portable path, address that dependency explicitly without rewriting the old adjudication.

### 4.14 v3.0 / M13 — integration and release convergence

**Research goal.** Establish that the combined system improves real tasks and does not lose correctness through feature interactions.

Freeze the feature set before final qualification. Use the existing measured subjects and compatibility evidence where applicable, and rerun changed dependencies plus necessary cumulative/interaction cases. No new memory architecture or endless “one more prerequisite” belongs here. [P1]

**Required result.** Request-neutral no-benefit behavior; valid incremental reuse; real source discovery; context fidelity and actual recovery; the declared executable procedure families; selective consolidation and a beneficial cheap learned policy; bounded resources; OMP plus one real second-host proof; upgrade/recovery integrity; resolved critical findings; and explicit owner release approval.

An optional experiment can finish rejected, deferred, or hardware/API blocked without blocking the release. A missing mandatory outcome cannot be renamed optional. The definition of done is finite, but it is not negotiable through presentation changes.

---

## 5. Research program and selection rules

### 5.1 Comparative experiments

| ID | Question | Required comparison | Decisive evidence |
|---|---|---|---|
| E1 | Which execution boundary makes Brain cheapest? | Cold bridge, reused interpreter, in-host/compiled path | Same request semantics; whole-path cold/warm costs; lifecycle/resource safety |
| E2 | Does dependency-aware reuse save net work? | Recompute, coarse invalidation, precise dependencies | Valid reuse wins after validation costs; adverse invalidation cases do not leak stale results |
| E3 | When is semantic retrieval worth running? | Strong lexical, local semantic, always-hybrid, selected hybrid | Held-out relevant evidence and task quality versus full latency/memory/index cost |
| E4 | Which context representation is sufficient? | Exact excerpts, structured capsule, summary, current policy | Preserved obligations/details; fewer total tokens/round trips including later page-ins |
| E5 | Do procedures beat strong native tooling? | Native scripts/parallel tools, prose skill, checked procedure | Reduced coordination at equivalent verified outcome and permissions |
| E6 | Does selective consolidation repay itself? | None, fixed, value-selected | Full repeated-task lifecycle benefit including construction and stale refresh |
| E7 | Can a learned selector beat fixed rules cheaply? | Fixed policy, small learned policy, offline search candidate | Held-out benefit; correct attribution; safe rejection and reversal |
| E8 | Which cache/prefetch policy helps under load? | LRU, S3-FIFO-style policy, no prefetch, bounded prefetch | Completion improvement exceeding wasted work and interference |
| E9 | Does the same core really work on two hosts? | OMP and one actual second host | Shared authority and retained behavior through real supported native paths |

Every experiment needs a hypothesis, implementation dependency, controls, workload split, resource ceiling, decision rule, and stopping condition. A literature review ends in a decision or a bounded experiment—not in a permanent reading queue. Keep published results, local reproduced results, and proposed synthesis labeled separately.

### 5.2 Conditional frontier work

The earlier ambitious ideas remain research tracks, not discarded goals. Difficulty alone is not a rejection criterion. Their adoption depends on access, hardware, correctness, and measured lifetime value. [P3]

| Track | First useful experiment | Boundary |
|---|---|---|
| Learned compression | Compare extraction/structured views with one learned compressor on exact-value, negation, correction, and later-detail tasks | Compression must not silently discard obligations; preparation and page-in costs count |
| Rich graph / multi-vector retrieval | Isolate relation-heavy or paraphrase cases where the current planner misses necessary evidence | No always-on graph expansion or second canonical store without measured need |
| Neural or activation memory | Use a small compatible local-model fixture and compare against external retrieval | Requires real model/runtime access; cannot assume hidden-state or KV control over a hosted model |
| Local serving / prefix-state reuse | Compare supported local serving behavior on compatible models and the actual laptop | API/model compatibility and resource use are separate from prompt caching in a cloud API |
| Aggressive speculative reads | Overlap a known pure read under a constrained workload | No speculative effects, unknown authority, hidden provider spend, or unsupported cancellation claims |
| Broader usage/effort routing | Same-model fixed effort versus a cheap selector, then explicitly approved routing alternatives | Model changes cannot be counted as a core Brain optimization; cache and quota transitions count |

None of these requires installing a service at roadmap admission. Reverify the selected primary source, license, implementation status, and dependency version when the experiment is scheduled.

---

## 6. Evaluation design

### 6.1 Representative workload families

Use actual Second Brain work plus approved offline SZ and Basic Upscaler sources. Keep a held-out set of naturally phrased tasks and adverse cases. LongMemEval’s categories—updates, temporal reasoning, multi-session information, and abstention—are useful supplements, but do not replace repository correctness and native lifecycle tests. [R13]

| Family | Required challenge |
|---|---|
| Genuine no-benefit | Arithmetic or direct answer with no relevant project obligation |
| Short but memory-dependent | “Continue,” “use the earlier decision,” or a compact project switch |
| Known-source discovery | Find and actually inspect approved mappings, dumps, assets, tests, or evidence |
| Repeated engineering task | Reuse a valid result without recreating its discovery sequence |
| Changed reality | Dirty/untracked edits, new files, source updates, changed permissions or build |
| Context continuity | Compaction, restart, worker handoff, later exact-detail question |
| Contradiction and absence | Corrected fact, conflicting evidence, no supporting source, wrong project |
| Pressure and recovery | Limited RAM, full disk, interrupted write, cancellation, process loss |

Construct local fixtures with explicit ground truth. Use independent review for genuinely semantic outcomes, blinded to the candidate arm where practicable. Do not let a self-assigned model confidence replace deterministic checks. Public benchmark improvement is supporting evidence, not the product’s finish line.

### 6.2 Trial discipline

Start with cheap local replay and profiling. Then propose an explicitly bounded live pilot to characterize variance and decide the repetition count. Thirty paired observations may be a starting pilot; they do not establish a reliable tail or a small effect by themselves. Choose counts and stopping rules based on the decision and observed variance, before evaluating the final candidate. [P2]

Randomize/interleave matched arms. Keep model, reasoning effort, source availability, machine load, and non-Brain settings comparable. Separate warm and cold starts and provider-cache conditions. Reset independent arms to equivalent initial state; preserve intended within-sequence learning when testing consolidation. Do not leak learned candidate state into a supposedly untouched control.

Report per-family quality and costs alongside aggregates. Use paired uncertainty and appropriate task/session grouping rather than treating correlated repeated turns as independent samples. Retain failed runs, timeouts, budget stops, and missing usage. Inconclusive is an acceptable experiment result; it is not measured parity.

### 6.3 Security and trust tests

Include poisoned retrieved text, forged evidence links, attempted policy promotion, cross-project leakage, permission revocation, and instructions embedded in documents or skill candidates. Memory-injection research makes clear that persistent agent memory is an attack surface; tests must distinguish untrusted content from authority. [R14]

Generated claims cannot authorize effects. Foreign skills remain candidates until the existing checks and approvals are satisfied. Keep secrets out of captures and training corpora. Do not upload source material to a research service merely because the roadmap includes an offline teacher.

### 6.4 Budget envelope

Each executable packet records the allowed subject, commands/scenarios, write roots, maximum duration, provider/model allow-list, request and token limits, money cap, worker count, local-memory ceiling, output quota, and stop behavior. Reserve budget for in-flight work and settlement before starting additional calls.

An old campaign’s unused money is not authorization. Do not reuse the completed $0.02 allowance. Where no new provider budget is approved, do the permitted offline work and leave the native/provider-dependent conclusion unclaimed.

---

## 7. Storage discipline from the first sprint

The storage problem is not solved by one cleanup or by compression alone. Development output needs a lifecycle before new experiments multiply it.

**At admission:** inspect sizes using existing manifests or bounded directory summaries. Do not hash or traverse the entire archive on every hook. Identify output owners and active worktrees. Select per-packet limits before creating new material.

**At capture:** write one immutable source artifact, reference it from receipts, and avoid copying whole homes or full packs unless recovery or reproduction specifically requires them. Keep optional telemetry bounded. If essential raw evidence reaches its allocation, stop the experiment with an incomplete result rather than silently truncate it and claim success.

**At closure:** preserve source/results/failure evidence and the reproduction recipe, remove only proven disposable material in an authorized boundary, and verify surviving references. Compression and archival are lossless operations with round-trip checks; garbage collection follows references and retention authority.

**Protected by default:** canonical DB and journal state, unique source material, accepted or disputed evidence, active ownership records, historical seals, and unpreserved work. A user-requested deletion or retention-policy change is a separate explicit action, not automatic TTL cleanup.

Full adaptive cache/retention optimization is M11. These basic limits are an immediate development requirement, not a new release series.

---

## 8. First sprint: strong start without a rewrite

This is a deliverable sequence, not a calendar promise. Estimate time after the existing-code delta and first measurements are known.

### Step A — M00.1 admission

Read-only verification and reuse map. Stop at the defined entry checkpoint. The accompanying first-session prompt is designed for this step only.

### Step B — first authorized M01 packet

Add or extend root-task accounting, request comparison, and stage timings in an isolated candidate. Start with no-benefit and short-memory-dependent fixtures plus one real source-discovery fixture. Set output/worktree limits before generating data. Use only approved local runs.

### Step C — identify the dominant avoidable cost

Run matched local controls and one-component ablations. Distinguish extension packaging, process startup, retrieval, locking, rendering, and provider time. Select one intervention because its measured contribution is material—not because “Rust,” “vectors,” or “async” sounds faster.

### Step D — first M02 candidate

Implement the selected minimal no-op/startup repair, compare the alternate execution-boundary prototype where required, and preserve recovery/permission tests. Prepare the smallest justified live-provider comparison and budget proposal; do not self-authorize it.

### Sprint outputs

A verified baseline/reuse map, an attributable local measurement path, a causal bottleneck ranking, and one bounded optimization candidate with correctness tests. Hosted economics may remain pending authorization; say so. Do not promise a full v2.1 release merely because the local candidate is promising.

**Not in this sprint:** a new vector database, model router, generic daemon framework, full neural-memory engine, mass archive migration, GUI, broad adapter rewrite, or another full 68-clause issuance cycle.

### Working arrangement

Use one designated implementation owner per mutating scope and an independent reviewer for material boundary changes. OpenCode controls and observes isolated OMP runs; it must not secretly perform the cleanup or state repair whose native behavior is being tested. Keep production OMP unchanged.

The reviewer receives the original requirement, actual diff, relevant source, and raw results—not only the implementer’s narrative. Jev/TypeSafe may supplement evidence audits at meaningful checkpoints under its approved resources; it does not replace deterministic tests or the accountable review decision.

The agent makes routine engineering decisions inside the authorized packet. Packet/release progression, new spend, destructive cleanup, canonical migration, and production activation remain explicit boundaries. Do not ask the owner to choose every function name or test implementation.

---

## 9. Migration, promotion, and rollback

Prefer additive compatible interfaces, isolated backfill, rebuildable derived views, shadow comparison, one-owner cutover, and retirement of duplicate internals only after compatibility proof. Unknown historical provenance must remain unknown. [P1]

A rollback must preserve the most recently acknowledged work. Restoring an older database may erase later progress, so binary/config rollback and state recovery need separate treatment. When an old binary cannot read current state, use a verified compatible export or forward repair rather than a destructive downgrade.

Apply OFF → SHADOW → ADVISORY/CANARY → ACTIVE where relevant, but account for shadow costs and do not treat simulation as native proof. Independent review and affected regression tests are sized to risk. Full cumulative and interaction checks still occur at the relevant release boundary.

Keep one existing traceability path: requirement → changed implementation → exact executed subject → evidence → review. Use small incremental receipts and links to preserved raw data. Do not generate another enormous nested evidence bundle solely to restate an unchanged verdict.

User-facing status should distinguish implemented, tested, qualified, staged, and activated. Model-free tests, native execution, and provider-backed economics are separate forms of evidence. Tooling identities and runtime subjects stay separate.

---

## 10. Finite definition of done

V3.0 is ready only when the retained core outcomes are demonstrated together in the intended shipping configuration: no-op economics, valid reuse, findable knowledge, context continuity, executable procedures, useful selective learning, predictable resources, and real portable operation. Required release, security, migration, recovery, and owner-approval conditions remain intact. [P1]

Every optional research track receives a disposition. No automatic v2.8, v2.9, universal “freshness campaign,” or new prerequisite platform is introduced at the finish line. A genuine discovered blocker is a bounded dependency repair whose effect on the release claim is explicit.

The practical success test is simple: ordinary prompts do not pay for unnecessary Brain work; recurring engineering tasks require less rediscovery and coordination; corrections and unfinished work survive; and these gains do not depend on hidden worker tokens, background costs, stale evidence, or unbounded disk growth.

---

## 11. Sources and research status

### Project planning and owner reports

**[P1]** `00_MASTER_ROADMAP.md`, 9 September 2026. Retrieved from the user’s File Library. Supplies the v2.1–v3.0 sequence, M00–M13, mandatory comparison/core outcomes, migration principles, and finite finish line. Planning source, not implementation proof.

**[P2]** `Second_Brain_v3_Performance_Charter_PROPOSED_2026-09-09.md`. Retrieved from the File Library. Supplies proposed 10/50/100 ms budgets, request neutrality, whole-task accounting, workload controls, and attribution requirements. Historical measurements inside it are not current installed measurements.

**[P3]** `Second_Brain_v3_Architecture_Research_and_Synthesis_2026-09-09.md`. Retrieved from the File Library. Supplies incremental memory compilation, context/procedure views, selective consolidation, offline policy learning, hardware/API distinctions, and the earlier 61-source research register. This roadmap does not claim all 61 sources were freshly revalidated.

**[P4]** `FIRST_SESSION_PROMPT.md`, 9 September 2026. Retrieved from the File Library. Supplies read-only M00.1 admission and its stop boundary. Individual module files linked by the master were not fully retrieved for this response; the executing agent must locate them before applying their specific packets.

**[P5]** Owner-supplied OMP campaign reports in this conversation, culminating in the 21 September final unavailable-host adjudication and closure. Supplies the sealed subject, tooling successor, five demonstrated native clauses, explicit limitation, scoped issuance, and no-production-change status. Not independently executed here.

**[P6]** `2nd Brain — Canonical R&D Scout Spec (v1.0 + v2.0)`, connected Google Doc read on 21 September 2026; and `Second_Brain_v1_v2_Deep_Implementation_Upgrade_Research_Plan.md`, 29 August 2026, retrieved from the File Library. Supplies local-first, reuse-first, deterministic-first, controlled promotion, token-economy, and existing skill/Brainstem principles. Their global release scope is not silently satisfied by a later OMP-only ledger.

### Primary external sources checked for this roadmap

All URLs below were accessed on 21 September 2026. Source publication results are not reproduced Second Brain results. Documentation and paper versions should be pinned again when implementation creates a dependency.

**[R1] OpenTelemetry, “Traces.”** Official conceptual documentation. Trace/span correlation vocabulary; no requirement to adopt a new collector.  
`https://opentelemetry.io/docs/concepts/signals/traces/`

**[R2] OpenAI, “Prompt caching.”** Official API documentation. Prefix reuse and provider-specific cache accounting; no local Brain savings claim.  
`https://developers.openai.com/api/docs/guides/prompt-caching`

**[R3] DeepSeek, “Context Caching.”** Official API documentation. Provider-specific cache behavior and usage fields.  
`https://api-docs.deepseek.com/guides/kv_cache/`

**[R4] OpenAI, “Latency optimization.”** Official API documentation. Avoiding unnecessary model requests and processing; not a promise about a particular hosted task.  
`https://developers.openai.com/api/docs/guides/latency-optimization`

**[R5] SQLite, “Write-Ahead Logging.”** Official implementation documentation. Writer concurrency, checkpointing, and deployment constraints; retain actual existing configuration until a measured change is justified.  
`https://sqlite.org/wal.html`

**[R6] Mokhov, Mitchell, and Peyton Jones, “Build systems a la carte: theory and practice.”** Journal of Functional Programming, 2020; Microsoft Research author publication page. Framework for comparing build-system mechanisms. Publication overview inspected, not a new implementation reproduction.  
`https://www.microsoft.com/en-us/research/publication/build-systems-a-la-carte/`

**[R7] Salsa, “Algorithm.”** Official documentation. Revision/dependency validation and red-green/backdating behavior; direct algorithm description inspected.  
`https://salsa-rs.github.io/salsa/reference/algorithm.html`

**[R8] SQLite, “FTS5 Extension.”** Official documentation. Lexical search, ranking, tokenization, and index configuration.  
`https://sqlite.org/fts5.html`

**[R9] Liu et al., “SimpleMem: Efficient Lifelong Memory for LLM Agents.”** arXiv:2601.02553v3, 29 January 2026. HTML method sections inspected. Structured/lexical/semantic representations and model-based processing; no extrapolation of author benchmark gains to Brain.  
`https://arxiv.org/html/2601.02553v3`

**[R10] “GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning.”** arXiv:2507.19457. Author abstract/metadata screened as an offline optimization comparator; a methods-level implementation review remains part of M10 research.  
`https://arxiv.org/abs/2507.19457`

**[R11] “FIFO Queues are All You Need for Cache Eviction.”** SOSP 2023; authors’ CMU Parallel Data Laboratory publication summary. S3-FIFO as a comparative cache mechanism; not a Brain performance result.  
`https://www.pdl.cmu.edu/PDL-FTP/Storage/FIFOqueues-SOSP23_abs.shtml`

**[R12] Git, “git-worktree.”** Official command documentation. Ownership-aware worktree lifecycle; prune is not arbitrary directory deletion.  
`https://git-scm.com/docs/git-worktree`

**[R13] “LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory.”** arXiv:2410.10813. Author abstract/benchmark scope screened; categories supplement, not replace, project evaluation.  
`https://arxiv.org/abs/2410.10813`

**[R14] “Memory Injection Attacks on LLM Agents via Query-Only Interaction.”** arXiv:2503.03704. Author abstract/security scope screened. Persistent memory is an attack surface; the roadmap’s controls are proposed mitigations to test, not a proven complete defense.  
`https://arxiv.org/abs/2503.03704`

---

**Immediate next action:** run only the accompanying M00.1 admission prompt. Then authorize the narrow measurement packet and first request-neutral candidate. Begin with less wasted work, not more infrastructure.
