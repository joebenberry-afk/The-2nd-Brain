# Second Brain V3 — Final Requirements Baseline

**Version:** 1.0 adoption proposal  
**Prepared:** 24 September 2026  
**Status:** Ready to adopt as a development requirements baseline; not an implementation, independent code audit, deployment approval, push or tag.  
**Scope:** Local-first, orchestration-free memory/retrieval/context/skills/reuse/learning/storage.  
**Baseline:** User-reported completed and activated M00, with the external trust root still pending.

## Product definition

**Second Brain V3 is a low-overhead, source-backed memory and context system that reduces repeated discovery, repeated mistakes and unnecessary model work across native harnesses.** It should remember what is currently true, locate the evidence needed now, reuse valid prior work, and preserve useful knowledge across sessions without taking control of agent execution.

The success criterion is not a larger memory store, a particular vector database, a new orchestration service or a longer prompt. It is correct work completed with less total avoidable effort.

## Reading and authority

The historical research/roadmap inputs are dated **9 September 2026**. The user's subsequent **23–24 September 2026** orchestration-removal and M00 activation decisions take precedence where they conflict.

The user-reported activation identifies the qualified-m00 runtime, schema 28 and 116 retained memories. These are supplied operational facts, not a fresh inspection from this document. Existing VERIFIED claims remain at most TESTED/advisory. Skill review files remain unprotected, direct library model-outcome records remain informational, and independent signing/approval is unavailable. No clause here turns those residuals into demonstrated protected capabilities.

“Canonical” means the authoritative data representation for a record class; it does not mean the agent has independent permission-granting authority. “Validated reuse” means an applicability/evidence check, not creation of the unavailable VERIFIED grade. Host permission decisions always remain with the native host and its real authority.

Every requirement below is initially **NOT_ASSESSED**. Existing M00 implementations may satisfy one after a precise code/evidence mapping; do not rebuild a working feature just to match a new label. A requirement is not a claim that code already implements it.

## What changes from the earlier roadmap

| Earlier theme | Final treatment |
|---|---|
| More capable retrieval | Keep; add explicit current-state/supersession, query dilution, scope lineage and embedding migration requirements. |
| M02 lifecycle broker | Restrict to Brain's own runtime/process lifetime; no host-work broker. |
| M04 action/result cache | Keep dependency-checked evidence/artifact reuse; no cached side-effect execution or task-completion authority. |
| M08 executable procedural memory | Keep portable scripts/recipes/contracts executed by the native harness; remove a Brain workflow runtime. |
| M10 learned policies | Require the fixed-versus-learned experiment; deploy the winner, not a learned policy regardless of results. No model/provider or task routing. |
| M11 resource scheduling | Apply only to Brain-owned caches, indexes, maintenance and resource use; remove host-worker scheduling. |
| M12 portability | Begin contract tests immediately; final dual-host proof remains required. Host versions never define core authority semantics. |
| External issuer and cloud integration | Parallel/later tracks; neither delays local V3 development. |
| A chosen library becomes a milestone | Replace with capability and comparative evidence requirements. USearch is a candidate, not a definition of V3. |

## Non-negotiable exclusions

No orchestrator/coordinator, worker lifecycle, scheduling/reservations, task dispatch, agent/provider routing, retries, settlement, completion veto, forced continuation or equivalent control plane. No mandatory cloud deployment, private-memory Git upload, external signing installation, GPU, hosted embedding service, new graph database, custom ANN implementation, always-on LLM reflection, model-weight training or universal transcript replacement. Heavy multimodal retrieval, multi-vector models, neural/KV memory and broad distributed synchronization stay optional experiments.

These exclusions do not prohibit difficult useful research. They prevent incompatible or unproven implementation choices from becoming release prerequisites.

## Requirement register

All clauses below are core outcomes. Optional implementation experiments are classified separately after the register. “Shall” defines the proposed acceptance contract, not a claim of present compliance.

## 1. Architectural boundary

### ARCH-01 — Memory assistance, never host-work control

**Requirement.** Brain shall provide memory, retrieval, context, evidence, reusable artifacts and skill discovery. It shall not spawn, schedule, route, admit, veto, retry, continue, stop or settle host agent work, nor certify host-task completion. Brain may enforce access to its own data and limit its own resource consumption.

**Acceptance.** Exercise task start, delegation, normal completion, error and cancellation with Brain on and off. No Brain-controlled lifecycle decision, continuation response or obsolete worker tool remains. Include the reported Antigravity Stop path and stale Hermes worker surfaces.

### ARCH-02 — Stable core contracts

**Requirement.** Core behavior shall use normalized interfaces and capability negotiation. Host names, hook events, internal classes, versions and model/provider identities belong in adapters, not core semantics. Compatibility independence means adapting documented changes, not promising immunity to every breaking host change.

**Acceptance.** Run the same core fixtures through two host adapters; a compatible host update requires no core semantics change. Unknown capabilities degrade explicitly rather than being guessed.

### ARCH-03 — Bounded failure without interference

**Requirement.** Optional assistance shall time out and return without blocking native work. An explicit Brain query shall return a structured unavailable/error result rather than fabricate an empty successful search. Brain data permissions and unavailable authority remain fail-closed even when assistance is unavailable.

**Acceptance.** Inject a missing interpreter, locked database, broken index, slow encoder and malformed hook payload. The host remains usable, restricted data is not returned, and diagnostics identify the failing Brain component.

### ARCH-04 — No new infrastructure prerequisite

**Requirement.** The local V3 core shall not require a cloud account, external issuer, new database server, GPU, paid embedding API, always-on daemon or model training. Optional profiles may add dependencies only with separate measured benefit and an operational fallback.

**Acceptance.** Run the default profile offline on the existing 16 GB machine with optional dependencies unavailable. Exact/lexical retrieval and ordinary advisory memory remain usable.

## 2. Performance and honest economics

### PERF-01 — True no-benefit neutrality

**Requirement.** A genuinely no-benefit fresh request shall add zero Brain model-visible tokens, tool schemas, skill descriptions, management calls or status wrappers relative to a matched native baseline. A later turn retaining earlier useful Brain content is not a full-run zero-cost case.

**Acceptance.** Diff the actual model-facing requests and tool surfaces on held-out no-benefit cases. Report retained context separately. Include short prompts that do need memory to expose false abstention.

### PERF-02 — Whole-turn latency budgets

**Requirement.** The default no-benefit path shall target at most 10 ms median and 50 ms p95 incremental warm local blocking time, and at most 100 ms p95 incremental cold time to first dispatch. The allowance covers the entire turn, not each hook. These are adoption targets, not measured achievements.

**Acceptance.** Use repeated paired measurements with an inert-adapter control. Include startup, imports, locks and blocking finalization; separate cold and warm results. No hiding startup in an unreported warm-up.

### PERF-03 — All-in accounting

**Requirement.** Every optimization claim shall count query formation, embeddings, ranking, injection, tool expansion, validation, retries, maintenance, consolidation and paid model work. Separate logical tokens, cached input, output, observed money, elapsed time and local resources. Unknown usage remains unknown.

**Acceptance.** Reconcile non-overlapping spans and provider request identifiers. Compare task-level totals and lifetime/amortized totals; do not relabel task-agent-only savings as whole-system savings.

### PERF-04 — Optimize measured bottlenecks

**Requirement.** The first runtime work shall profile repeated bridge/process startup, discovery, configuration reads and unnecessary context before choosing a rewrite. Compare a reused-interpreter/in-host fast path with a bounded native prototype where justified. A language or backend is not itself a performance requirement.

**Acceptance.** An ablation identifies the source of the gain. The chosen implementation satisfies quality and latency gates against identical fixtures and hardware; a rejected native rewrite is a valid comparison outcome.

## 3. Memory representation and evolving state

### MEM-01 — Canonical records and rebuildable views

**Requirement.** Define canonical ownership for each record class: memories, source evidence, revisions, acknowledged events, dependencies and receipts. Derived lexical/vector indexes, summaries and caches shall be rebuildable. Do not assume every SQLite row can be reconstructed from tracked Markdown; prove rebuildability class by class.

**Acceptance.** Delete and rebuild only declared derived views and compare their supported answers. Backup/restore preserves non-rebuildable provenance and acknowledged state; unknown legacy provenance is not invented.

### MEM-02 — Typed, versioned, source-backed records

**Requirement.** Records shall distinguish observations, decisions, corrections, hypotheses, procedures, source locators and derived summaries. Store stable identity, revision, scope, source references, observed time, applicable time when known, evidence status and transformation provenance. Store claimed grade separately from effective authority.

**Acceptance.** Round-trip representative records without losing source, exact identifier, units, scope, uncertainty or temporal meaning. An imported legacy VERIFIED claim remains at most TESTED/advisory under the M00 boundary.

### MEM-03 — Explicit supersession and current-state views

**Requirement.** Represent correction, supersession and invalidation explicitly. A current-state query shall not silently resurrect a superseded fact. Historical/as-of queries shall remain possible. Newer timestamps alone do not prove truth, grant authority or resolve conflicting source claims.

**Acceptance.** Ingest a known sequence of decisions and reversals, including late-arriving old records. Current queries choose the supported current state; historical queries return the correct earlier state and provenance. Include removal of Brain orchestration as a real fixture.

### MEM-04 — Contradictions remain visible

**Requirement.** When evidence cannot resolve a contradiction, preserve competing claims and their scope instead of merging them into a confident statement. Separately track evidence strength, freshness, relevance, observed utility and authorization; one score must not stand in for all five.

**Acceptance.** Conflicting memories from two runs produce an explicit conflict or bounded advisory alternatives. Repeated retrieval, high similarity or self-reported success never upgrades authority.

### MEM-05 — Durability, retention and reconstruction honesty

**Requirement.** Acknowledge a memory write only after its declared durability contract is met. Preserve sufficient exact evidence for supported reconstruction under the configured retention policy. When source material was deleted, is missing or was never captured, disclose that limitation; a summary is not lossless raw evidence.

**Acceptance.** Fault-inject crashes before and after acknowledgment, retry duplicate events and replay partial segments. No acknowledged record is silently lost; unavailable source expansion returns a clear error.

## 4. Retrieval and source discovery

### RET-01 — Scope and lineage before disclosure

**Requirement.** Build the authorized candidate universe from project/worktree/recipient scope and explicitly permitted shared scope before ranking. Derived records shall inherit source restrictions; re-evaluate changed access at retrieval and expansion. Apply equivalent protection to cached snippets, summaries, embeddings and diagnostic output.

**Acceptance.** Attempt cross-project reads, restricted-source summarization into a shared record, revocation after caching and forbidden-ID expansion. No disallowed payload or revealing metadata reaches the recipient. This is an application data boundary, not protection from a same-user attacker controlling the OS.

### RET-02 — Prompt-dilution-resistant intent extraction

**Requirement.** Construct retrieval queries from the actual task and relevant structured cues, not indiscriminately from the full agent prompt. Preserve exact symbols, paths, IDs, errors, negation, numerical limits, temporal qualifiers and genuine new constraints. Deterministic extraction is the default; any model-assisted rewrite is optional and budgeted.

**Acceptance.** For meaning-equivalent concise and instruction-heavy prompts, retain the required evidence on named regression cases. Test logs, code and irrelevant boilerplate. Separately test appended instructions that genuinely change the task and must change retrieval.

### RET-03 — Selective multi-operator search

**Requirement.** Support exact identifiers, lexical/BM25, structured metadata and source relationships, with a real local semantic retrieval path and graceful lexical fallback. Choose the cheapest sufficient plan; do not run every operator for every query. Scope determines eligibility, not merely a score boost.

**Acceptance.** Compare lexical-only, exact-vector hybrid and ANN hybrid on a frozen corpus. Include paraphrases, exact errors, source-location requests, changed-state cases and no-answer queries. Semantic benefit and costs are reported separately from ANN benefit.

### RET-04 — Versioned embedding spaces

**Requirement.** Identify each vector space by encoder artifact/version, tokenizer and input template, dimensions, pooling, normalization, quantization and metric. Never compare incompatible spaces merely because their dimensions match. Migrations shall build and validate a new index before switching; rollback restores the matching encoder/index pair.

**Acceptance.** Mix same-size incompatible embeddings, interrupt a migration and change query instructions. The mismatches are rejected or isolated. Full reindex preserves source links and old/new writer-reader tests are recorded.

### RET-05 — Evidence-centered ranking and packing

**Requirement.** Compare fusion, reranking, deduplication, diversification and bounded relationship expansion without making every technique mandatory on the hot path. Prefer evidence that answers the question, not merely topically similar prose. Report conflicting or stale candidates and retain an exact-evidence expansion path.

**Acceptance.** Evaluate evidence recall, ranking quality, stale-answer rate, irrelevant-context rate, latency and tokens at the delivered packet budget. Test small authorized subsets, duplicate memories and valid exceptions that similarity would otherwise suppress.

### RET-06 — Automatic source-location catalogue

**Requirement.** Maintain a small discoverable catalogue of approved repositories, mappings, schemas, assets, reports and external-source locators with revision and access metadata. Retrieve the locator and inspect the underlying source when needed; do not duplicate entire domain databases inside Brain or inject the whole catalogue on every turn.

**Acceptance.** A held-out SZ-tools/Telemetry task locates the canonical mapping/definition source without a supplied path. A BasicUpscaler task finds its applicable research/evidence artifact. An unrelated project cannot see either without explicit sharing.

## 5. Context construction and continuity

### CTX-01 — Fidelity classes rather than uniform summarization

**Requirement.** Context construction shall distinguish exact material, structured facts, advisory summaries and expandable references. Preserve exact commands, identifiers, numbers/units, active task constraints and provenance where correctness requires them. Fidelity classification does not promote stored text to policy or authorization.

**Acceptance.** Repeatedly compress and reconstruct a test context containing exact values, quoted hostile instructions, superseded advice and active user constraints. Required details survive within the supported projection contract; uncertainty and source type do not disappear.

### CTX-02 — Recipient and context-epoch awareness

**Requirement.** Deduplicate by recipient, source revision, representation and observed context epoch. Past delivery is not proof of present visibility after host compaction or restart. Parent and child agents receive only context relevant and permitted to their own requests; Brain does not manage the child lifecycle.

**Acceptance.** An unchanged visible record is not appended repeatedly. A restart/compaction or source revision causes appropriate rehydration. Parent delivery does not suppress a needed child delivery or leak the parent packet wholesale.

### CTX-03 — Recover without controlling host compaction

**Requirement.** Preserve acknowledged Brain state and rebuild context when the host signals loss of visibility. Brain shall not veto compaction, block Stop, force continuation or manufacture a host completion decision. Unknown coverage shall be reported as unknown and reconstructed conservatively within budget.

**Acceptance.** Run actual compaction/restart on supported hosts and an unsupported-signal fixture. Native lifecycle remains unchanged and no claim of complete recovery is made when required evidence is unavailable.

### CTX-04 — Minimum sufficient and cache-conscious context

**Requirement.** Pack the smallest sufficient evidence view under an explicit token budget, with progressive expansion. Keep stable reusable prefixes where the adapter permits, without pretending cached tokens are free. Never silently drop a required qualifier just to meet a token target; report a partial view when exact coverage cannot fit.

**Acceptance.** Measure initial packet plus later expansion costs, not just the first response. Compare native/full-context/compiled-context controls and record fidelity, repeated injection and provider-cache behavior where observable.

## 6. Dependency-aware reuse

### REU-01 — Incremental knowledge dependencies

**Requirement.** Track how facts, source maps, summaries, skills and cached computations depend on source revisions and configurations. Invalidate affected derived views when inputs change and rebuild only what is needed. A compact dependency table/graph inside the existing store is acceptable; a new graph database is not required.

**Acceptance.** Change one dependency and prove affected views become invalid while unrelated views remain reusable. Cover source removal, corpus-membership changes and transitive derivatives.

### REU-02 — Freshness beyond commit IDs

**Requirement.** Reuse validity shall account for project/worktree identity, relevant dirty/staged/untracked inputs, environment/tool/configuration versions, schema and data revisions, permissions and requested time scope. Validation shall have a bounded cost; uncertainty causes revalidation or advisory-only return, not fabricated freshness.

**Acceptance.** Change an uncommitted file while HEAD stays fixed; switch worktrees; change a tool configuration and revoke source access. Stale results cannot be presented as current exact results.

### REU-03 — Reuse results, not side effects or success claims

**Requirement.** Brain may return a dependency-checked prior analysis or generated artifact. It shall not silently substitute a cached write, installation, command execution or task-success receipt for actual host work. The caller/native harness decides whether to use an artifact or execute a script.

**Acceptance.** A repeated read-only derivation reuses valid work. A prior successful mutation is never replayed, skipped or marked completed by Brain. Reuse records label provenance and validation time.

### REU-04 — Versioned positive and negative caches

**Requirement.** Cache keys shall include scope, source/index epoch, query plan and relevant capability versions. Negative results shall expire or invalidate on new evidence. Cache retention shall be bounded and caching may not preserve access after revocation.

**Acceptance.** After a miss, add the relevant memory and retrieve it immediately under the documented invalidation contract. Test scope switching, deletions, partial index rebuild and encoder changes.

## 7. Skills and learning from corrections

### SKL-01 — Portable, progressive skill packages

**Requirement.** Use Agent Skills-compatible packages where suitable: compact metadata, SKILL.md, and on-demand references/scripts/assets. Preserve existing useful skills. Do not register the entire library into every model prompt; metadata itself has a measurable cost. Support native discovery before inventing a competing skill catalogue.

**Acceptance.** A relevant skill is found and expanded on demand in two adapters; irrelevant skill instructions are absent. File format validation and total startup metadata costs are recorded.

### SKL-02 — Native execution, not a Brain workflow engine

**Requirement.** Procedural memory may produce ordinary scripts, recipes and input/output contracts that the user or native harness executes. Brain shall not implement a second workflow language, execution graph, coordinator, worker pool or retry controller. Static artifact checking and memory applicability checks remain in scope.

**Acceptance.** Three procedure families—source discovery/inspection, reproducible evidence/test collection, and read-only derivation/report generation—are packaged and exercised through native tooling with explicit dependencies and fewer repeated interpretation steps.

### SKL-03 — Applicability and unprotected-review honesty

**Requirement.** Skills shall state prerequisites, supported environments, known failure modes, examples and evidence references. The existing writable review file is not independent approval. Candidate skill text or scripts shall not acquire privileged execution or VERIFIED status through popularity, automatic export or a self-review.

**Acceptance.** Tamper with review metadata, age dependencies and insert a malicious instruction in a reference. No privileged authority is created; stale applicability is detected or explicitly unknown.

### SKL-04 — Negative experience and error-triggered help

**Requirement.** Capture useful corrections, failed assumptions and tool-calling pitfalls as scoped candidate knowledge, not merely success stories. Retrieve a small relevant correction when an error/task cue matches. Avoid permanent global bans derived from a single failed attempt.

**Acceptance.** A repeat-error workload uses the supported correction and avoids the original mistake, while a changed environment can invalidate it. Compare a concise correction against replaying the full failed transcript.

## 8. Consolidation and inexpensive learning

### LRN-01 — Selective, provenance-preserving consolidation

**Requirement.** Consolidation shall merge true duplicates, separate hypotheses from observations, preserve contradictions and extract reusable patterns from permitted evidence. Derived summaries retain source lineage and restrictions. Raw/evidence retention follows explicit policy; a generated summary is never declared mathematically lossless without proof.

**Acceptance.** Compare pre/post-consolidation answers on exact-fact, current-state, conflict and authorization fixtures. A bad consolidation can be reverted without losing acknowledged source records.

### LRN-02 — Evidence checking before relying on a learned claim

**Requirement.** For candidate memories intended to guide repeated work, support targeted read-only verification of relevant source paths, schema, API shape, units or procedure prerequisites. Use existing safe readers and explicit budgets; do not spawn a Brain-owned curator agent. No safe read surface means unsupported/unconfirmed, not guessed evidence.

**Acceptance.** A plausible but incorrect source locator or schema convention is detected before it is treated as a supported reusable fact. Verification cost and remaining validity scope are recorded separately from authorization.

### LRN-03 — Learn selectors only when they beat fixed ones

**Requirement.** Implement an offline comparison of fixed and learned retrieval/cache/consolidation selectors on training and held-out workloads. Deploy the cheapest selector that meets the contract. Learning concerns Brain assistance only, never model/provider routing or host task decisions. Successful empirical learning is desirable; a losing learned approach shall not block V3 if the required outcome is met by a fixed one.

**Acceptance.** Record a reproducible fixed-policy baseline, holdout results, full training/maintenance cost and promotion/rejection decision. No evaluation leakage, self-reported model-success authority or silent automatic policy promotion.

### LRN-04 — Bounded maintenance and measured payoff

**Requirement.** Maintenance and optional model-assisted consolidation shall use explicit limits and be disabled or postponed when unavailable. Account for their cost even when outside the response path. No endless reflection, paid research loop or untracked background work is part of the default runtime.

**Acceptance.** Run an interrupted/capped maintenance cycle and an idle session. Native work remains unaffected; pending work and dropped optional telemetry are explicit; claimed savings include amortized construction cost.

## 9. Storage and resource bounds

### RES-01 — Budgets by owned data category

**Requirement.** Track canonical payloads, derived indexes/caches, logs, reports, backups and development artifacts separately. Use content-addressed payload reuse and lossless compression where appropriate. Register byte, age and count budgets for managed categories before promotion; do not claim bounded storage merely because the SQLite file is small.

**Acceptance.** A growth workload demonstrates accounting and quota behavior for each managed category, including external output/worktree directories when registered. Canonical evidence is not silently deleted to satisfy a cache budget.

### RES-02 — Retention, deletion and lineage

**Requirement.** Retention shall distinguish reclaimable caches from pinned evidence, acknowledged state and recovery snapshots. Deleting/restricting a source shall propagate to dependent views and future retrieval. Already disclosed information cannot be recalled from a host context; report that limitation.

**Acceptance.** Purge a source and inspect summaries, embeddings, positive/negative caches and later expansion. Live/pinned recovery material remains protected; expiration and deletion receipts identify what was and was not removed.

### RES-03 — Safe maintenance and worktree cleanup

**Requirement.** Only explicitly Brain-managed, disposable artifacts may be automatically reclaimed. Use ownership manifests, dry-run reporting and live-reference checks. Never delete unknown/untracked user files, active worktrees, the active runtime or its only compatible rollback material.

**Acceptance.** Populate managed/unmanaged files, an active worktree and the reported leftover probe class. Cleanup touches only eligible owned objects. A full quota suppresses optional capture/maintenance, not host task execution.

### RES-04 — Measured 16 GB operating envelope

**Requirement.** Before promoting each profile, freeze numerical RAM, CPU, I/O, disk and maintenance-concurrency budgets on the user's 16 GB system. Include encoders and all Brain processes. Default GPU use is zero; optional semantic resources must unload/degrade according to the declared profile. Budget selection is an M01 deliverable, not an indefinite TBD.

**Acceptance.** Publish a versioned resource-profile manifest before holdout evaluation. Test native host co-use, cold load, idle, indexing and memory-pressure cases. Reject budget overruns rather than silently changing limits after seeing results.

## 10. Security and trust preservation

### SEC-01 — No authority laundering

**Requirement.** Preserve M00 refusals throughout create/search/merge/resolve/list/curate/consolidate/export/context paths. Agent-written approval, model-success claims, claimed VERIFIED grades and writable skill-review records remain non-authoritative. Facts, remembered user instructions and evidence references do not mint current permission.

**Acceptance.** Carry an unauthorized claim through repeated merges, summaries, retrievals and exports; it cannot become VERIFIED, project policy or critical completion authority. Preserve effective/claimed label separation everywhere.

### SEC-02 — Prompt-injection and metadata tests

**Requirement.** Treat retrieved content, tool outputs, filenames, project names and source metadata as untrusted data. Frame and escape them, preserve provenance and source role, and prevent them from altering scope/tool capability decisions. Framing alone is not a security guarantee; test downstream behavior and enforce data boundaries outside generated text.

**Acceptance.** Test direct and indirect injection, malicious names, quoted instructions, summary contamination and persistent poisoning in real hook/output paths. No source may expand its own permissions or execute a skill by being retrieved.

### SEC-03 — Explicit disclosure and sharing

**Requirement.** Cloud exports, Git commits of memory and cross-project shared packs shall be explicit, curated and traceable. Do not copy the entire live store or assume a private repository makes all content suitable for upload. Core local operation must not upload prompts, embeddings or memory without authorization.

**Acceptance.** Inspect outgoing requests and export manifests. A local-only profile performs no memory egress; excluded/private records are absent from exported packs and derived summaries.

### SEC-04 — Integrity is not independent authentication

**Requirement.** Unsigned chains/checksums shall be described as integrity mechanisms under their stated assumptions, not independent proof against a same-user attacker who can rewrite state and validation code. External issuer/custody/signing remain separate. No test suite or second model is itself an external root of trust.

**Acceptance.** Reports distinguish tested integrity checks from protected signatures and identify trust assumptions. Authority remains unavailable until separately qualified; no V3 acceptance claim quietly upgrades that status.

## 11. Portability and deployment

### PORT-01 — Two real hosts, shared semantics

**Requirement.** Qualify OMP and one additional existing local harness against the same core memory/retrieval contracts. Support Windows as the primary environment and exercise platform-neutral components on Linux. A cloud adapter is optional and not a release-start gate.

**Acceptance.** Use real sessions for at least two hosts with positive memory delivery, Brain-off controls, scope isolation, refusal preservation and unaffected native delegation. Adapter omissions are reported, not covered by simulated-host tests alone.

### PORT-02 — One runtime identity per active integration

**Requirement.** Bind every active entrypoint to the intended runtime and schema. Detect canonical-venv/environment-variable mismatches, stale plugins, gateways requiring restart and old hooks. Qualification shall enumerate actual entrypoints rather than assume an environment variable affects every host.

**Acceptance.** Invoke the real CLI, hooks and plugin entrypoints and record imported source identity. A mixed old/new runtime is detected; a gateway restart is evidenced when required.

### PORT-03 — Interoperate without protocol overreach

**Requirement.** Expose small stable memory/search/expand/skill interfaces through native hooks or standards-based adapters as supported. Agent Skills compatibility is useful now; MCP extensions require capability negotiation and actual host support. New protocol task/orchestration features do not authorize Brain task management.

**Acceptance.** Unsupported extension capabilities cleanly fall back or remain unavailable. The adapter adds no forbidden lifecycle control and no unused global tool surface in the strict no-op profile.

### PORT-04 — Current-state-safe upgrade and recovery

**Requirement.** Migration, backups and rollback shall preserve the latest acknowledged work. Keep derived index migration separate from canonical schema migration. Prefer forward repair or a compatible M00-based recovery path over restoring an old vulnerable runtime; label any emergency security regression explicitly.

**Acceptance.** Rehearse upgrade and failure on disposable production-like copies, then bind live acceptance to the same bytes when authorized. Recovery does not silently discard post-backup memory or reinstate SEC-AUTH authority.

## 12. Evaluation and finite release acceptance

### VAL-01 — Strong matched controls

**Requirement.** Compare native host, inert Brain adapter, activated M00 baseline and V3 candidate with matched model, effort, tools and data. Where relevant and available, include the host's native memory/skills configuration as a strong control rather than an artificially impoverished baseline.

**Acceptance.** Each report includes configuration fingerprints, source/corpus snapshots, randomization/order, all failures and cold/warm/cache conditions. Do not compare a better model in the candidate to a weaker model in the control.

### VAL-02 — End-to-end and multi-session workloads

**Requirement.** Evaluate real developer tasks across Brain, BasicUpscaler and SZ-tools/Telemetry, plus synthetic controlled cases. Include multi-session state changes, changed dependencies, exact IDs, prompt dilution, no-benefit turns, repeat corrections, compaction, cross-project denial and missing sources.

**Acceptance.** Publish held-out task families and memory queries before promotion. Measure correct task completion, current-state accuracy, repeat-mistake rate, evidence coverage, total tokens/time and resources, not only retrieval recall or unit-test count.

### VAL-03 — Diagnose the failing stage

**Requirement.** Separate capture/construction loss, stale-state resolution, query/candidate retrieval, reranking/packing and model interpretation. Use explicit gold-evidence and raw-source diagnostic controls where feasible. Do not respond to every retrieval failure by adding a larger encoder.

**Acceptance.** For a failed case, compare normal retrieval, known correct stored evidence and raw evidence under a fixed reader. The report identifies which stage the intervention implicates without claiming a universal causal proof.

### VAL-04 — Predeclared gates and independent review

**Requirement.** Freeze benchmark snapshots, resource limits, quality margins and material-improvement thresholds before evaluating held-out results. Deterministic security, source-validity and acknowledged-state fixtures must all pass. Evaluate stochastic task results with appropriate uncertainty and changed-path independent review.

**Acceptance.** No post-hoc removal of failing cases, relaxed threshold or suppressed startup cost. Zero observed failures is reported as a tested result, not proof that future failures are impossible.

### VAL-05 — Finite V3 boundary

**Requirement.** V3 requires useful retrieval, current-state memory, safe reuse, faithful continuity, portable host-executed skills, selective consolidation, bounded resources and demonstrated net benefit under shipping defaults. Optional techniques receive a disposition: promoted, rejected, deferred or blocked. A named algorithm losing a comparison does not create a new prerequisite module.

**Acceptance.** The final matrix maps every core requirement to code/evidence or a stated unmet condition. No unchecked core outcome is relabeled optional merely to declare completion, and no new paper automatically reopens scope.

## 13. Mandatory comparisons; conditional implementation choices

| Experiment | Required comparison | Promotion rule | Valid losing outcome |
|---|---|---|---|
| E01 Runtime fast path | Current path versus reused-interpreter/in-host and a justified bounded native prototype | Meets whole-turn no-op and resource targets | Keep the simpler implementation when the native rewrite does not help. |
| E02 Semantic retrieval | Lexical/structured baseline versus compact local encoders and exact-vector hybrid | Improves declared paraphrase/evidence workloads within resource and token budgets | An encoder may be rejected; lexical fallback remains. V3 still needs a demonstrated useful local semantic capability, not merely an unused interface. |
| E03 ANN acceleration | Exact-vector search versus USearch HNSW using the same encoder, corpus, filters and ranking | End-to-end benefit at the declared corpus scale without unacceptable retrieval loss | Ship exact search for small corpora and leave ANN off. |
| E04 Ranking/context | Simple fusion and deterministic packing versus reranking/diversification/alternative representations | Improves delivered evidence or total task economics | Leave the expensive stage off when it does not repay cost. |
| E05 Learned selectors | Fixed selectors versus offline-learned retrieval/cache/consolidation policies | Held-out improvement after training and maintenance cost; review before promotion | Ship the fixed selector and record the learned approach as rejected. |
| E06 Skills and consolidation | Concise packages/corrections versus full-trace replay and strong native tooling | Fewer repeated mistakes or interpretation calls without quality regression | Reject an unhelpful recipe or summarization mechanism, not the entire requirement for useful reusable knowledge. |

Initial encoder shortlist: EmbeddingGemma and Qwen3-Embedding-0.6B, plus a smaller existing compatible encoder where available. Their release dates are 2025, not new September 2026 launches. USearch 2.26.2 was listed as the current PyPI release when checked, dated 31 August 2026. These names are research candidates, not hidden dependencies. [S07–S10]

An ANN engine accelerates vector neighbor lookup; it does not supply embeddings, correct a diluted query, establish scope, distinguish current from superseded facts, or preserve authority. At the last reported 116 logical memories, exact search deserves the first baseline. The actual source/chunk corpus may be much larger and must be measured rather than inferred from the memory-row count.

For optional multimodal work, preserve typed source locators and resource metadata now. Do not add a multi-billion-parameter image/video model to the default 16 GB profile merely because a capable release exists.

## 14. Minimal stable data contracts

These are semantic contracts, not instructions to create a new protocol or replace existing types wholesale.

**SourceRef:** stable identity; revision/content digest; project/access scope; path/URI or source-system identifier; relevant span; availability; evidence role. A path is a locator, not itself proof that content is current or authorized.

**MemoryRecord:** identity/revision; record type; concise content; exact fields when required; source references; derivation lineage; observed/applicable times; supersession/conflict links; evidence status; claimed/effective trust; retention class.

**RetrievalRequest:** supplied task context; host-observed project/worktree/recipient identity; explicitly permitted shared scopes; current/as-of intent; exact cues; token/time budget; context epoch when observed. Agent-supplied strings do not create privileges.

**RetrievalPacket:** scoped source-backed items; provenance; effective advisory/evidence status; partial/conflict/staleness markers; expansion handles; packet cost; optional out-of-band diagnostics. A no-benefit hook returns no model-facing packet. An explicit failing query returns an error, not false success.

**DerivedArtifact:** source/input/environment dependencies; applicability conditions; creator/transformation version; artifact digest; last validation; invalidation reason. It cannot stand in for an actual side effect.

**SkillPackage:** native-compatible metadata; SKILL.md; on-demand scripts/references; inputs/outputs; prerequisites; known failure modes; evidence and version. Review metadata is not a protected signature.

**ContextReceipt:** recipient; context epoch; source revision; representation; observed delivery/visibility limits. It describes Brain content, not host-agent task settlement.

**ResourceProfile:** numeric per-profile budgets for RAM, CPU, storage categories, maintenance concurrency and deadlines; scope of accounting; measured hardware; defaults; fallback behavior. M01 freezes these values before a profile's holdout evaluation.

## 15. Acceptance targets and measurement rules

| Area | Baseline requirement |
|---|---|
| No-benefit fresh input | Zero extra Brain messages, tool schemas, skill descriptions or model/management calls in the strict default profile. |
| Warm whole-turn local overhead | At most 10 ms median and 50 ms p95 incremental blocking time. |
| Cold incremental overhead | At most 100 ms p95 to first dispatch, measured separately. |
| Deterministic security/state fixtures | All declared fixtures pass; zero observed forbidden disclosure, authority promotion, stale exact reuse or acknowledged-state loss in that suite. This is not a universal guarantee. |
| Named dilution regression | Required source is recovered for meaning-equivalent concise/long cases; changed real constraints are respected. |
| Semantic/ranking quality | Predeclared held-out quality and no-answer margins against the lexical baseline. Do not invent a universal percentage from another paper. |
| End-to-end benefit | Demonstrated net reductions in avoidable tokens and completion time on declared useful-memory workload classes, with quality non-inferiority. Report classes separately. |
| Resource envelope | Numerical limits fixed by M01 on the actual 16 GB laptop, including optional encoder costs; default requires no GPU. |
| Portability | Real OMP plus one additional local host; platform-neutral components exercised on Linux. |
| Deployment | Exact runtime identity, migration/recovery rehearsal, changed-path review and separate authorized live promotion. |

The latency figures are inherited proposed engineering targets from the 9 September performance charter, not present performance claims. Resource numbers beyond these latency targets must be measured and frozen as the first implementation deliverable; this document deliberately does not pretend to have measured the local machine.

Use stratified held-out cases, paired/interleaved repetitions, explicit failure/timeout accounting and confidence intervals appropriate to the claimed effect. An improvement smaller than the experiment can resolve is **inconclusive**, not a success. More retrieval recall is not automatically better task correctness; more compression is not automatically lower total cost.

For ANN scaling, include the current full eligible corpus and justified larger fixtures (for example 1k, 10k and 100k chunks) within available resources. Synthetic vector timing does not replace tests using real text, restricted subsets, tombstones and index updates.

## 16. Delivery slices and old-module traceability

Do not renumber historical M00–M13 evidence just to adopt this requirements document. The S labels below are delivery slices, not a new set of serial prerequisite subsystems or calendar promises.

| Slice | Existing modules principally covered | Shippable result |
|---|---|---|
| S1 — Fast, observable, non-interfering Brain | M01, M02; minimal M03/M12 contracts; remaining no-orchestration cleanup | Matched controls, runtime identity census, no-op fast path, prompt-dilution regression and bounded failure. |
| S2 — Useful current-state retrieval | M03, M05, M06; necessary M04 dependencies | Structured current-state records, source discovery, task-focused query formation, exact/lexical plus local semantic retrieval. ANN ships only if earned. |
| S3 — Safe reuse and continuity | M04, M07 | Dependency invalidation, reusable read-only artifacts, minimal context, recipient-aware rehydration and compaction recovery. |
| S4 — Reusable skills and measured learning | M08, M09, M10 | Native-executed skill packages, corrections, bounded evidence checking/consolidation, and a documented fixed-versus-learned selector result. |
| S5 — Integrated qualification | M11, M12, M13 | Resource/retention growth tests, real second-host proof, migration/recovery and all-in task economics under shipping defaults. |

Storage budgets, privacy, authority preservation and adapter contracts begin in S1; S5 is their cumulative proof, not the first time they are implemented. Source/state and retrieval prototypes can proceed as compatible vertical slices after measurement/contracts exist. Do not delay all useful retrieval behind a complete general-purpose memory graph.

M00 stays completed under its recorded external-trust-root boundary. Confirm residual hook/plugin cleanup as a narrow changed-path task; do not reopen the whole M00 campaign merely to re-label it. The missing historical module documents need not be recreated as a prerequisite to the first V3 implementation slice.

## 17. Finite definition of done

V3 is ready for owner-authorized promotion when the core register is evidenced, the shipped operators satisfy their registered comparisons, and real tasks demonstrate the intended value. The user should experience fewer repeated source hunts, fewer repeated known errors, correct current-state recall, dependable continuity and less unnecessary context without native task interference.

A library installation, green unit tests, a benchmark screenshot or a successful parent-memory canary alone does not establish this. Conversely, an unhelpful ANN/learned/multimodal experiment does not make V3 incomplete when a simpler shipped mechanism satisfies the corresponding core outcome.

New findings after adoption go to a change log. Only an actual correctness/security/compatibility blocker or a bounded, demonstrated high-value replacement changes the release contract. Neither “a new paper exists” nor “one more framework may help” is a reason to stop V3 development.

## 18. Evidence and source register

**P1 — Current conversation.** User-supplied M00 activation and operational reports, 23–24 September 2026; orchestration-removal decision and cloud deferral. Accepted as supplied context; no Windows runtime or repository was re-audited while producing this document.

**P2 — Historical project file.** `00_MASTER_ROADMAP.md`, dated 9 September 2026, version 1 retrieved from the personal Library. Original M00–M13 structure, incremental reuse and performance goals; conflicting orchestration/workflow/worker provisions are superseded here.

**P3 — Historical project file.** `Second_Brain_v3_Performance_Charter_PROPOSED_2026-09-09.md`, version 1 retrieved from the personal Library. No-op contract, proposed latency targets, full accounting and measured promotion.

**P4 — Historical project file.** `Second_Brain_v3_Architecture_Research_and_Synthesis_2026-09-09.md`, version 1 retrieved from the personal Library. Source-backed incremental views, selective retrieval and context representation; historical performance reports are not current measurements.

The external sources below were checked on 24 September 2026. This was a targeted relevant-source review, not an exhaustive search or a reproduction of any external experiment. Published results are evidence for hypotheses and failure modes, not promised Second Brain gains.

**S01 — Can Agent Memory Systems Track Evolving State?.** 2026-08-20. Research paper; methods and limitations inspected. Explicit supersession and state tracking; do not copy its costly per-turn extraction pipeline.

Source: `https://arxiv.org/html/2608.19652v1`

**S02 — The Compaction Cliff in Long-Running AI Agent Memory.** 2026-08-24. Public author version; abstract and selected methods/limits inspected. Fidelity-aware context handling; not a license to restore Brain policy authority.

Source: `https://arxiv.org/html/2608.22752v1`

**S03 — Agent Memory Is a Surface for Endogenous Authorization Laundering.** 2026-09-01. Research paper; abstract and full-text sections inspected. Test authority preservation across transformations, not only direct memory writes.

Source: `https://arxiv.org/html/2609.01836v1`

**S04 — Does Your Agent's Memory Survive a Model Upgrade? A Controlled Study of Memory Portability.** 2026-09-04. Under-review study; 48 synthetic histories and two sub-10B models. Retain source evidence; test writer/reader changes and isolate embedding spaces. Not proof that all memory needs a graph database.

Source: `https://arxiv.org/html/2609.05339v1`

**S05 — Grounding Agent Memory: Environment-Probing Curation for Enterprise Agents.** 2026-09-10. Research paper; methods and cost accounting inspected. Targeted read-only checking of candidate knowledge; account for curation separately and in total. Do not import its agent lifecycle.

Source: `https://arxiv.org/html/2609.11060v1`

**S06 — AkasicMEM: Governed Enterprise Memory for Agents.** 2026-09-22. New architecture paper; sections on lineage and evaluation inspected. Preserve source restrictions through derived memory. Architecture proposal, not a reproduced local performance result.

Source: `https://arxiv.org/html/2609.25563v1`

**S07 — USearch 2.26.2.** 2026-08-31. Maintainer package release metadata; current docs inspected. Candidate exact/ANN vector backend; package availability is not evidence of an end-to-end Brain speedup.

Source: `https://pypi.org/project/usearch/`

**S08 — USearch documentation.** Accessed 2026-09-24. Official implementation documentation. Exact and approximate search, serialization, memory-mapped views and filtering. Pin and test the selected binding.

Source: `https://unum-cloud.github.io/USearch/`

**S09 — Introducing EmbeddingGemma.** 2025-09-04. Official Google release announcement; current model docs also checked. Compact local encoder candidate; 308M parameters and flexible 768-to-128-dimensional representations. Vendor device benchmarks are not laptop measurements.

Source: `https://developers.googleblog.com/introducing-embeddinggemma/`

**S10 — Qwen3 Embedding and Qwen3-Embedding-0.6B.** 2025-06-05. Official release and model card. Alternative compact text encoder; compare precision, query preparation, load time and resident working set on the actual workload.

Source: `https://huggingface.co/Qwen/Qwen3-Embedding-0.6B`

**S11 — Agent Skills specification.** Accessed 2026-09-24. Official format specification. Progressive disclosure of metadata, instructions and resources. Metadata is not zero-cost.

Source: `https://agentskills.io/specification`

**S12 — Model Context Protocol 2026-07-28.** 2026-07-28 specification. Official protocol and linked working-group material. Stable adapter/capability negotiation. A linked Skills-over-MCP working group is not evidence that every host ships it.

Source: `https://modelcontextprotocol.io/specification/2026-07-28`

**S13 — MemoryArena.** 2026-02-18. Benchmark paper; abstract and project description inspected. Multi-session tasks with interdependent experiences are a stronger memory test than isolated QA.

Source: `https://arxiv.org/abs/2602.16313`

**S14 — AMA-Bench.** 2026-02-26. Benchmark paper; abstract inspected. Evaluate machine-generated tool/environment trajectories as well as conversation recall.

Source: `https://arxiv.org/abs/2602.22769`

**S15 — Agent Memory Distillation.** 2026-08-07. Research paper; abstract inspected. Hierarchical reusable examples and error-triggered function guidance are experiment candidates, not permission for Brain-controlled student/teacher agents.

Source: `https://arxiv.org/abs/2608.07169`

**S16 — SimpleMem.** 2026-01-05. Research paper and author release notes inspected. Structured memory and selective consolidation reinforce existing directions; no wholesale store replacement is required.

Source: `https://arxiv.org/abs/2601.02553`

**S17 — Claude Managed Agents memory stores.** Accessed 2026-09-24. Official product documentation; beta API documentation. Native/product memory is a relevant comparison. Managed Agents is not automatically the same product or credit entitlement as Claude Code cloud.

Source: `https://platform.claude.com/docs/en/managed-agents/memory`

