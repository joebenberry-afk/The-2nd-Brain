# Second Brain v3 — Architecture Research and Synthesis

## From remembered text to reusable computation

**Research date:** 9 September 2026  
**Status:** Research synthesis and proposed architecture. Not an implementation result, production promotion, or authorization to modify the live installation.  
**Hardware baseline:** The user's confirmed 16 GB system RAM. A previously reported RTX 5070 Ti Laptop GPU is treated as optional, unprobed hardware; neither its free memory nor safe sustained compute capacity was measured here.  
**Project baseline:** Canonical Scout Spec and Idea Ledger read from connected Google Drive; selected repository sources inspected at `6baea51b0be3ac7108ca6deafe5665ab8cca0852`. That snapshot is not assumed to be the user's installed runtime.

> **Strong goal:** Make experience change the amount of computation needed for future work. Build a memory runtime that can preserve exact evidence, construct useful representations, reuse valid results, retrieve missing information, and execute learned procedures without repeatedly asking a large model to rediscover the same facts or coordinate the same steps. Preserve model and harness portability. Treat engineering difficulty as a challenge, not an exclusion criterion.

The previous performance charter specified an outcome: negligible no-op overhead, zero unnecessary model tokens, and net savings on meaningful work. This dossier proposes machinery that could achieve that outcome. Its central recommendation is an **evidence-backed incremental memory compiler**: one durable source of truth, multiple rebuildable memory views, a dependency-aware reuse engine, and a small runtime that materializes only the information or computation a task actually needs.

“Compiler” here is literal in the engineering sense. Rich source material and successful execution traces are transformed into indexed facts, source maps, cached query plans, bounded context representations, and executable procedures. Those outputs carry dependencies and validity conditions. They can be rebuilt, checked, shared, and invalidated without replaying an entire conversation.

## Reading map

Sections 1–2 separate project evidence from external research. Sections 3–7 specify the proposed memory representation, execution boundary, retrieval planner, context compiler, and procedure compiler. Sections 8–10 connect biological memory, offline policy learning, and speculative preparation. Sections 11–12 distinguish hosted-model access from hardware feasibility. Sections 13–16 provide worked examples, reconciliation with earlier decisions, experiments, and build order. The final registers identify internal evidence and external sources.

## Executive synthesis

The strongest direction is not a larger pile of memories or an additional intelligent supervisor on every turn. It is a combination of **incremental computation, selective multi-view retrieval, procedural compilation, and offline learning**.

The most consequential proposals are:

1. **A memory build graph.** Treat facts, indexes, summaries, plans, and verified results as derived computations with explicit dependencies. Recompute only the affected portion when a source changes.
2. **A compiled local fast path.** Replace repeated cold bridge startup with an in-host or native decision path over an immutable snapshot. Use a reusable, lifecycle-owned service for operations that need richer state or durable writes. Keep one canonical authority.
3. **A retrieval query optimizer.** Combine exact references, lexical search, code structure, local semantic embeddings, time, and relations, but choose a plan instead of executing every technique for every request.
4. **A context compiler.** Preserve exact evidence out of context; construct a task-specific representation with explicit fidelity requirements, source references, and recipient/context-epoch tracking.
5. **Executable procedural memory.** Turn validated recurring workflows into typed, effect-aware programs with semantic model calls only where judgment remains necessary.
6. **A fast-learning/slow-consolidation loop.** Record experience cheaply, then spend more effort selectively on representations and procedures likely to be reused. Distill expensive research into cheap runtime decisions.
7. **An experimental neural tier.** Study learned memory policies, small local models, and model-specific activation memories without pretending that an external harness can alter an opaque hosted model's internal memory.

These are proposed combinations, not claims of scientific novelty or guaranteed performance. Several ingredients already exist in the v1/v2 design. V3's substantive change would be their execution model: dependency-tracked, compiled, amortized, and selected according to measured task value.

## 1. Evidence, scope, and the actual problem

### 1.1 What was examined

The research crosses agent memory, retrieval, inference systems, databases, incremental compilers, cache management, program synthesis, reinforcement learning, neuroscience, cognitive psychology, and information theory. The reference register contains 61 primary papers, author reports, official implementations, and official documentation. Inspection depth varies: core proposals use method/limitation sections and implementation excerpts; some alternative systems were screened at abstract level.

The requested Deep Research plugin was discovered as installed, but discovery did not expose an invocable research action. Research was conducted directly with web and connected project tools. No independent reproduction of an external paper, local laptop benchmark, model training, or paid research campaign occurred in this response.

Use three evidence categories throughout:

- **Observed project evidence:** files and reports actually read. Historical reports remain historical.
- **Published evidence:** authors' findings on their own workloads. These establish plausibility and failure modes, not the magnitude of an improvement in Second Brain.
- **Proposed synthesis:** the design and experiments in this document. Their success is unknown until implemented and evaluated.

This is a broad, representative search, not an assertion that every AI publication or every current memory product has been exhaustively evaluated.

### 1.2 What the historical latency result does and does not establish

The historical arithmetic comparison records 3.99 seconds without the extension and 10.53 seconds with it, alongside 33,082 versus 33,221 total tokens. The native arm already had substantial token usage; the whole 33K is not Brain overhead. The difference of 139 total tokens is not a direct measurement that Brain injected exactly 139 tokens. [R01]

The latency report identifies repeated process startup and a roughly 242 ms package/CLI startup measurement, but does not causally explain the complete wall-clock gap. Any investigation must separate extension discovery, initialization, retrieval, locks, provider calls, and finalization. Routing and provider spans might overlap; distinct request identities are needed before declaring an extra model call. [R02]

The objective is therefore not simply to reduce a prompt by 139 tokens. It is to redesign the local computation and inference boundaries so irrelevant memory work is absent and useful work can be reused.

### 1.3 Existing foundations should not be mistaken for missing features

The inspected Action Cache already classifies dependencies and records validation economics. VMem already distinguishes residency from durable recovery. Retrieval already exposes a cascade and diversity logic. These are real places to attach v3 research. However, comments claiming sub-millisecond behavior, vector tiers, or a fixed fraction of short-circuited queries are not measurements or proof that those paths are active. [R03–R05]

The canonical documents already include earned memory, reconsolidation, strategic forgetting, causal credit, procedural engrams, teacher/student transfer, and a Cortex/Brainstem split. Repeating their names is not a v3 breakthrough. The proposals below change how those ideas are represented and executed. [R06–R07]

## 2. What the literature says—and where it disagrees

### 2.1 There is no evidence-backed universal winner

EvoMemBench compares knowledge-oriented and execution-oriented memory within and across episodes. Its results show that useful memory form depends on the task; irrelevant retrieval, missing execution detail, and mismatched transfer can hurt. Strong long-context controls remain important. This is evidence for a portfolio selected by task, not justification to abandon memory. [E01]

The design implication is to optimize the **decision process**, not the name of the memory system. “Always graph,” “always vector,” “always summarize,” and “always use a memory agent” are all suspect defaults.

### 2.2 Structured facts and rich episodes solve different problems

SimpleMem emphasizes structured, compact representations and adaptive retrieval. Hindsight separates types of memory and uses complementary retrieval channels. HippoRAG 2 develops associative retrieval using a graph with passage context. E-mem supplies an important counterpoint: reconstruction from richer episodes can preserve details that fact extraction removes. [A01–A03, A08]

I would combine them rather than choose a side. A fact index should be a **view over an episode or artifact**, not its replacement. An entity graph should preserve links to the passages that support its edges. An extracted fact should state where it came from and how it can be invalidated.

### 2.3 Low online cost can conceal expensive preparation

LightMem explicitly distinguishes online savings from total costs through filtering, short-term organization, and sleep-time updates. Sleep-time Compute studies preparation before immediate queries. These support investing in reusable representations, but the preparation must be included in lifetime economics. [A04, P13]

For this project, expensive construction is acceptable when it has a credible reuse horizon. It is not acceptable to call an operation free merely because it finishes after the visible answer or before the benchmark timer starts.

### 2.4 The strongest memory may be a procedure

Memp treats reusable procedures as a distinct memory form. ProcMEM examines activation, execution, and termination of procedural knowledge. LLMCompiler moves tool execution toward dependency-graph scheduling; RLMs move large inputs outside the main prompt into an inspectable environment. These point toward remembering **how to perform a class of work**, not merely remembering the final prose answer. [P01–P02, P07, P09]

The design opportunity is larger than storing a skill file. A procedure that still requires a model to reinterpret every step retains much of the original coordination cost. A checked executable representation can remove that repeated interpretation.

### 2.5 Comparison map

| Research family | Mechanism worth borrowing | What not to import uncritically |
|---|---|---|
| SimpleMem / Mem0 | Selective extraction and compact reusable facts | A claim that semantic compression preserves every future-relevant detail |
| Hindsight / Zep | Separate memory types, time-aware retrieval, evolving entity state | An entire server stack or unverified summaries treated as unquestionable truth |
| HippoRAG 2 | Associative search over relations while retaining passage evidence | An expensive online LLM filter on every simple query |
| A-MEM / OpenViking | Linked organization and multiple levels of detail | Continuous broad rewriting or a literal filesystem required for the metaphor |
| E-mem | Rich episode recovery | A separate coordinating agent for every retrieval |
| LightMem / Sleep-time Compute | Move reusable preparation away from immediate response time | Unaccounted maintenance cost or unnecessary constant background work |
| Memp / ProcMEM / ACE | Retain and improve procedures | Replaying a growing playbook into every context |
| GEPA / MemEvolve / Memory-R1 | Learn memory operations and selection strategies from outcomes | A costly learned supervisor running on every lifecycle event |
| Build systems / Salsa | Dependency-tracked computation and change-sensitive reuse | Assuming a hash of one file proves a whole result remains valid |
| Database query optimizers | Choose where and how to perform operations | Treating probabilistic semantic operations as exactly interchangeable SQL expressions |
| Cartridges / Titans / TTT / Engram | Alternative locations and mechanisms for learned memory | Assuming access to the internals of a hosted frontier model |

Sources: [A01–A11, C01–C02, C06–C09, P01–P08, P13, N05–N08].

## 3. The proposed system: one authority, multiple compiled views

### 3.1 The central representation

A proposed `MemoryObject` should express information that ordinary transcript text does not make reliable enough for reuse:

```text
identity: object_id, revision, project/scope, source_kind
source: artifact_ref, content_hash, source_span, producing_event
meaning: object_kind, subject, claim/procedure/obligation
status: observed | inferred | verified | disputed | superseded
validity: observation_time, valid_interval, dependency_refs
authority: origin, permitted_use, approval_reference
views: exact | structured | extract | summary | embedding | executable
execution: preconditions, effects, termination, verification_contract
residency: recipient_id, context_epoch, delivered_revision
```

This is a proposed logical schema, not a demand to place every field on every small object. Use typed variants and compact identifiers. Different views remain derived from the same source; an embedding is not a second owner of truth.

Distinguish the time an event was observed from the time a claim is considered valid. A late-arriving historical result must not silently overwrite a newer state merely because it was imported later. A conflict becomes an explicit relationship, not an averaging operation.

### 3.2 The dataflow

```text
source files / tools / user corrections / verified execution
                       |
             canonical evidence and events
                       |
           dependency-tracked memory build graph
              /         |          |          \
        source map   fact views  context views  procedures
              \         |          |          /
                published versioned snapshot
                       |
request + task state -> local plan selector
                       |
         reuse / retrieve / compile / pass through
                       |
       minimal model input or checked execution
                       |
       new evidence -> incremental invalidation
                       |
         selective consolidation and learning
```

The main model is a semantic decision engine within this process, not the process manager for every deterministic operation.

### 3.3 A build graph, not just a cache

Build systems and Salsa provide a useful distinction: an input changing does not necessarily mean every downstream answer changed. Dependencies can be re-evaluated and unchanged intermediate results retained. [C01–C02]

Applied to Brain, a graph might look like:

```text
source bytes -> parsed symbols -> source-location map
                         -> dependency edges -> affected test selection
verified test run -> result object -> current status view
source-location map + current task -> retrieval plan -> context projection
```

A changed comment may require reparsing but leave a symbol-location-independent dependency result unchanged. A new file may invalidate a previously empty search. An altered tool version may invalidate a procedure's verification even when its input files are identical.

This is the first major synthesis: **memory becomes incremental computation whose outputs can be reused with evidence of continuing validity**.

### 3.4 Negative knowledge requires dependencies too

“No matching dump exists” depends on the searched catalogue and filters, not just the files that were found. “No relevant memory exists” depends on corpus membership, scope, ranking configuration, and relevant index versions.

Therefore, negative results need dependency objects for directories, source registries, or query domains. Otherwise a fast negative cache can make new knowledge invisible. This is particularly important for the user's automatically discovered mappings, assets, and dumps.

### 3.5 The practical freshness strategy

Use change events to maintain versions cheaply, but treat dropped events, overflow, process restart, and inconsistent source identity as uncertainty. Uncertain state triggers authoritative reconciliation before consequential reuse. Do not turn an unreliable watcher into a false proof of freshness.

Use immutable snapshots for concurrent readers, and publish a new snapshot only after the relevant derived state is complete. Keep original artifacts and durable events recoverable. SQLite provides relevant transactional and snapshot mechanisms, but its WAL design still has one writer and requires disciplined checkpointing. [C04–C05]

A read-only snapshot shared with an adapter is a cache, not a new canonical database. The writer and migration authority remain explicit.

## 4. Native execution and a real near-zero-cost path

### 4.1 Why native code is a serious candidate

The earlier charter was right not to assume that rewriting everything would help. It was too conservative if read as a reason not to investigate a native kernel. The measured startup floor makes process lifetime and the execution boundary legitimate architectural questions. [R02]

I recommend a three-way prototype, all using the same logical contract:

| Candidate | Shape | Question it answers |
|---|---|---|
| Reused Python runtime | One lifecycle-owned broker, cached imports/configuration, combined requests | How much is simply repeated cold startup? |
| Native core with thin host binding | Rust or equivalent core over compact immutable snapshots; broker for writes/heavier work | How small can the actual decision and context-compilation path become? |
| Sandboxed compiled core | A compatible WebAssembly component where the host supports it | Can one compiled semantic core remain portable without unacceptable binding overhead? |

Do not implement all three as permanent state owners. They are alternatives to compare. Native compilation is favored for investigation, not presumed to win every workload. The result must include cold startup, resident memory, sustained operation, and adapter compatibility.

### 4.2 Separate immediate decisions from deferred preparation

The immediate path should be able to resolve project identity, inspect current task state, match relevant event cues, and consult a small index without starting a large process. It should then either return an already-valid action/context result or request a richer operation from the reusable runtime.

The slow path may parse a changed repository, construct embeddings, consolidate a new episode, or train a policy. Those are real capabilities, not prohibited because they cost more. They simply should not be prerequisites for a trivial self-contained response.

A session-owned broker can stay available while a root task and its workers run, then stop when idle or explicitly released. Avoid a separate heavy process per worker. If future measurements justify a longer-lived broker, that is an explicit deployment choice rather than an accidental daemon.

### 4.3 Exact no-op semantics

A no-op must preserve the actual model-facing request, not merely return a message saying that no memory was found. Extra tool descriptions, extension instructions, empty wrappers, and a model call to decide relevance all count as overhead.

This creates a real integration challenge: a harness that always exposes Brain-specific tool schemas may not support strict request equality without deferred discovery or interception of existing tools. That is a capability question to test, not something a prompt can solve. Native deferred tool discovery is worth considering where the host exposes it. [P11]

A short request is not necessarily irrelevant. “Continue” may require a saved objective, open obligations, or the last verified action. The gate must use task state and cues, not prompt length alone.

### 4.4 Failure should not turn into an unbounded wait

For optional memory enrichment, an unavailable broker should lead to an explicitly recorded degraded path with bounded waiting. Required recovery state and authorization are different: their absence can block a consequential action rather than silently remove a protection.

Both behaviors belong in executable contracts. They do not require extra prose in every model request. Persist any acknowledgement-critical state before claiming it is durable; postpone only work whose loss or delay is genuinely acceptable.

## 5. Retrieval as query planning rather than one universal search

### 5.1 A portfolio of operators

Use a logical request describing the information needed, then select a physical plan. Candidate operators are exact lookup, scope filtering, lexical/FTS search, symbol/dependency lookup, semantic retrieval, temporal filtering, bounded relation traversal, reranking, and exact evidence expansion.

Database research such as Palimpzest and LOTUS shows the usefulness of making AI operations explicit enough to optimize for quality, cost, and latency. More recent Sema and Larch are additional research comparisons for adaptive execution and learned planning. [C06–C09]

Our proposed planner should normally be a compact cost model or classifier, trained and calibrated offline if helpful. It need not consult a premium model to decide whether a premium model should search.

### 5.2 Concrete plan examples

**Exact symbol question:** resolve project and source version, look up the symbol, retrieve its definition and selected dependency/test references. A dense embedding lookup adds little when the identifier is already exact.

**Vaguely phrased remembered decision:** retrieve candidates using lexical plus local semantic similarity, filter by project and validity, then expand source evidence for a small candidate set. This is the kind of workload on which lexical-only retrieval deserves a serious challenger.

**Historical state question:** use observation and validity information to select the relevant interval before ranking passages. Returning today's state is not correct merely because it scores highly.

**Relationship question:** retrieve seed facts and perform a bounded graph expansion, preserving source passages for the relation chain. HippoRAG 2 is a useful method reference; its online recognition costs are not automatically appropriate for Brain. [A03]

### 5.3 Explicitly reopening local semantic retrieval

The ledger previously rejected treating a vector fallback as an existing canonical capability or adding one without evidence. That was not proof that vectors can never help. The user's current research direction warrants a **new comparative experiment**, not a silent rewrite of the ledger. [R07]

EmbeddingGemma is a concrete candidate: official documentation describes a 308M-parameter encoder, configurable 768-to-128-dimensional representations, and a quantized configuration below 200 MB RAM. That is a reason to test compact local encoding; its advertised EdgeTPU latency is not a measurement of this laptop. [N01]

Compare it with a strong lexical baseline and a smaller alternative selected for the user's actual language/code mix. Precompute source embeddings only when the relevant source changes. Evaluate query encoding cost, memory, cold loading, code identifiers, paraphrases, and false matches. Keep the ability to bypass semantics completely.

Matryoshka representations allow a coarse-to-fine experiment: search a compact prefix, then refine a bounded candidate set. ColBERT-style late interaction is another precision-oriented candidate, but its richer representations have storage and compute costs. [N02–N03]

### 5.4 A source-capability catalogue solves a different problem

Sometimes the agent does not need another fact; it needs to know which information source exists and how to query it. The catalogue should record source kind, project, identity/version, searchable fields, available operations, expected cost, and evidence boundaries.

For SZ, proposed entries could identify mapping indexes, assets, dumps, runtime observations, and export memberships. Brain would retain source descriptors and useful results; `sz-tools` or Telemetry would remain the authority for domain-specific inspection. Do not duplicate the entire game-data store inside Brain.

A query such as “verify this field against the available mapping” could select a mapping inspector directly rather than first rediscovering the folder structure. Discovery should be incrementally updated as sources appear or change.

This combines retrieval with a form of metamemory: **knowing where reliable knowledge can be obtained**. The cognitive transactive-memory literature is inspiration for the distinction, not proof of software performance. [B08]

## 6. Context compilation: fidelity, not just compression

### 6.1 One object can have several representations

For a test result, the exact log is one view; the failing assertions are another; a pass/fail status bound to source/configuration hashes is another. For a research decision, the original evidence, a structured claim, and a concise task-specific explanation serve different purposes.

A proposed context compiler selects among these views based on what the next action needs. It should not repeatedly summarize a summary when an exact source or structured field is available.

This is how structured-memory methods and episode-preserving methods can coexist. The fast representation does not have to contain every detail if recovery is reliable and the task-specific representation preserves what the current decision requires. [A01–A02, A08]

### 6.2 A task-dependent distortion objective

Rate-distortion theory suggests evaluating representation size against the error caused by compression, rather than size alone. Its application here is a proposed engineering objective, not a proof that an LLM's task loss is easy to measure. [B06]

For Brain, define high-cost distortion categories: removed negation, altered units, lost bounds, missing exceptions, conflated time/version, omitted unresolved requirements, unsupported confidence, and exact-code changes. A shorter representation that introduces one of these errors can be much worse than a longer one.

An illustrative optimization is:

```text
choose representation r to minimize:
    estimated processing cost(r)
  + estimated future reacquisition cost(r)
  + risk-weighted task distortion(r)
subject to:
    required evidence coverage
    source/authority constraints
    model capacity and current task obligations
```

No numeric weights are canonically prescribed here. Fit and test them by task class. Known exact requirements can impose hard constraints; uncertainty about semantic completeness must remain visible.

LLMLingua-2 is a worthwhile compression baseline, particularly for low-risk, repetitive prose. It should not be permitted to silently strip exact identifiers, user constraints, or test evidence merely because a compression score favors doing so. [N04]

### 6.3 Context residency must be recipient-specific

A past delivery event does not prove that a model still has an object after compaction, restart, a branch change, or a worker handoff. Track a delivery key such as:

```text
(recipient, task, context_epoch, object_id, revision, representation_hash)
```

The model-facing projection can omit unchanged material only while the relevant residency assumption remains valid. If the host cannot expose authoritative context-retention events, the adapter must use a more conservative mode rather than claim exact deduplication.

This is a proposed extension of existing VMem and handoff contracts, not another message store. [R05]

### 6.4 Preserve the provider's useful cache behavior

Keep the existing cache-relevant distinction between stable prefix and changing tail. Multiple storage views do not require reviving five prompt-stability classes. Provider prompt caching and application-level memory reuse are separate mechanisms, and both need accounting. [D01, R07]

Compacting a context can reduce later processing yet lose useful cached prefix work. A context compiler should compare those costs rather than aggressively reorder the request each turn. It cannot assume that a small prompt is always the cheapest total execution plan.

References are also not magic: a URI does not convey the referenced contents to a model that has not read them. Measure the cost of expansion and subsequent reasoning, not only the size of the pointer.

## 7. Procedural memory should become executable

### 7.1 From successful experience to a program

A candidate procedure can begin as a verified execution trace. A teacher then proposes its reusable structure: inputs, preconditions, deterministic steps, semantic decision points, permitted effects, completion conditions, and required evidence. The resulting program is checked against held-out variations before becoming an active option.

Memp and ACE support learning reusable procedural knowledge and improving it incrementally. Our additional proposal is to compile suitable portions into execution rather than always delivering prose instructions. [P01, P03]

A useful distinction is:

```text
remembered answer       -> possibly reusable information
remembered procedure    -> reusable decision guidance
checked procedure       -> executable computation with explicit limits
```

Not every task can or should become the third kind. The goal is to remove repeated coordination where its structure is stable.

### 7.2 Example: inspecting known project data

A hypothetical, read-only procedure could be:

```text
input: project, requested concept, source-version constraints
1. select eligible source descriptors
2. query mapping and dump indexes in parallel when independent
3. normalize identifiers using the approved mapping revision
4. collect exact supporting spans and disagreement records
5. return a compact evidence package
6. invoke a model only to resolve a genuinely semantic ambiguity
```

The procedure does not let a memory string choose an arbitrary executable or access unrelated files. Its read capabilities, resource bounds, source identities, and output schema are explicit.

Compared with an agent deciding each intermediate search independently, this could remove several model decision boundaries. The actual reduction is unknown; existing native parallel calls may already remove some of them. Compare against a strong harness baseline, not a deliberately inefficient sequence.

### 7.3 Typed control and semantic uncertainty

RLM-style execution is attractive for large corpora because programmatic selection can keep bulk inputs out of the main context. LLMCompiler supplies a dependency-graph perspective. Lambda-RLM supplies an additional direction: retain structured control around bounded neural computations. [P07–P09]

I would represent a procedure as a graph of typed operations with effect annotations such as `pure`, `read_snapshot`, `write_workspace`, and `external_side_effect`. The graph scheduler can batch compatible reads and preserve dependencies. Semantic model calls are explicit nodes with their own input/output contract and quality check.

Type checking can catch invalid composition and bound certain control structures. It does not prove that a model's interpretation is correct. A generated procedure still needs behavioral tests, trustworthy evidence checks, and an appropriate fallback.

### 7.4 Execute near the data

Anthropic's code-execution and programmatic-tool work illustrates a practical principle: intermediate results can be filtered, aggregated, and transformed without sending every row through the model. This is a stronger optimization than telling the model to be concise. [P10–P11]

For Brain, put deterministic operations in reusable tool-side functions or checked programs. Make the model-visible return a focused result with exact recovery references. A read-only data reduction can often be proved against its source; a model-authored semantic reduction requires additional validation.

### 7.5 Safety is part of the execution model

A learned procedure is not authorized simply because it was successful once. Distinguish suggested operations from granted capabilities. Imported tool descriptions, web text, memory records, and generated programs cannot enlarge their own permissions.

Wasmtime is one possible sandbox substrate, not a complete safety solution by itself. Host imports and resource controls matter. Memory-injection research such as MINJA further motivates preserving origin and authority across learning and reuse. [E04–E05]

Pure computation, read-only inspection, reversible workspace changes, and external actions require different execution policies. Speculative writes or publication are not justified by an expected speedup.

## 8. Biological inspiration translated into mechanisms

### 8.1 Fast acquisition, slower integration

Complementary-learning-systems theory motivates separating rapid acquisition of specific experience from the slower integration of reusable structure. It should not be mistaken for a literal map of two software folders onto two brain regions. Recent experimental work also complicates simple anatomical versions of the story. [B01, B09]

Our proposed implementation is straightforward in purpose but substantial in machinery: capture exact episode evidence cheaply; asynchronously derive structured relationships; consolidate recurring patterns into a procedure or retrieval policy only when their scope and evidence are clear. LightMem and sleep-time computation provide AI-system comparisons for this separation. [A04, P13]

### 8.2 Replay according to expected benefit

Mattar and Daw's need-by-gain theory offers a useful normative criterion for prioritizing replay. The original account does not supply a ready-made efficient estimator for a coding agent. [B02]

A proposed Brain approximation would prioritize an experience when a similar task is likely to recur, the prior cost or failure was significant, and a representation update is likely to change the outcome. It would deprioritize repeatedly rehearsing an already reliable, low-cost procedure.

Rather than training on all history equally, select examples of expensive rediscovery, source-version mistakes, harmful compression, wrong transfer, and successful difficult reuse. Evaluate changes on different episodes, not the very trace used to create the rule.

### 8.3 Prospective memory: remember at the moment of action

Prospective-memory research distinguishes remembering an intention when a relevant cue appears from continuously monitoring for an opportunity. [B07]

Brain can implement a concrete analogue: compile outstanding obligations into an event-indexed trigger table. A migration-file change activates migration-specific knowledge; a project switch activates source-scope checks; a forthcoming finalization activates unresolved acceptance requirements. These events should fetch only the relevant state.

This is especially useful for the user's “the agent forgot mappings exist” experience. The desired behavior is not to keep a paragraph about mappings permanently in every prompt. It is to recognize a query or operation for which the mapping source matters and supply the appropriate capability or evidence.

### 8.4 Event boundaries and surprise guide capture

Event-segmentation research treats boundaries and prediction error as important to organizing experience. [B04]

A proposed capture policy should therefore pay attention to meaningful changes: a hypothesis was disproved, a test passed after a repair, an interface changed, an external source contradicted memory, or a task moved from blocked to actionable. It should not summarize every token or every mouse movement.

Surprise is a reason to inspect, not a reason to immediately generalize. One failed command could reflect a transient environment issue rather than a reusable law about the project.

### 8.5 Forgetting should remove maintenance burden, not rewrite truth

Recency and frequency can help predict future demand, as illustrated by work connecting memory and environmental statistics. [B05]

In Brain, the corresponding operation should usually be demotion from expensive resident/indexed representations, not destruction of unique evidence. A rarely used but safety-critical requirement remains protected. A high-frequency misconception must not become trusted through repetition.

S3-FIFO provides a systems counterpart worth comparing: inexpensive admission and probation can keep one-time items from dominating the hot cache. Its results are cache-system evidence, not direct evidence that model tokens will fall. [C03]

### 8.6 Control effort itself has a cost

Expected-value-of-control theory motivates spending management effort when its expected benefit exceeds its cost. [B03]

Our proposed implementation is not an LLM deliberating over every memory choice. It is an offline-fitted selector whose runtime inputs are cheap features: task signature, current source validity, available indexed operators, cache residency, observed previous outcomes, and estimated work avoided.

The biological idea is used to select computation, not to name another always-running agent.

## 9. Let expensive research produce a cheap runtime

### 9.1 Learn the policy, not only the memories

GEPA, Memory-R1, and MemEvolve suggest different ways to improve agent behavior from outcomes: reflective optimization, trained memory actions, and evolution of memory-system operations. They are not interchangeable algorithms, and their published results do not establish the best controller for this project. [P04–P06]

The important proposal is an **offline design-and-distillation loop**. Search over retrieval plans, cache admission, context representations, procedure selection, and consolidation strategies. Evaluate candidates against preserved task traces and held-out live workloads. Then compile the selected behavior into small tables, classifiers, or native functions.

This is the “sleep teaches the reflex” combination: expensive exploration is allowed, but its deployed result should not necessarily be an expensive model invocation.

### 9.2 The search space should include real design alternatives

Candidate changes should be substantive: lexical-only versus hybrid retrieval; sparse versus dense relation expansion; several compression forms; cache-admission algorithms; conservative versus predictive local prefetch; selected executable procedures; and alternative event/cue features.

Do not optimize only the wording of a prompt while treating architecture as fixed. Equally, do not permit a search process to redefine truth, weaken tests, or change the benchmark population until its result looks favorable.

Start with evidence-carrying operators that can be composed. The offline optimizer should choose implementations and parameters within a constrained contract. A proposed new operator can enter the research environment, but must acquire its own behavioral and resource evidence.

### 9.3 Causal evidence matters

A memory being present during a successful task does not prove that it helped. Record exposures, selections, intervention identities, relevant state, and outcomes. Where safe and authorized, compare alternative policies on equivalent tasks. Retain support and uncertainty information before relying on off-policy estimates.

The existing ledger already recognized that delayed propensity logging cannot reconstruct past selection probabilities. V3 should reuse and strengthen that accounting rather than create another telemetry system. [R07]

Optimize a vector of outcomes: correct completion, task tokens, latency distribution, local resources, source-freshness failures, and recovery. Do not compress safety-critical errors into a small monetary penalty that a fast but unsafe policy can profitably ignore.

### 9.4 A concrete lifetime-value model

For a proposed compiled representation or procedure `j`, use an experimentally estimated model such as:

```text
lifetime_value(j) =
    expected valid future reuse × expected work avoided per reuse
  - construction cost
  - maintenance and invalidation cost
  - storage / residency / interference cost
```

This is a proposed accounting model, not a theorem about user demand. Keep tokens, money, latency, and machine resources separately observable; combining them requires explicit priorities.

An illustrative break-even condition is:

```text
N > construction_cost / (cost_without_reuse - cost_with_reuse - maintenance_per_use)
```

It is meaningful only if the denominator is positive, the units match, and the same result remains valid long enough. Stable documentation may justify heavy preparation; constantly changing runtime memory may not. Expensive development can still be worthwhile, but its eventual savings should be tested rather than assumed.

## 10. Use waiting time intelligently, without speculative harm

### 10.1 Local prefetch is not speculative prompt stuffing

When a model is already processing a request or a tool is waiting for a result, Brain may prepare a likely next local lookup. Prefetching an index page, parsing a known changed source, or resolving a source descriptor can reduce later waiting without adding tokens to the current request.

The proposed scheduler must respect the user's real hardware load. Unused prefetch work consumes CPU, memory, and energy even when it adds no model tokens. It should be cancelled or deprioritized when foreground work needs those resources.

### 10.2 A more aggressive experimental track

Speculative Programmatic Tool Calling demonstrates an author prototype that can begin eligible calls while a program is still being generated. This is promising but introduces control-flow, identity, and side-effect questions. [P12]

For Brain, begin with strictly bounded, pure or snapshot-read operations whose inputs and authority are already known. Never infer that a shell command is safe just because it resembles a read. Avoid speculative writes, uploads, remote mutations, or unapproved paid model calls.

Maintain distinct invocation identities for nondeterministic operations; identical arguments do not make two model samples interchangeable. Speculation should return a reusable future only when its dependency and occurrence identity matches the eventual call.

The decisive comparison is end-to-end verified latency versus extra work and cancellation waste. A slower, more expensive speculative branch that merely moves activity earlier is not a success.

## 11. Neural memory and inference techniques: what is actually accessible?

### 11.1 Three control surfaces

| Surface | What Brain can reasonably control | Limitation |
|---|---|---|
| Outside the model | Files, indexes, representations, tool execution, retrieval, prompt assembly, adapters | The host must expose the relevant hook or protocol surface |
| Local model serving | Tokenization, inference runtime, compatible activation caches, model-specific helpers | Available RAM/VRAM, model support, implementation and thermal limits |
| Inside a hosted frontier model | Normally only the documented provider interface | An external client cannot assume raw KV import, trainable test-time layers, or hidden-state access |

The third limitation is **API control**, not weak laptop hardware. These categories should not be conflated when deciding what is feasible.

### 11.2 Titans, test-time training, and Engram

Titans and test-time-training layers investigate memory mechanisms inside a model. Engram investigates conditional lookup as a complement to model computation. These are relevant scientific inspiration but not features an OMP extension can install into a hosted model. [N05–N07]

For a local research branch, a small model could investigate learned memory selection or a specialized representation. For the hosted-model core, borrow the architectural principle: reusable lookup for stable knowledge and computation for genuinely new combinations. Brain's existing term “workflow engram” should not be confused with the separate Engram model architecture.

### 11.3 Trained activation memories

Cartridges train a compact corpus-specific KV prefix while keeping model weights fixed. The paper reports an unoptimized Llama-8B construction run taking about 30 minutes on eight H100 GPUs. That is a concrete warning against treating published construction as a laptop-scale operation. Smaller experiments remain research possibilities, not ruled out by difficulty. [N08]

A model-specific activation memory could become an optional acceleration backend for stable corpora, but not the canonical evidence store or the portable cross-provider memory format. Updates, exact fact recovery, and model compatibility would still require testing.

### 11.4 Serving optimizations are not client-side switches

SGLang's structured execution/prefix reuse, CacheBlend's cached-knowledge fusion, and PagedAttention's serving-memory management operate at the inference-system level. They are useful when Brain controls a compatible local serving stack. They cannot simply accelerate the provider's hardware through a client-side configuration. [N09–N11]

For hosted inference, optimize the documented request path, useful cache behavior, and the amount of work requested. Do not report local context handles or small serialized worker packets as actual provider KV reuse without provider evidence. [D01–D02]

## 12. Hardware feasibility on the existing laptop

### 12.1 What does not inherently require larger hardware

The proposed native control path, content-addressed artifacts, dependency graph, lexical/source indexes, compact local policies, and source catalogue are normal CPU/storage workloads. Their size can be bounded and measured. There is no identified fundamental requirement for a larger GPU to research them.

Local semantic encoding is also a credible experiment given the existence of compact encoders, but overall application residency is more than model weights. The encoder, runtime buffers, index, source text, other applications, and operating system all share the user's 16 GB. [N01]

A useful scale calculation: 100,000 vectors at 256 dimensions require **25.6 MB** for one-byte coordinates, or **102.4 MB** for 32-bit floats, before metadata, search-index overhead, original text, runtime buffers, or model memory. These are arithmetic storage estimates, not a prediction of process memory or retrieval latency.

### 12.2 What needs a separate resource study

Neural reranking, multi-vector indexes, local generative teacher models, training a memory selector, and activation-memory experiments should be admitted according to measured resource use. Use the GPU opportunistically rather than making every memory lookup depend on its availability.

Measure cold load, sustained throughput, foreground interference, memory pressure, and energy/thermal effects. A local model that fits once is not necessarily appropriate while development tools or a game are running. Do not assume the previously reported GPU's full nominal memory is available.

### 12.3 What is genuinely beyond the baseline without extra resources

Replicating large-model training or the cited multi-H100 cartridge construction is not a credible default workload on the existing laptop. It may be possible to use a smaller model, a less expensive construction method, or explicitly approved external compute. Those alternatives should have their own feasibility and privacy assessment, not an invented equivalence to the published result.

No source material should be sent to a cloud trainer merely because this research discusses offline teachers. The user's willingness to invest in development is not authorization for an arbitrary upload or charge.

### 12.4 Resource policy follows measurements, not aesthetics

A compact persistent process can be more efficient than repeated subprocess startup; a native component can be more efficient than interpreter overhead; a simpler implementation may also be sufficient. Compare them. Do not reject a justified process or native implementation because an earlier design avoided services, and do not adopt one solely because it sounds more advanced.

The preserved requirement is local autonomy and one canonical state authority. The exact process lifetime and language are now explicit research variables.

## 13. Three end-to-end examples

These illustrate the proposed design. They are not implemented commands or measured outcomes.

### 13.1 A simple arithmetic request

The adapter already has the current project/task snapshot. No unresolved obligation or relevant memory cue applies. The compiled gate returns pass-through, adds no Brain-specific message or schema, and leaves the provider request semantically identical to the native control. Optional telemetry is recorded without a model call.

This is how a roughly four-second native response could remain roughly four seconds: remove local work rather than asking a second model to be faster. Provider variability remains. Achieving three seconds requires actual saved work or a faster provider response, not merely loading Brain.

### 13.2 The agent needs game mappings and dumps

The source catalogue identifies eligible mapping and dump inspectors. A compiled read-only procedure selects the relevant version, searches the correct fields, and returns exact evidence spans with conflicts. A compact representation gives the solver the necessary result and recovery references.

The model no longer needs to first remember that these sources exist, guess their folders, inspect broad directories, and devise the same joining procedure again. The catalogue and procedure are refreshed only when their dependencies change.

The win is not “all mappings are permanently in the prompt.” It is that the proper information source and the route to inspect it are already known to the runtime.

### 13.3 A recurring migration review after a code change

A file-change event matches the prospective cue for migration review. The dependency graph identifies the changed migration, relevant schema/configuration, inspection tools, and tests. A verified procedure performs mechanical checks. Its output includes exact failures and any semantic ambiguity needing review.

A subsequent change to an unrelated document does not automatically invalidate the review. A change to a migration dependency or test runner does. A resumed session receives the current verified state and unresolved questions, rather than a repeated transcript of every previous search.

The system saves work only to the extent that its dependency model and procedure are valid. That is precisely why those mechanisms need tests as rigorous as the task itself.

## 14. Reconciliation with previous decisions

The user's new direction removes implementation difficulty as a research veto. It does not silently alter the live system or erase the reasons for earlier decisions.

| Previous decision or assumption | Research treatment now |
|---|---|
| Avoid a native rewrite by default | Actively compare a native kernel with a reused interpreter runtime; keep the winner for measured reasons |
| Avoid any longer-lived local process | Compare lifecycle-owned brokers and in-host snapshots; local-first does not require a cold process on every hook |
| Vector fallback rejected in earlier scope | Reopen as a hypothesis where paraphrase/semantic failures justify it; do not claim the old code already supplies it |
| Dynamic tool-schema mutation rejected | Preserve stable-prefix behavior; test native deferred discovery first, and compare any dynamic alternative explicitly |
| Five stability classes rejected | Keep PREFIX/TAIL for provider placement; multiple internal storage views are a separate concern |
| Lean-first optimization rejected | Retain a trustworthy evidence and freshness floor before making adaptive performance claims |
| One canonical owner | Preserve it; compiled caches and snapshots are derived views, not rival sources of truth |
| Agent OS framing already in v2 | Do not rebrand it as the research discovery; focus on concrete algorithms and execution boundaries |

These are proposed reconsiderations attached to existing primitives. No Idea Ledger state was changed during this research. [R06–R07]

## 15. The experimental program

### 15.1 Questions that should determine the architecture

| Experiment | Hypothesis | Decisive comparison / failure signal |
|---|---|---|
| E1: execution boundary | Reused/native execution can remove cold bridge costs | Native OMP, inert extension, current Brain, reused-runtime candidate, and native candidate with identical request contracts; cold and warm separately |
| E2: memory build graph | Precise incremental invalidation saves more work than its bookkeeping costs | Dirty/staged/untracked edits, new files, changed tool/config versions, lost watcher events, and identical derived outputs; any unsafe stale reuse fails |
| E3: retrieval planner | A selected hybrid portfolio improves useful recall without unnecessary work | Exact symbols, held-out paraphrases, temporal queries, relationships, no-relevance cases, and cross-project distractors; compare strong lexical and always-hybrid baselines |
| E4: context compiler | Task-specific representations reduce processing without losing needed evidence | Exact values/negations, changed requirements, resumed tasks, conflict resolution, and later detailed questions; measure omitted obligations and reacquisition |
| E5: procedure compiler | Reusable programs eliminate unnecessary model coordination | Native parallel tools versus prose skills versus compiled procedures, including unexpected inputs and changed dependencies |
| E6: cue-triggered memory | Event-indexed obligations reduce forgotten resources without broad injection | Natural requests requiring mappings, tests, resume state, or project-specific constraints; measure missed cues and false activations |
| E7: consolidation and policy learning | Offline preparation pays back over realistic repeated work | Entire sequences with build, maintenance, invalidation, and replay costs; held-out task families and model transitions |
| E8: speculative reads | Safe overlap reduces critical-path latency | Sequential versus prefetched execution under normal and constrained hardware load; count wasted reads, cancellations, and foreground interference |
| E9: neural optional tier | A small model-specific helper provides additional net value | Local encoding/reranking first, then a separately budgeted small activation-memory prototype; no direct extrapolation from large-model papers |

### 15.2 Do not benchmark only happy paths

The user's workload should include current Second Brain development, known-source discovery for SZ, and source-backed engineering investigations such as Basic Upscaler work. Freeze a corpus and task set without including private data unnecessarily. Use existing successful tasks plus new paraphrases and adverse cases.

LongMemEval and EverMemBench provide additional memory challenges, but neither substitutes for code execution, evolving repository state, or the user's actual tools. Include their useful categories—updates, time, multi-session evidence, and abstention—inside project-specific evaluations. [E02–E03]

A policy that improves easy recall but mishandles “this previous finding is now wrong” is not ready. A procedure that reduces turns only because its test prompts exactly match its training trigger is not sufficient.

### 15.3 Measure the right costs

Record logical input, cached input, output/reasoning where exposed, all descendant calls, actual tool executions, prepared-but-unused work, local processing, critical-path spans, first visible output, verified completion, startup, and finalization. Preserve real provider request identities.

Token cost, model-reported money, and subscription quota are distinct quantities. Unknown subscription attribution remains unknown. Do not add overlapping timing spans. Do not compare a warm candidate to an artificially cold control without a separate matched analysis.

A component can reduce tool execution but leave the model-call count unchanged; another can reduce tokens but increase latency. Report the separate mechanisms and their joint result rather than call every improvement “speed.”

### 15.4 Learn with an outer research loop, deploy through an inner runtime

Use a progression from deterministic replay and microbenchmarks to real-host trials and full task sequences. Preserve every failed run. Sample sizes should follow the decision and uncertainty; a small pilot is not a proof of tail latency or zero failure probability.

Ablate individual mechanisms, then test important interactions: semantic retrieval plus compression; incremental invalidation plus action caching; procedural compilation plus prefetch; context deduplication plus provider caching. A set of individually good components can be bad in combination.

Train selectors and procedures on one partition, tune on another, and evaluate on held-out tasks and chronologically later source states. Distribution shift is expected as the user's projects and providers change.

### 15.5 Conditions for rejecting a candidate

Reject a candidate when it cannot preserve required correctness or authority, when total lifecycle value is negative on its intended workload, when it depends on unavailable host capabilities, or when its resource use is incompatible with the actual machine. Do not reject it merely because implementation is difficult.

A rejected universal policy may still be valuable as a narrow specialized operator. Conversely, one spectacular benchmark win does not justify turning it on for every request.

## 16. Recommended research-to-build sequence

**First: make reuse trustworthy and execution measurable.** Build the shared memory representation and dependency contract around existing sources. Prototype the native/reused execution boundary. Preserve unresolved v2 correctness and recovery issues; design research is not a shortcut around them.

**Second: make knowledge accessible in the right form.** Add the source-capability catalogue and retrieval-plan experiments. Implement context views and recipient/context-epoch tracking. This connects directly to the user's forgotten-source problem.

**Third: remove repeated agent work.** Compile a small set of high-value procedures and compare them against a strong OMP tool baseline. Add safe local prefetch where actual waits leave useful overlap opportunities.

**Fourth: let outcomes improve the implementation.** Run offline controller and memory-organization research, retain causal accounting, and distill selected strategies into the cheap runtime. Expand the catalogue of executable procedures as evidence supports it.

**Parallel exploratory branch: neural memory.** Study small local semantic helpers and compatible model-specific memories separately. Their hardware and API requirements should not block the portable core, and their results should not be hidden inside its baseline.

This ordering follows dependency and attribution needs, not reluctance to tackle difficult work. The long-term architecture is ambitious; the experiments determine which complex mechanisms deserve permanent residency.

## 17. Final design position

The proposed v3 is not simply a stricter governor. It is a system that changes the economics of repeated work:

- Exact evidence can outlive the active prompt.
- Derived knowledge can be rebuilt rather than manually rediscovered.
- Unchanged computation can be reused rather than rerun.
- A task can choose among memory forms instead of accepting one universal representation.
- Successful procedures can become executable instead of repeatedly narrated.
- Expensive learning can produce cheap future decisions.
- The main model can spend its effort on uncertainty, not on maintaining its own infrastructure.

The underlying hypothesis is that the best path to a faster, more capable Second Brain is **to compile experience into something the runtime can use directly**. Published research supplies credible ingredients. The integrated design and its benefit on the user's hardware remain to be demonstrated.

## Internal evidence register

**[R01] Historical Phase 20 token-efficiency report.** `outputs/reports/v2/omp-burnin/20-token-efficiency/TOKEN_EFFICIENCY.md`, repository snapshot `6baea51b0be3ac7108ca6deafe5665ab8cca0852`. Historical paired observations, not current installed measurements.

**[R02] Historical Phase 21 latency report.** `outputs/reports/v2/omp-burnin/21-latency-qualification/LATENCY_QUALIFICATION.md`, same snapshot. Includes startup measurements and an explicitly unresolved end-to-end gap.

**[R03] Action Cache source excerpt.** `src/second_brain/action_cache.py`, lines 1–180 at the same snapshot. Dependency classes, proof-related fields, validation economics, file hashing, and Git subprocess helpers were inspected. Header performance claims were not independently verified.

**[R04] Retrieval source excerpt.** `src/second_brain/hybrid_retrieval.py`, lines 1–210 at the same snapshot. Cascade/result representations and ranking code were inspected. This excerpt alone does not prove an active vector backend or an advertised latency/coverage claim.

**[R05] VMem source excerpt.** `src/second_brain/vmem.py`, lines 1–150 at the same snapshot. Residency, recovery classes, material-state protection, and additive fields were inspected.

**[R06] Canonical Scout Spec.** Connected Google Doc `1XnGaiQdBREY31CmX1Fo-u1bjiDq81GxbfGMh_-T3nLI`, title `2nd Brain — Canonical R&D Scout Spec (v1.0 + v2.0)`, read 2026-09-09. Defines roadmap and architectural contracts; does not override current repository reality.

**[R07] Idea Ledger.** Connected Google Doc `1VTTnlBQIWfydXQT6aVkBUHJINFVjgtLzQDcGeFVg33k`, title `IDEA_LEDGER.md`, read 2026-09-09. Includes September 2 rejected subideas and September 6 synthesis. No ledger edits were made.

**[R08] Earlier proposed performance charter.** `Second_Brain_v3_Performance_Charter_PROPOSED_2026-09-09.md`, supplied locally in this conversation. Its numerical targets remain proposals; this dossier adds architectural research, not measured compliance.

---

## Reference register

61 external primary sources. Dates identify publication periods or documentation access, not a claim that every current implementation was audited. Some comparisons use paper abstracts; the core design discussions also used methods, limitations, official documentation, or source excerpts. URLs are provided for verification.

**[B01] Complementary learning systems in the hippocampus and neocortex** — 1995. Neuroscience theory.
Fast acquisition and slower integration; not a literal two-database blueprint.
Source: `https://pubmed.ncbi.nlm.nih.gov/7624455/`

**[B02] Prioritized memory access explains planning and hippocampal replay** — 2018. Computational neuroscience.
Need and gain as a normative prioritization principle; efficient estimation remains an engineering problem.
Source: `https://pmc.ncbi.nlm.nih.gov/articles/PMC6203620/`

**[B03] The expected value of control** — 2013. Computational neuroscience.
Allocate control effort according to prospective benefit and cost.
Source: `https://pmc.ncbi.nlm.nih.gov/articles/PMC3767969/`

**[B04] Event perception: a mind-brain perspective (event segmentation)** — 2007. Cognitive science.
Event boundaries and prediction error as cues for episode organization.
Source: `https://pubmed.ncbi.nlm.nih.gov/17338600/`

**[B05] Reflections of the environment in memory** — 1991. Cognitive science.
Recency and frequency in relation to environmental demand.
Source: `https://journals.sagepub.com/doi/10.1111/j.1467-9280.1991.tb00174.x`

**[B06] Rate-distortion theory and human perception** — 2016. Information theory / cognition.
Task-dependent distortion, rather than minimum representation length alone.
Source: `https://pubmed.ncbi.nlm.nih.gov/27107330/`

**[B07] Prospective-memory retrieval and monitoring experiments (PMID 20053054)** — 2010. Experimental cognitive science.
Cue-triggered remembering versus costly ongoing monitoring.
Source: `https://pubmed.ncbi.nlm.nih.gov/20053054/`

**[B08] Google effects on memory: cognitive consequences of having information at our fingertips** — 2011. Experimental cognitive science.
Remembering where information is available; a limited analogy for a source catalogue.
Source: `https://pubmed.ncbi.nlm.nih.gov/21764755/`

**[B09] Systems consolidation reorganizes hippocampal engram circuitry** — 2025. Experimental neuroscience.
Counterweight to oversimplified anatomical analogies; memory precision and gist can change within hippocampal circuitry.
Source: `https://pubmed.ncbi.nlm.nih.gov/40369077/`

**[A01] SimpleMem: Efficient Lifelong Memory for LLM Agents** — 2026; HTML v3. Research paper / preprint.
Structured compression, synthesis at writing, and adaptive multi-view retrieval; construction cost is separate from query cost.
Source: `https://arxiv.org/html/2601.02553v3`

**[A02] Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects** — 2025; HTML v1. Research paper / preprint.
Different memory types and complementary semantic, lexical, graph, and temporal retrieval.
Source: `https://arxiv.org/html/2512.12818v1`

**[A03] From RAG to Memory: Non-Parametric Continual Learning for Large Language Models (HippoRAG 2)** — 2025; HTML v2. Research paper / preprint.
Associative retrieval using triples, passage context, recognition, and graph propagation.
Source: `https://arxiv.org/html/2502.14802v2`

**[A04] LightMem: Lightweight and Efficient Memory-Augmented Generation** — 2025–2026; current abstract checked. Research paper.
Sensory filtering, short-term organization, and sleep-time updates; distinguishes online and total costs.
Source: `https://arxiv.org/abs/2510.18866`

**[A05] Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory** — 2025. Research paper.
Memory extraction and updating; useful external baseline, not automatic evidence of Brain savings.
Source: `https://arxiv.org/abs/2504.19413`

**[A06] Zep: A Temporal Knowledge Graph Architecture for Agent Memory** — 2025. Research paper / preprint.
Time-aware knowledge graphs for evolving agent memory.
Source: `https://arxiv.org/abs/2501.13956`

**[A07] A-MEM: Agentic Memory for LLM Agents** — 2025. Research paper / preprint.
Linked notes and evolving associations; useful organization, with an update-cost trade-off.
Source: `https://arxiv.org/abs/2502.12110`

**[A08] E-mem: Episodic Memory for LLM Agents** — 2026. Research paper / preprint.
Episodic context reconstruction; counterpoint to aggressive fact-only compression.
Source: `https://arxiv.org/abs/2601.21714`

**[A09] EverMemOS** — 2026. Research paper / preprint.
Episodic cells, semantic organization, and prospective information.
Source: `https://arxiv.org/abs/2601.02163`

**[A10] MemOS** — 2025–2026. Research paper / preprint.
Different memory substrates and lifecycle management; distinguish textual from activation and parameter access.
Source: `https://arxiv.org/abs/2507.03724`

**[A11] OpenViking** — Repository consulted 2026-09-09. Official implementation.
Hierarchical resources and multiple levels of detail; borrow the abstraction rather than require its deployment stack.
Source: `https://github.com/volcengine/OpenViking`

**[A12] VikingMem** — 2026. Research paper / preprint.
Event-driven state and memory organization; a comparison point for derived entity views.
Source: `https://arxiv.org/abs/2605.29640`

**[C01] Build Systems à la Carte** — 2018 / journal treatment 2020. Research paper / author institution.
Dependency-aware recomputation as a general reusable-computation model.
Source: `https://www.microsoft.com/en-us/research/publication/build-systems-a-la-carte/`

**[C02] Salsa: the red-green algorithm** — Documentation checked 2026-09-09. Official documentation.
Revision tracking, dependencies, and retaining downstream results when recomputed values do not change.
Source: `https://salsa-rs.github.io/salsa/reference/algorithm.html`

**[C03] FIFO Queues are All You Need for Cache Eviction (S3-FIFO)** — 2023. Systems research paper.
Probation and low-overhead cache management; evaluate on Brain traces rather than import cache throughput claims.
Source: `https://www.pdl.cmu.edu/PDL-FTP/Storage/FIFOqueues-SOSP23_abs.shtml`

**[C04] SQLite isolation** — Documentation checked 2026-09-09. Official documentation.
Snapshot reads and transactional consistency.
Source: `https://www.sqlite.org/isolation.html`

**[C05] SQLite Write-Ahead Logging** — Documentation checked 2026-09-09. Official documentation.
Local reader/writer concurrency with one writer; checkpoints and long-lived readers matter.
Source: `https://www.sqlite.org/wal.html`

**[C06] Palimpzest: Optimizing AI-Powered Analytics with Declarative Queries** — 2024. Research paper.
Cost/quality/latency trade-offs in choosing physical AI query plans.
Source: `https://arxiv.org/abs/2405.14696`

**[C07] LOTUS: semantic operators and query optimization** — 2024–2025. Research paper.
Declarative semantic operations and optimized execution rather than model-managed row-by-row loops.
Source: `https://arxiv.org/abs/2407.11418`

**[C08] Sema** — 2026. Research paper / preprint.
Semantic query processing and adaptive execution; an experimental comparison, not a required dependency.
Source: `https://arxiv.org/abs/2603.11622`

**[C09] Larch** — 2026. Research paper / preprint.
Learned planning of semantic operations; a research direction for an offline-trained cost model.
Source: `https://arxiv.org/abs/2606.07923`

**[P01] Memp: Exploring Agent Procedural Memory** — 2025–2026. Research paper.
Build, retrieve, and update reusable procedures from experience.
Source: `https://arxiv.org/abs/2508.06433`

**[P02] ProcMEM** — 2026. Research paper / preprint.
Procedural activation, execution, and termination as a learned memory-management problem.
Source: `https://arxiv.org/abs/2602.01869`

**[P03] Agentic Context Engineering (ACE)** — 2025. Research paper / preprint.
Incremental playbook improvement rather than repeatedly rewriting a shrinking summary.
Source: `https://arxiv.org/abs/2510.04618`

**[P04] GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning** — 2025. Research paper / preprint.
Reflective, Pareto-oriented optimization from execution evidence.
Source: `https://arxiv.org/abs/2507.19457`

**[P05] MemEvolve: Meta-Evolution of Agent Memory Systems** — 2025–2026. Research paper / preprint.
Optimize the organization and operations of memory, not only memory contents.
Source: `https://arxiv.org/abs/2512.18746`

**[P06] Memory-R1: Enhancing Large Language Model Agents to Manage and Utilize Memories via Reinforcement Learning** — 2025. Research paper / preprint.
Outcome-trained memory actions; training and inference costs remain relevant.
Source: `https://arxiv.org/abs/2508.19828`

**[P07] Recursive Language Models** — 2025–2026. Research paper / preprint.
Treat a large input as an external programmatically inspectable environment.
Source: `https://arxiv.org/abs/2512.24601`

**[P08] The Y-Combinator for LLMs: Solving Long-Context Rot with lambda-Calculus** — 2026. Research paper / preprint.
Structured control with bounded neural computations; type safety does not prove semantic answers.
Source: `https://arxiv.org/abs/2603.20105`

**[P09] An LLM Compiler for Parallel Function Calling** — 2023–2024. Research paper.
Dependency-graph execution and parallel function calls.
Source: `https://arxiv.org/abs/2312.04511`

**[P10] Code execution with MCP: building more efficient agents** — 2025-11-04. Primary engineering report.
Filter and aggregate intermediate data outside model context; sandbox requirements remain.
Source: `https://www.anthropic.com/engineering/code-execution-with-mcp`

**[P11] Advanced tool use** — 2025-11-24. Primary engineering report.
Native deferred tool discovery and programmatic tool calling.
Source: `https://www.anthropic.com/engineering/advanced-tool-use`

**[P12] Speculative Programmatic Tool Calling** — 2026. Author prototype / engineering report.
Start safe eligible calls before generation ends; not evidence for unrestricted speculative execution.
Source: `https://alexzhang13.github.io/blog/2026/spec-ptc/`

**[P13] Sleep-time Compute: Beyond Inference Scaling at Test-time** — 2025. Research paper / preprint.
Spend compute on reusable context before the immediate query; count preparation and invalidation.
Source: `https://arxiv.org/abs/2504.13171`

**[N01] EmbeddingGemma model overview** — Official documentation checked 2026-09-09. Official model documentation.
Compact local semantic encoding with configurable embedding dimensions; laptop latency is unmeasured.
Source: `https://ai.google.dev/gemma/docs/embeddinggemma`

**[N02] Matryoshka Representation Learning** — 2022. Research paper.
Nested representations support coarse-to-fine retrieval at different dimensions.
Source: `https://arxiv.org/abs/2205.13147`

**[N03] ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction** — 2021–2022. Research paper.
Token-level late interaction; possible precision gain at additional storage and computation cost.
Source: `https://arxiv.org/abs/2112.01488`

**[N04] LLMLingua-2: Data Distillation for Efficient and Faithful Task-Agnostic Prompt Compression** — 2024. Research paper.
Learned extractive compression; not a general guarantee of lossless task evidence.
Source: `https://arxiv.org/abs/2403.12968`

**[N05] Titans: Learning to Memorize at Test Time** — 2025. Research paper / preprint.
Neural memory updates at inference; requires model-internal access.
Source: `https://arxiv.org/abs/2501.00663`

**[N06] Learning to (Learn at Test Time): RNNs with Expressive Hidden States** — 2024. Research paper.
Test-time-training layers; distinct from external agent memory.
Source: `https://arxiv.org/abs/2407.04620`

**[N07] Conditional Memory via Scalable Lookup: A New Axis of Sparsity for Large Language Models (Engram)** — 2026. Research paper / preprint.
Conditional lookup versus computation inside a model; not Brain workflow engrams.
Source: `https://arxiv.org/abs/2601.07372`

**[N08] Cartridges: Lightweight and general-purpose long context representations via self-study** — 2025–2026; HTML v3. Research paper.
Corpus-specific trained KV prefixes; expensive construction and model-specific serving.
Source: `https://arxiv.org/html/2506.06266v3`

**[N09] SGLang: Efficient Execution of Structured Language Model Programs** — 2023–2024. Research paper.
Structured execution and prefix reuse in an inference runtime.
Source: `https://arxiv.org/abs/2312.07104`

**[N10] CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion** — 2024. Research paper.
Fusion of cached context with selective recomputation; serving-level capability.
Source: `https://arxiv.org/abs/2405.16444`

**[N11] Efficient Memory Management for Large Language Model Serving with PagedAttention** — 2023. Research paper.
Paged serving-memory allocation; not a cloud-client-side speed switch.
Source: `https://arxiv.org/abs/2309.06180`

**[E01] EvoMemBench: Benchmarking Agent Memory from a Self-Evolving Perspective** — 2026. Research paper / preprint.
Knowledge versus execution and within- versus across-episode comparisons; no universal memory winner.
Source: `https://arxiv.org/html/2605.18421`

**[E02] LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory** — 2024–2025. Research paper.
Temporal reasoning, updates, multi-session evidence, extraction, and abstention.
Source: `https://arxiv.org/abs/2410.10813`

**[E03] EverMemBench** — 2026. Research paper / preprint.
Long-horizon evolving and multi-party memory evaluation.
Source: `https://arxiv.org/abs/2602.01313`

**[E04] MINJA: A Practical Memory Injection Attack against LLM Agents** — 2025. Security research paper.
Retrieved and learned memory can become an attack channel.
Source: `https://arxiv.org/abs/2503.03704`

**[E05] Wasmtime Security** — Documentation checked 2026-09-09. Official documentation.
Sandboxed execution requires trustworthy host imports and resource controls.
Source: `https://docs.wasmtime.dev/security.html`

**[D01] OpenAI API prompt caching** — Documentation checked 2026-09-09. Official documentation.
Provider cache behavior is distinct from eliminating model-visible tokens.
Source: `https://developers.openai.com/api/docs/guides/prompt-caching`

**[D02] OpenAI API latency optimization** — Documentation checked 2026-09-09. Official documentation.
Reduce avoidable requests and critical-path work; provider latency is separately measured.
Source: `https://developers.openai.com/api/docs/guides/latency-optimization`
