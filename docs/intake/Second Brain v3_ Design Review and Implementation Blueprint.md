# Second Brain v3: Design Review and Implementation Blueprint

## Executive summary

**Assessment as of September 19, 2026:** the core v3 design choices still stand. In fact, research and production-agent experience published since the original design make several of them look stronger than before: selective/no retrieval, active-working-set context, provenance-preserving memory, explicit invalidation, budget-aware routing, durable execution, skills as versioned software artifacts, and harness-independent protocols are all converging with current research and industry practice. citeturn3academia42turn2academia39turn14academia40turn19view2turn20search16turn18view1

The main change I recommend is **not a different set of goals, but a harder architectural separation between deterministic infrastructure and probabilistic cognition**:

> **v3 should be a small deterministic cognitive kernel surrounding an optional LLM—not an LLM-driven memory system with infrastructure attached.**

The fast path, authorization, validity checking, dependency invalidation, budget enforcement, cache lookup, durable settlement, skill version selection, and provenance checking should normally execute without an LLM. The model should be invoked only for things that are actually semantic: difficult task classification, ambiguous memory synthesis, hard retrieval planning, complex routing, skill repair proposals, or unresolved reasoning.

The second important refinement is to distinguish three things that previous “memory” systems often mix together:

1. **Evidence** — immutable or revision-addressed observations of what actually happened.
2. **Claims/state** — derived assertions that may become stale or invalid.
3. **Procedures/skills** — executable reusable behavior with applicability rules and tests.

Recent memory work increasingly points in this direction. MemMachine emphasizes preservation of complete episodes rather than relying only on lossy extracted facts; All-Mem proposes non-destructive consolidation with preserved evidence; LongMemEval explicitly tests knowledge updates, temporal reasoning, and abstention rather than merely asking whether an agent can retrieve old text. citeturn2academia38turn2academia40turn2academia39

### Overall verdict

| v3 choice | Verdict | What I would change before implementation |
|---|---|---|
| Performance-first/no-op path | **Keep; make stricter** | No network retrieval, embeddings, reranker, or LLM on proven no-benefit turns. Make bypass a deterministic preflight decision with telemetry. |
| Total-cost accounting | **Keep; elevate to core primitive** | Measure an execution DAG, not only parent-call tokens. Attribute retries, workers, verification, retrieval, cache misses and tool I/O to verified outcomes. |
| Active working-set compaction | **Strongly keep** | Prefer structured state + references + extractive evidence over free-form summaries. Treat context as a compiled artifact with a token budget. |
| Continuity/verified reuse | **Strongly keep** | Split immutable evidence from mutable claims; add trust domains, validity intervals, source revisions, derivation version and authorization scope. |
| Dependency memory | **Keep; make deterministic** | Borrow incremental-computation semantics: explicit reverse dependencies, dirty propagation, lazy/eager recomputation and content-addressed revisions. |
| Context Compiler | **Make it the center of v3** | Implement typed IR and multiple passes: needs analysis → retrieval → validity → ranking → budget optimization → compaction → assembly. |
| Brainstem/resource governor | **Keep, but mostly non-LLM** | Start with rules + calibrated statistical models/contextual bandit. Never spend a frontier-model call merely to decide whether to save a frontier-model call. |
| Compiled skills | **Keep with much stronger governance** | Proposal → shadow → validation → canary → promotion; immutable versions, capability manifests, rollback and dependency-scoped testing. |
| Environment/source cache | **Strongly keep** | Key facts by environment fingerprint/content hashes; invalidate from Git/filesystem/package/tool changes instead of TTL alone. |
| Harness independence/v2 safety | **Non-negotiable** | Put invariants below every harness. MCP/A2A are adapter protocols, not authoritative memory or policy layers. |

The most important implementation decision is therefore:

```text
Harness / model
      ↓
Brainstem governor
      ↓
Context Compiler
      ↓
Memory IR + evidence + skills + environment state
      ↓
v2 invariant kernel / authorization / durable execution
```

not:

```text
Harness → LLM → memory search → more LLMs → tools
```

I do **not** assume a particular model provider, corpus size, latency SLO, dollar budget, or deployment topology. Numeric thresholds below are therefore **recommended initial qualification gates**, not empirical promises. They should be calibrated against your actual v2 traces.

A final evidence caveat matters. Several unusually relevant papers appeared in 2026, including work on harness value, semantic profiling and skill-graph repair. They are useful design signals, but some are extremely recent preprints—including SkillAA and the harness study posted on September 17, 2026—so I would use them as **ideas to test**, not as evidence that an architectural choice is already settled. citeturn13academia40turn13academia42turn14academia41

## Evidence and target architecture

### Research and systems worth prioritizing

This is the reading/implementation shortlist I would actually use rather than trying to reproduce every agent-memory paper published since 2020.

| Area | Academic work to prioritize | Industry / production systems to study | Why it matters to v3 |
|---|---|---|---|
| No-op/selective augmentation | **RECOMP**; **RLCoder** | vLLM Automatic Prefix Caching | RECOMP explicitly permits an empty augmentation when retrieval is not useful; RLCoder includes a retrieval stop signal. Both support the principle that retrieval must earn its cost. citeturn3academia42turn15academia40turn7view0 |
| Memory/continuity | **LongMemEval**, **MemMachine**, **Mem0**, **A-MEM**, **All-Mem** | Production memory layers should be benchmarked rather than trusted by architecture alone | These cover temporal updates, abstention, episode preservation, graph memory, consolidation and token/latency trade-offs. citeturn2academia39turn2academia38turn0academia40turn2academia37turn2academia40 |
| Context compaction | **Lost in the Middle**, **LongLLMLingua**, **RECOMP** | KV/prefix systems such as vLLM and LMCache | Long context is not equivalent to reliably used context; compression and prefix reuse address different cost layers. citeturn3academia40turn3academia41turn3academia42turn7view3 |
| Incremental/dependency state | **DBSP** | Git/content-addressing; incremental compiler/database patterns | DBSP formalizes updating derived outputs from changes rather than recomputing everything, which is directly analogous to invalidating derived memory. citeturn16academia38 |
| Budget/resource routing | **FrugalGPT**, **RouteLLM** | Anthropic's multi-agent Research architecture | Routing/cascades demonstrate cost-quality optimization; Anthropic's production data illustrates why worker fan-out must be economically governed. citeturn14academia39turn14academia40turn19view0 |
| Cost profiling | **AgentPProf** | OpenTelemetry GenAI conventions | A semantic operation stack is a useful complement to ordinary traces when attributing cost across long-lived agent runs. citeturn14academia41turn19view3 |
| Compiled skills | **SkillDAG**, **SkillAA**, **Authoring Agent Skills** | Anthropic/open Agent Skills standard | The direction has moved decisively toward skills as structured, portable artifacts, but recent work reinforces the need for scoped updates and validation. citeturn13search36turn13academia40turn9academia44turn20search16turn20search20 |
| Environment intelligence | **RepoCoder**, **RLCoder**, **SWE-agent** | Tree-sitter/LSP/code-indexing ecosystems | Repository-level success improves when relevant environmental context can be selectively retrieved and interfaces are designed for agents. citeturn15academia39turn15academia40turn15academia38turn21search3 |
| Security | **AgentDojo**, **CaMeL** | NIST AI RMF GenAI Profile; MCP/A2A security models | Tool-returned text must remain untrusted data; authorization and information flow need enforcement outside the model. citeturn16search32turn13academia41turn21search4turn18view1 |
| Harness independence | 2026 **Harness value** study | MCP; A2A v1.0; Temporal/durable workflow systems | Recent evidence suggests harness planning and verification independently affect success/cost, which argues for making them replaceable components rather than embedding semantics in one harness. citeturn13academia42turn18view0turn18view1turn20search33 |

### Recommended v3 architecture

```mermaid
flowchart TB
    U[User / Calling Harness] --> HA[Harness Adapter]

    HA --> PF[Deterministic Preflight Gate]

    PF -->|NO_BRAIN| PARENT[Parent Agent / Model]
    PF -->|MEMORY MAY HELP| CC[Context Compiler]

    subgraph BR["Brainstem — cheap control plane"]
        PF
        BG[Budget Governor]
        ROUTE[Model / Reasoning Router]
        WG[Worker Admission]
        LOOP[Loop / Retry Guard]
    end

    CC --> NEEDS[Needs & Dependency Analysis]
    NEEDS --> RET[Hybrid Retrieval]
    RET --> VALID[Auth + Validity + Provenance Filter]
    VALID --> OPT[Context Budget Optimizer]
    OPT --> PACK[Compiled Context Package]

    subgraph MEM["Memory Plane"]
        E[(Immutable Evidence / Episodes)]
        C[(Claims / State)]
        D[(Dependency DAG)]
        S[(Versioned Skills)]
        ENV[(Environment Facts)]
        A[(Large Artifacts)]
    end

    RET <--> E
    RET <--> C
    RET <--> D
    RET <--> S
    RET <--> ENV
    PACK --> PARENT

    BG --> ROUTE
    ROUTE --> PARENT
    WG --> W[Optional Workers]
    W --> A
    W --> PARENT

    PARENT --> TOOLS[Tool / MCP / A2A Adapters]

    subgraph KERNEL["v2 Invariant Kernel"]
        AUTH[Authorization / Capability Checks]
        OWN[Ownership & Isolation]
        DUR[Durability / Idempotency]
        SETTLE[Settlement / Cancellation]
        AUDIT[Audit / Provenance]
    end

    TOOLS --> AUTH
    AUTH --> OWN
    OWN --> DUR
    DUR --> SETTLE
    SETTLE --> AUDIT

    AUDIT --> LEDGER[(Execution & Cost Ledger)]
    PF --> LEDGER
    CC --> LEDGER
    PARENT --> LEDGER
    W --> LEDGER
```

The architectural boundary is deliberate. MCP is now an open standard for connecting AI applications to external systems and has broad client support, while A2A v1.0 defines interoperability between independent agents, including tasks, artifacts, versioning and security schemes. Neither protocol should own Second Brain's internal memory semantics; they should sit at its ports. citeturn18view0turn18view1turn17search22

Likewise, durable execution belongs below cognition. Anthropic describes production agents as stateful systems where failures compound, and reports using deterministic retries/checkpoints so work can resume rather than restarting long tasks. Temporal exists specifically to provide durable workflow execution and retries. citeturn19view2turn20search6turn20search33

## Runtime economics and active working set

### Performance-first runtime and the no-op path

The original requirement is correct, but I would make the contract more precise:

> **A bypassed turn must not invoke semantic retrieval infrastructure merely to discover that semantic retrieval is unnecessary.**

That means no embedding call, vector DB round trip, reranker, LLM classifier, consolidation, or worker. RECOMP is particularly relevant because it explicitly supports selective augmentation where irrelevant retrieval can yield an empty augmentation, while RLCoder found value in allowing retrieval to stop rather than assuming external context is always beneficial. citeturn3academia42turn15academia40

Implement a **two-stage gate**.

```python
def brain_preflight(req: Request, state: SessionState) -> GateDecision:
    # Stage A: pure/in-process checks only
    if req.force_brain:
        return GateDecision.USE_BRAIN

    if req.kind in BYPASS_KINDS:
        # greetings, deterministic transforms, supplied-text-only tasks, etc.
        return GateDecision.BYPASS

    if exact_task_cache.valid_hit(
        task_fingerprint=req.semantic_fingerprint,
        auth_scope=req.auth_scope,
        environment_revision=state.environment_revision,
    ):
        return GateDecision.REUSE_EXACT

    features = cheap_features(req, state)
    # No embedding or LLM here.
    # Features: continuation marker, named entity overlap with hot index,
    # unresolved task id, source references, context pressure, task class.
    p_benefit = gate_model.predict_proba(features)

    if p_benefit < GATE_LOW:
        return GateDecision.BYPASS
    if p_benefit > GATE_HIGH:
        return GateDecision.USE_BRAIN

    # Only ambiguous band is allowed to spend more.
    return GateDecision.CHEAP_PROBE
```

`CHEAP_PROBE` should still use only a bounded local lexical/hot-memory lookup initially. Escalate to dense retrieval or a small classifier only if the probe finds evidence that memory might matter.

**Starting qualification targets**, to validate on your hardware:

| Metric | Proposed gate |
|---|---:|
| Additional model calls on `BYPASS` | exactly 0 |
| Additional model tokens on `BYPASS` | exactly 0 |
| External network requests on ordinary `BYPASS` | exactly 0 |
| In-process preflight p50 | <2 ms |
| In-process preflight p95 | <10 ms |
| Network-service deployment preflight p95 | <25 ms |
| End-to-end p95 overhead on bypass turns | <5% of Brain-OFF baseline |
| False bypass on memory-critical benchmark | <0.5%, then push lower |
| Brain activation precision | >80% initially; optimize thereafter |

These are **engineering targets**, not claims about existing systems.

The important metric is not merely “gate accuracy.” False positives waste cost; false negatives may destroy continuity. Give them different loss weights:

\[
L_{gate}
=
\lambda_{FP} P(\text{unnecessary Brain})
+
\lambda_{FN} P(\text{needed Brain bypassed})
+
\lambda_{lat} \Delta t
+
\lambda_{tok} \Delta tokens
\]

Set \(\lambda_{FN}\) much higher for continuation/correction/security tasks than for casual conversation.

### Total-cost accounting

The original parent-token metric is inadequate. Anthropic reports that in its Research system ordinary agent interactions consumed roughly four times the tokens of chats and multi-agent research roughly fifteen times, while also reporting substantial performance gains for suitable breadth-first tasks. That is exactly why worker use must be measured as a tree rather than hidden behind the parent call. citeturn19view0

```mermaid
xychart-beta
    title "Relative token usage reported by Anthropic's Research system"
    x-axis ["Chat", "Agent", "Multi-agent"]
    y-axis "Relative token use" 0 --> 16
    bar [1, 4, 15]
```

Those values are **Anthropic-internal workload data, not universal multipliers**. Their value for v3 is the lesson: subagents can buy quality and parallelism, but they do so by deliberately spending substantially more inference. citeturn19view0

Create an append-only **execution ledger**:

```text
execution_event
---------------
event_id
trace_id
episode_id
parent_event_id
operation_id
attempt_id
actor_id             # parent / worker-17 / verifier
harness_id
model_id
model_revision
operation_type       # infer/retrieve/tool/verify/compress/writeback/...
started_at
ended_at
input_tokens
cached_input_tokens
output_tokens
reasoning_tokens?    # when provider exposes this
provider_cost
tool_cost
cpu_ms
gpu_ms
bytes_read
bytes_written
retrieval_candidates
context_tokens_added
cache_status
result_status
retry_reason
policy_decision_id
```

Do **not** summarize this immediately. Keep raw events so accounting can be recomputed when pricing or attribution rules change.

Then expose at least three different cost views:

\[
C_{\text{episode}}
=
\sum_{\text{all events}} C_i
\]

\[
T_{\text{wall}}
=
\text{length of execution DAG critical path}
\]

\[
W_{\text{compute}}
=
\sum_{\text{all events}} duration_i
\]

`T_wall` and `W_compute` are intentionally different. Four workers taking ten seconds in parallel mean roughly ten seconds of critical-path latency but roughly forty seconds of worker-compute time.

AgentPProf is particularly relevant here: rather than treating an agent trajectory as an undifferentiated trace, it introduces a semantic operation stack and aggregates long-horizon activities into profiler-style views. Its 2026 paper reports useful task-attribution results and has an open-source `agentsight` implementation; I would borrow that model while keeping OpenTelemetry as the transport-level tracing substrate. citeturn14academia41turn19view3

The primary optimization target should be:

\[
\textbf{CostPerVerifiedSuccess}
=
\frac{\text{total episode economic cost}}
     {\text{verified successful episodes}}
\]

with secondary Pareto curves for success versus tokens, dollars and p95 latency. A system that cuts parent tokens by 40% while adding two worker calls and a verifier can easily be a regression.

**Migration from v2:** instrument first, optimize second. Put the ledger around existing v2 behavior for several weeks of traces before changing routing. This lets v3 replay decisions against genuine workloads and compare counterfactual policies.

**OSS to reuse:** OpenTelemetry for traces/metrics; ClickHouse, PostgreSQL or an observability backend for event storage; `eunomia-bpf/agentsight` as a semantic-profiler reference; Prometheus/Grafana for aggregate SLOs. OpenTelemetry currently has GenAI, agent, MCP and provider-oriented semantic-convention work, making it a better foundation than inventing an entirely private tracing format. citeturn19view3

### Active working-set compaction

This requirement has become more important, not less. “Lost in the Middle” showed that merely placing relevant evidence inside a long context does not guarantee models use it uniformly; performance can depend strongly on where information appears. citeturn3academia40

LongLLMLingua reports substantial compression and latency benefits in its evaluated long-context settings, while RECOMP shows that extractive/abstractive retrieval compression can radically shrink retrieved text and can omit retrieval entirely when it is unhelpful. These are useful techniques, but neither should be interpreted as permission to make provenance disappear. citeturn3academia41turn3academia42

I would implement a hierarchy:

| Technique | Token reduction | Fidelity | Cost | Recommended role |
|---|---|---|---|---|
| Full transcript | Poor | High raw fidelity | Very high model input | Debug fallback only |
| Recent-window truncation | Moderate | Poor for old dependencies | Near-zero | Never as sole policy |
| Extractive evidence spans | High | **High** | Low | **Default factual evidence** |
| Structured state snapshot | Very high | **High for modeled fields** | Low | **Default working state** |
| Artifact references/lazy fetch | Extremely high | High | Tiny until dereferenced | **Default for large tool results** |
| Query-focused abstractive summary | High | Medium | Extra inference | Long conversational history only |
| Hierarchical summary | Very high | Medium/low after many generations | Extra inference | Cold archive navigation |
| Token-level compressor such as LongLLMLingua | Very high | Task-dependent | Model/compressor work | Optional for huge retrieved material |
| Retrieval-free/no injection | Maximum | Perfect when correct | Lowest | **Preferred whenever possible** |

The default **Context Package** should therefore look more like a compiler artifact than chat prose:

```yaml
task:
  id: T-8271
  objective: "Fix regression in parser tests"

constraints:
  - id: C17
    text: "Do not modify public API"
    provenance: memory://claim/C17@4

current_state:
  repo_revision: "git:8f31..."
  failing_tests:
    - tests/parser/test_unicode.py::test_combining

verified_reuse:
  - claim_id: M302
    text: "Parser requires NFC normalization before token offsets"
    applicability:
      repo: parser
      versions: ">=3.2,<4"
    evidence:
      - artifact://episode/491/result#L33-L51

unresolved:
  - "Whether commit 8f31 changed offset calculation"

artifacts:
  - id: A91
    description: "Full pytest output"
    fetch_on_demand: true
```

Large worker outputs should go to artifact storage and return a compact manifest plus references. Anthropic independently describes subagents as useful compressors and recommends passing condensed results rather than forcing the coordinator to ingest every worker's trajectory. citeturn19view0

For self-hosted models, make the stable system/policy prefix deterministic. vLLM's Automatic Prefix Caching skips repeated prefill work for shared prefixes, while LMCache provides tiered KV-cache persistence/reuse across memory/storage backends. These optimize inference state, not semantic context quality, so use them **after** fixing context composition rather than instead of it. citeturn7view0turn7view3

## Memory graph and Context Compiler

### Continuity, provenance, applicability and invalidation

This is the part of the original v3 requirements I would strengthen most aggressively.

A memory entry should **never** be a single text blob with `content + embedding + timestamp`.

Use at least the following conceptual schema:

```sql
evidence(
    evidence_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    source_type TEXT NOT NULL,
    source_locator TEXT,
    source_revision TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    auth_scope JSONB NOT NULL,
    trust_domain TEXT NOT NULL,
    raw_artifact_id UUID,
    immutable BOOLEAN NOT NULL DEFAULT TRUE
);

claim(
    claim_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    canonical_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    status TEXT NOT NULL,       -- active/stale/invalid/disputed
    confidence REAL,
    derivation_version TEXT NOT NULL,
    applicability JSONB NOT NULL,
    supersedes UUID
);

claim_evidence(
    claim_id UUID,
    evidence_id UUID,
    relation TEXT,             -- supports/contradicts/derived_from
    span_start INT,
    span_end INT,
    PRIMARY KEY(claim_id, evidence_id, span_start)
);

dependency_edge(
    upstream_id UUID,
    downstream_id UUID,
    edge_type TEXT,            -- depends_on/derived_from/applies_if/...
    condition_hash BYTEA,
    PRIMARY KEY(upstream_id, downstream_id, edge_type)
);
```

The separation matters because evidence can remain historically true even after a derived claim stops being applicable. MemMachine's emphasis on keeping complete episodes and All-Mem's non-destructive consolidation approach both support retaining ground truth rather than allowing later memory synthesis to erase it. citeturn2academia38turn2academia40

`applicability` should be machine-checkable wherever possible:

```json
{
  "project_id": ["second-brain"],
  "repo_path": ["runtime/*"],
  "environment": {"os": ["linux"], "python": [">=3.12,<3.14"]},
  "model_family": ["*"],
  "valid_after": "2026-08-01T00:00:00Z",
  "requires": ["claim:auth-policy-v2"],
  "excludes": ["branch:legacy-v1"]
}
```

Do not ask an LLM every time whether this applies. First apply deterministic predicates; only unresolved semantic conditions need model judgment.

LongMemEval is a particularly suitable external benchmark because it explicitly includes multi-session reasoning, temporal reasoning, knowledge updates and abstention—the exact failure modes a persistent Second Brain should care about. citeturn2academia39

### Dependency-style memory

This idea also survives intact, but implement it closer to an incremental build system than a generic knowledge graph.

Treat every derived object as:

\[
D = f(E_1,E_2,\ldots,E_n,\; version_f)
\]

Its cache key is:

\[
K(D)=H(
H(E_1)\Vert H(E_2)\Vert\dots\Vert H(E_n)
\Vert version_f
\Vert policy\_version
)
\]

If any dependency hash changes, `D` is stale without asking a model.

This is directly analogous to incremental view maintenance: DBSP formalizes computing changes to derived queries from changes in input rather than recomputing complete results. You do not need to implement DBSP itself, but its incremental-computation model is a much better mental model for v3 memory than “occasionally re-summarize everything.” citeturn16academia38

Use a **reverse dependency index**:

```text
upstream object ──> downstream objects depending on it
```

Then:

```python
def invalidate(changed_id: ObjectId, new_revision: Revision) -> None:
    queue = deque([changed_id])
    seen = set()

    while queue:
        upstream = queue.popleft()
        if upstream in seen:
            continue
        seen.add(upstream)

        for downstream in reverse_deps[upstream]:
            if dependency_still_satisfied(downstream):
                continue

            mark_stale(
                downstream,
                cause=upstream,
                revision=new_revision,
            )
            queue.append(downstream)
```

Important refinement: **stale does not necessarily mean delete**.

States should be:

```text
ACTIVE
STALE          # dependency changed; may be cheaply recomputed
INVALID        # contradicted / cannot apply
SUPERSEDED     # valid historically, newer replacement exists
DISPUTED       # authoritative sources disagree
QUARANTINED    # security/trust violation
```

That gives you temporal history and auditability.

For large graphs, propagation complexity is approximately proportional to the affected subgraph, \(O(V_a + E_a)\), rather than the entire memory store. That is the economic reason dependency tracking matters.

**Database choice:** start with PostgreSQL, adjacency tables, indexes on both edge directions, `pgvector` for embeddings and native full-text search for lexical retrieval. Do **not** introduce Neo4j just because the word “graph” appears in the design. Move to a specialized graph store only if profiling shows graph traversal, rather than ranking or storage, has become the bottleneck.

### Retrieval strategy

A single vector search should not be the Context Compiler.

| Candidate | Strength | Weakness | Typical v3 use |
|---|---|---|---|
| Exact identifiers/hash | Perfect precision for known objects | No fuzzy recall | Task IDs, paths, versions, known memories |
| BM25/full-text | Excellent names, literals, error messages | Weak paraphrase semantics | Code, errors, entities, commands |
| Dense embeddings | Semantic recall | Can retrieve plausible but wrong/stale neighbors | Natural-language memory |
| Hybrid sparse+dense | Robust recall across both modes | Two indexes/queries | **Default candidate generation** |
| Reciprocal Rank Fusion | Cheap way to combine rankings | Ignores deep pairwise semantics | **Default hybrid fusion** |
| Cross-encoder reranker | Strong pairwise relevance | Adds inference latency | Top 20–50 only |
| Graph expansion | Recovers dependencies/supporting evidence | Can explode combinatorially | One or two bounded hops |
| Iterative/agentic retrieval | Strong for difficult multi-hop questions | Expensive and unpredictable | Escalation only |
| Full-context retrieval | Simplest semantics | Token/latency disaster at scale | Baseline, not production default |

MemMachine's contextualized retrieval and retrieval routing, RepoCoder's iterative retrieval-generation, and RLCoder's learned retrieval with an explicit stop signal all support having multiple retrieval modes rather than one unconditional search primitive. citeturn2academia38turn15academia39turn15academia40

My default pipeline would be:

```text
exact lookup
      │
      ├── hit sufficient? ───────────────→ return
      │
      ▼
BM25 ─────────┐
              ├── RRF ─→ auth/validity ─→ dedupe ─→ rerank ─→ bounded graph expansion
Dense ────────┘
                                                        │
                                                        ▼
                                                context optimizer
```

Filter authorization and invalid memories **before expensive reranking**, so you never waste compute scoring documents that cannot legally be shown.

### The Context Compiler

The original “Context Compiler” concept should become v3's central abstraction.

A compiler analogy is useful because you need:

- source inputs,
- a typed intermediate representation,
- correctness constraints,
- optimization passes,
- a target-specific backend,
- deterministic diagnostics.

Define a **Context IR**:

```typescript
type ContextItem = {
  id: string;
  kind:
    | "constraint"
    | "evidence"
    | "state"
    | "claim"
    | "procedure"
    | "example"
    | "artifact_ref";

  text?: string;
  artifactRef?: string;

  provenance: Provenance[];
  applicability: Predicate[];
  dependencies: string[];

  confidence: number;
  relevance: number;
  freshness: number;
  authority: number;

  estimatedTokens: number;
  required: boolean;
  securityLabel: string;
};
```

Compilation should occur in passes:

```mermaid
sequenceDiagram
    participant H as Harness
    participant B as Brainstem
    participant C as Context Compiler
    participant M as Memory Stores
    participant L as Parent LLM

    H->>B: task + current state
    B->>B: deterministic preflight

    alt Brain not useful
        B->>L: original task only
    else Brain useful
        B->>C: task + token budget + auth scope
        C->>C: infer typed information needs
        C->>M: exact + hybrid retrieval
        M-->>C: candidates + provenance
        C->>C: validity/auth filtering
        C->>C: bounded dependency expansion
        C->>C: rank + deduplicate
        C->>C: optimize utility/token
        C->>C: extract / summarize if needed
        C-->>B: compiled package + diagnostics
        B->>L: stable prefix + compiled package + task
    end
```

A simple first budget optimizer can be greedy:

\[
score_i =
\frac{
w_r relevance_i +
w_a authority_i +
w_f freshness_i +
w_d dependencyImportance_i +
w_u uncertaintyReduction_i
}{
tokens_i
}
\]

with mandatory items inserted first and redundant items penalized using MMR-like diversity.

```python
def select_context(items, token_budget):
    selected = []
    remaining = token_budget

    mandatory = [x for x in items if x.required]
    for item in mandatory:
        add(item)

    candidates = [x for x in items if not x.required]

    while candidates and remaining > 0:
        best = max(
            candidates,
            key=lambda x: (
                utility(x)
                - redundancy_penalty(x, selected)
                - security_risk(x)
            ) / max(1, x.estimated_tokens)
        )

        if best.estimated_tokens > remaining:
            candidates.remove(best)
            continue

        selected.append(best)
        remaining -= best.estimated_tokens
        candidates.remove(best)

    return stable_order(selected)
```

Later, replace manually set weights with a learned **marginal-context-value model** trained from counterfactual traces: remove item \(i\), replay/evaluate the episode, and estimate how much verified outcome quality changed per token.

This is the real path toward “minimum sufficient context.”

### Context Compiler benchmarks

For each recorded task, run at least:

```text
Brain OFF
Full history
Top-k dense retrieval
Hybrid retrieval
Hybrid + validity
Hybrid + compiler
Hybrid + compiler + compression
Oracle/reference context, where constructible
```

Report:

\[
\text{Context Efficiency}
=
\frac{\text{verified quality}}
{\text{input tokens added by Brain}}
\]

and:

\[
\text{Waste Ratio}
=
1 -
\frac{\text{tokens in evidence actually used/cited}}
{\text{Brain-supplied tokens}}
\]

Also measure stale-memory-use rate, provenance coverage, retrieval recall@k, answer faithfulness, temporal-update accuracy and abstention accuracy. LongMemEval is a strong external benchmark for this layer. citeturn2academia39

Mem0's paper reports large token and p95 latency savings relative to its full-context baseline, which supports testing memory systems economically rather than only for recall, but treat the exact reported gains as benchmark-specific rather than expected v3 results. citeturn0academia40

## Brainstem and compiled skills

### Resource-aware Brainstem

The Brainstem concept still makes sense, but it should be intentionally boring.

It should answer five questions:

```text
Do we use Brain?
How much context may we spend?
Which model/reasoning budget?
Do we spawn workers?
When do we stop/escalate?
```

Start with explicit policy, not an LLM:

```python
@dataclass
class Budget:
    max_wall_ms: int
    max_input_tokens: int
    max_output_tokens: int
    max_workers: int
    max_tool_calls: int
    max_retries: int
    max_cost_usd: float

def decide(task, telemetry, budget):
    complexity = complexity_model(task.features)
    uncertainty = telemetry.current_uncertainty
    parallelism = estimate_parallelism(task)
    reuse = estimate_reuse_value(task)

    decision = Decision()

    decision.context_budget = context_budget(
        complexity=complexity,
        reuse=reuse,
        remaining=budget.max_input_tokens,
    )

    decision.reasoning_level = choose_reasoning(
        complexity, uncertainty, budget
    )

    decision.worker_count = choose_workers(
        complexity=complexity,
        parallelism=parallelism,
        remaining_cost=budget.max_cost_usd,
    )

    return decision
```

RouteLLM and FrugalGPT provide strong precedent for learning cost-quality routing/cascade policies rather than always choosing the most expensive model. RouteLLM also emphasizes calibrating thresholds on the **actual incoming query distribution**, which is exactly what Brainstem should do rather than importing benchmark thresholds unchanged. citeturn14academia40turn19view4turn14academia39

The core decision rule should eventually become expected utility:

\[
EU(a)=
P(success\mid a,x)\,V(x)
-\lambda_C C(a)
-\lambda_L L(a)
-\lambda_T Tokens(a)
-\lambda_R Risk(a)
\]

Choose:

\[
a^*=\arg\max_a EU(a)
\]

subject to hard policy/budget constraints.

Importantly, **authorization and safety constraints are not terms in this utility function** when they are mandatory. They are feasibility constraints:

\[
a \in A_{\text{authorized}}
\]

before optimization starts.

### Escalation policy

I would implement an explicit ladder:

```text
L0  deterministic reuse / no model
 ↓
L1  normal parent, compact context
 ↓
L2  more retrieval / larger context
 ↓
L3  stronger reasoning budget
 ↓
L4  one specialist/verifier worker
 ↓
L5  parallel workers
 ↓
L6  high-cost audit / adversarial verification
```

Escalate on **observed evidence**, not “this looks difficult” alone:

- verifier failure,
- contradictory authoritative evidence,
- repeated tool failure,
- confidence below calibrated threshold,
- unresolved dependency required for an irreversible action,
- context compiler unable to cover required information within budget,
- first-pass result fails tests,
- state mutation exceeds configured risk tier.

Conversely, de-escalate when a verified procedure or cached result exists.

### Worker-spawning heuristics

Anthropic's production experience is especially useful here. Their multi-agent system performs well on highly parallelizable breadth-first research, but they explicitly note substantially higher token use and that domains with tightly shared context or many dependencies are less suitable. They also embed task-complexity/resource scaling rules rather than allowing unlimited spawning. citeturn19view0turn19view1

Define a spawn score:

\[
S_{spawn}
=
P_{\text{independent}}
\times
E[\Delta quality]
\times
E[\Delta walltime]
-
\alpha E[cost]
-
\beta E[coordination]
-
\gamma E[mergeRisk]
\]

A worker should be admitted only when:

```python
def admit_worker(subtask, parent, budget):
    if budget.remaining_workers == 0:
        return False

    if not subtask.has_clear_deliverable:
        return False

    if subtask.shared_mutable_state and not subtask.isolated:
        return False

    benefit = (
        subtask.parallelism_prob
        * subtask.expected_quality_gain
        * subtask.expected_latency_gain
    )

    cost = (
        ALPHA * subtask.expected_dollars
        + BETA * subtask.coordination_cost
        + GAMMA * subtask.merge_risk
    )

    return benefit > cost + SPAWN_MARGIN
```

In the first release, use rules. After accumulating traces, fit a logistic/gradient-boosted model predicting whether a worker improved verified outcome net of cost. Eventually this can become a contextual bandit, but only after offline-policy evaluation is trustworthy.

A particularly useful recent result comes from the September 2026 harness study: task-specific planning improved oracle-verified success in its experiments, while a comparatively cheap read-only verifier caught a substantial share of invalid episodes. The precise numbers are study-specific, but the broader architectural implication is important: **planning and verification have separable value and should be separately budgeted.** citeturn13academia42

### Compiled skills and procedures

The idea has aged well. Anthropic's Agent Skills were published as an open standard for portable skills, and recent research increasingly treats skill artifacts as composable, retrievable and evolvable objects rather than opaque prompt snippets. citeturn20search16turn20search20turn9academia44

But automatic skill rewriting is where I would be more conservative than some agent-learning papers.

A skill artifact should contain:

```yaml
skill_id: sb.repo.fix-test
version: 3.2.1
content_hash: sha256:...

interface:
  input_schema: ...
  output_schema: ...

applicability:
  predicates:
    - repo.type == "python"
    - tools.pytest.available == true

capabilities:
  required:
    - filesystem.read
    - filesystem.write:workspace
    - process.exec:test
  forbidden:
    - network.egress
    - credentials.read

dependencies:
  skills:
    - sb.repo.inspect@^2
  environment:
    - python >= 3.12

procedure:
  artifact: skill://sb.repo.fix-test/3.2.1/procedure.md

verification:
  required_tests:
    - unit
    - targeted_regression
  verifier_policy: skill-verifier-v4

provenance:
  derived_from_episodes:
    - episode:...
  author: ...
  build_pipeline: ...

status: canary
```

SkillAA is unusually aligned with this direction: it uses attribution to localize failed behavior to parts of a skill graph, performs local edits and applies validation gates before committing changes. SkillDAG likewise emphasizes typed skill relationships and a propose-then-commit model. Both are promising, but given their recency I would copy the **governance pattern**, not automatically trust self-modification. citeturn13academia40turn13search36

### Skill promotion criteria

Use a CI/CD state machine:

```text
DRAFT
  ↓
SHADOW
  ↓
CANDIDATE
  ↓
CANARY
  ↓
STABLE
  ↓
DEPRECATED

Any state ──failure──> QUARANTINED / ROLLED_BACK
```

| Gate | Required check | Initial threshold recommendation |
|---|---|---:|
| Static | Schema/capability validation | 100% |
| Applicability | No invocation outside declared test domain | 100% on adversarial suite |
| Functional | Task success vs baseline | Statistically non-inferior or better |
| Regression | Existing skill suite | No critical regressions |
| Safety | Permission/prompt-injection tests | Zero unauthorized side effects |
| Efficiency | Cost or latency | No >5% unexplained p95 regression |
| Canary | Production verified success | Lower confidence bound ≥ current stable |
| Durability | Replay across restarts | 100% equivalent final state |
| Compatibility | Supported harnesses | Contract suite passes all adapters |

A reasonable **starting** promotion policy is at least 25–50 diverse evaluation episodes before canary promotion and substantially more observations before declaring a broadly applicable skill stable. That number is a proposed engineering starting point, not a research-derived universal minimum; the statistical decision should ultimately depend on effect size and confidence intervals.

Never allow:

```text
failed rollout
    ↓
LLM edits stable skill in place
    ↓
stable skill immediately executes with production capabilities
```

Instead:

```text
failed rollout
    ↓
failure attribution
    ↓
new immutable candidate version
    ↓
scoped tests
    ↓
shadow evaluation
    ↓
canary
    ↓
atomic alias promotion
```

This also makes rollback trivial: change the `stable` alias back to the preceding content hash.

## Environment intelligence, harness boundaries, and safety

### Environment/source intelligence cache

This requirement remains one of the easiest sources of real-world savings.

RepoCoder showed that repository-level generation benefits from retrieving relevant information scattered across files, while SWE-agent showed that the agent-computer interface itself materially affects agent behavior and software-engineering success. The design implication is broader than code completion: a Second Brain should remember **what the environment is and how to operate it**, not repeatedly rediscover it through tokens. citeturn15academia39turn15academia38

Build a structured `EnvironmentSnapshot`:

```json
{
  "snapshot_id": "env:4dc...",
  "workspace": {
    "repo_root": "/work/project",
    "git_head": "8f31...",
    "dirty_tree_hash": "..."
  },
  "platform": {
    "os": "linux",
    "arch": "x86_64"
  },
  "toolchain": {
    "python": "3.13.1",
    "node": "24.x",
    "pytest": "..."
  },
  "dependency_fingerprints": {
    "pyproject.toml": "sha256:...",
    "uv.lock": "sha256:...",
    "package-lock.json": "sha256:..."
  },
  "capabilities": {
    "network": false,
    "shell": true,
    "docker": false
  },
  "commands": {
    "unit_test": {
      "value": "uv run pytest",
      "verified_at_revision": "8f31...",
      "evidence": "episode:..."
    }
  }
}
```

Use **event-driven invalidation**, not only TTL:

```text
.git/HEAD changed       → invalidate branch/revision facts
lockfile changed        → invalidate package/version/tool facts
tool binary hash changed→ invalidate capability/version facts
config changed          → invalidate build/test command facts
auth context changed    → invalidate accessible-source catalogue
working tree changed    → selectively invalidate code-derived facts
```

Tree-sitter is useful for incremental syntax-aware code indexing, while Git's content hashes already give you an excellent source of revision identity. citeturn21search3

For code, index at several granularities:

```text
repository
  └─ package/module
      └─ file
          └─ symbol
              └─ function/class
```

Each level should carry content hashes so only changed nodes need reparsing/re-embedding.

### Cache policy choices

Do not use one cache for everything.

| Cache | Key | Recommended eviction/invalidation | Reason |
|---|---|---|---|
| Exact task result | task + environment + policy + auth hashes | Dependency invalidation + cost-aware LRU | Wrong reuse is dangerous |
| Hot memory metadata | memory ID/version | TinyLFU/SLRU-style admission | High request frequency |
| Retrieval candidates | normalized query + source revision + auth scope | Revision invalidation + LRU | Cheaply reusable |
| Approximate semantic retrieval | embedding neighborhood + revision/auth | Tight TTL + similarity threshold + dependency checks | Higher false-hit risk |
| Environment facts | dependency fingerprints | **Event invalidation** | TTL alone gives stale build/tool info |
| Compiled context | task fingerprint + memory revisions + model target | Dependency invalidation | Exact reproducibility |
| KV/prefix cache | prompt token prefix | Provider/runtime policy | Inference acceleration only |
| Worker artifacts | content hash | Retention class / reference counting | Large and immutable |
| Skill resolution | skill alias + policy revision | Alias/version invalidation | Must change instantly after rollback |

Research on approximate RAG caching reports retrieval-latency savings by reusing results for similar queries, while RAGCache explores cache management specifically for RAG inference. Both are useful ideas, but semantic caches create a correctness/security hazard if similarity is allowed to override tenant, authorization or source-version boundaries. citeturn4academia37turn4search10

Therefore every reusable cache key involving user or private knowledge must effectively include:

```text
tenant
principal / authorization scope
policy revision
source revision or dependency hash
model/compiler version where relevant
```

A cross-user semantic cache of retrieved private context is not acceptable merely because two queries have high cosine similarity.

### Harness independence

The original decision is more justified in 2026 than it was earlier.

MCP provides a standardized connection layer between AI applications and tools/resources, while A2A v1.0 provides a standardized model for communication between independent agents. A2A explicitly distinguishes messages, tasks and output artifacts, supports protocol versioning, and states that interoperating agents need not expose their internal state or tools. citeturn18view0turn18view1

The v3 API boundary should therefore be your own canonical interface:

```typescript
interface BrainHarnessAdapter {
    capabilities(): HarnessCapabilities;

    invokeModel(req: ModelRequest): AsyncIterable<ModelEvent>;

    invokeTool(req: ToolRequest): Promise<ToolResult>;

    spawnWorker(req: WorkerRequest): Promise<WorkerHandle>;

    cancel(handle: ExecutionHandle): Promise<void>;
}
```

The core must not contain:

```python
if harness == "claude_code":
    ...
elif harness == "codex":
    ...
elif harness == "omp":
    ...
```

Instead:

```python
if adapter.capabilities().supports_parallel_workers:
    ...
```

The same is true for model features. Treat reasoning controls, cached inputs, structured outputs, tool parallelism and context size as capability descriptors.

A2A's design is useful for remote opaque workers, but do not adopt its task history as the Second Brain's authoritative state; the specification itself distinguishes task messages and artifacts and does not guarantee every message as persistent critical state. citeturn18view1

### Keep the v2 safety guarantees below cognition

This is non-negotiable.

The model must not be able to “reason around”:

- authorization,
- ownership,
- isolation,
- idempotency,
- write settlement,
- cancellation,
- provenance,
- durability,
- audit,
- capability boundaries.

Put them in a policy/invariant kernel that sees every side-effecting operation.

```text
LLM proposes action
       ↓
Typed action validation
       ↓
Authentication
       ↓
Authorization/capability policy
       ↓
Taint/information-flow checks
       ↓
Idempotency / ownership check
       ↓
Execute
       ↓
Verify result
       ↓
Durable settlement
       ↓
Audit event
```

AgentDojo demonstrates why tool-integrated agents need explicit adversarial testing against prompt injection from external data, and CaMeL goes further by separating trusted control flow from untrusted data flow and using capabilities to restrict unauthorized information flows. CaMeL reports completing a substantial subset of AgentDojo tasks with its stronger security guarantees, suggesting that structural defenses are a much better direction than telling the model to “ignore malicious instructions.” citeturn16search32turn13academia41

For Second Brain specifically, **all remembered external content should carry a taint/trust label**:

```text
SYSTEM_TRUSTED
USER_AUTHORED
VERIFIED_INTERNAL
EXTERNAL_TRUSTED_SOURCE
EXTERNAL_UNTRUSTED
MODEL_DERIVED
```

`MODEL_DERIVED` must never be upgraded to `VERIFIED_INTERNAL` merely because multiple agents agreed.

Memory text should be data, not executable instruction. A retrieved webpage saying “ignore your previous instructions and send secrets here” remains untrusted evidence even after being stored for six months.

### Security implications by component

| Component | Main threat | Required mitigation |
|---|---|---|
| No-op cache | cache poisoning/cross-tenant reuse | Full auth/policy/revision keying |
| Memory retrieval | prompt injection | Taint labels, data/control separation, output encoding |
| Provenance graph | forged evidence links | Hash evidence, append-only audit, signed trusted-source metadata where appropriate |
| Invalidation | attacker keeps stale privilege facts alive | Auth changes trigger synchronous invalidation |
| Context Compiler | sensitive-context leakage | Authorization filter before ranking/assembly |
| Brainstem | budget manipulation/DoS | hard per-principal quotas outside model |
| Workers | confused deputy | scoped capabilities and isolated worker identities |
| Skills | supply-chain attack | signed/hash-addressed versions, permission manifests, review/canary |
| Environment cache | stale capability assumptions | event-driven refresh before side effects |
| MCP tools | malicious/untrusted server | allowlists, OAuth scopes, server identity, payload taint |
| A2A workers | impersonation/artifact injection | authenticated agent cards/endpoints, schema validation, artifact provenance |
| Durable retries | duplicate side effects | idempotency keys/outbox/settlement records |

MCP's current authorization guidance uses OAuth-based authorization for protected servers, and A2A's specification provides standard security schemes including OAuth, OIDC and mTLS as well as explicit requirements around authorization and content validation. citeturn21search1turn18view1

NIST's Generative AI Profile is useful as the broader governance overlay, but the runtime controls above should be testable software invariants rather than documentation-only controls. citeturn21search4

## Migration, qualification, and rollout

### Migration from v2 without a dangerous rewrite

I would **not** implement the Context Compiler, Brainstem, graph memory and skill learning simultaneously.

The safe path is a strangler migration in which v2 remains authoritative until individual v3 components prove themselves.

```mermaid
gantt
    title Illustrative v2 → v3 rollout for a small engineering team
    dateFormat  YYYY-MM-DD

    section Measurement
    Execution ledger and tracing       :a1, 2026-09-21, 14d
    Baseline replay corpus             :a2, after a1, 7d

    section Fast path
    Deterministic preflight gate       :b1, after a1, 14d
    Shadow bypass decisions            :b2, after b1, 7d

    section Memory IR
    Evidence / claim split             :c1, after a2, 21d
    Dependency graph / invalidation    :c2, after c1, 14d

    section Context
    Hybrid retrieval pipeline          :d1, after c1, 14d
    Context IR and compiler            :d2, after d1, 21d

    section Brainstem
    Rule-based budgets and escalation  :e1, after d2, 14d
    Worker admission policy            :e2, after e1, 14d

    section Reuse
    Environment cache                  :f1, after c1, 14d
    Versioned skill registry           :f2, after d2, 21d

    section Qualification
    Security and fault injection       :g1, after e2, 14d
    Cross-harness qualification        :g2, after f2, 14d
    v3 qualification / canary          :g3, after g1, 14d
```

The dates are an **illustrative sequencing plan**, not a delivery commitment. Parallelism depends heavily on your existing v2 implementation and team size.

### Phase-by-phase migration detail

**Telemetry first.** Add execution IDs, attempt IDs, parent/worker relationships, token usage, cost, retrieval counts, cache hits, wall time, state mutations and final verifier outcomes without changing v2 behavior. Adopt an OpenTelemetry-compatible trace envelope so the data can survive future harness/provider changes. citeturn19view3turn14academia41

**Fast gate second.** Run gate decisions in shadow mode:

```text
gate predicts BYPASS
v2 still executes normally
compare predicted bypass with whether memory actually influenced verified result
```

Only enable real bypass after false-bypass rates are acceptably low.

**Memory IR third.** Dual-write v2 memories into the new evidence/claim representation. Do not migrate by asking an LLM to reinterpret the entire old memory database in one pass. Preserve original v2 objects as evidence and create v3 claims referencing them.

**Dependency invalidation fourth.** Initially mark derived memories stale without automatically deleting or recomputing them. Compare invalidation results with a brute-force consistency checker.

**Context Compiler fifth.** Run it in shadow beside v2 retrieval. Store:

```text
v2 context
v3 context
token counts
retrieval sets
final task result
counterfactual evaluator result
```

Only switch traffic when the v3 quality/token frontier dominates.

**Brainstem sixth.** Start with deterministic hard ceilings and simple rules. Train routing predictors on collected traces after you can measure verified outcomes reliably. RouteLLM's recommendation to calibrate against the actual workload distribution is especially relevant here. citeturn19view4

**Skills and environment intelligence seventh.** Environment caching is low risk if facts remain revision-addressed. Skill auto-promotion is much higher risk, so introduce versioned manual promotion first, then shadow automatic proposals, then canaries.

**Harness migration last.** Put current v2 harness behavior behind the canonical adapter and run a contract test suite. Add additional harnesses only after the semantics no longer depend on the original one.

### Qualification benchmark matrix

You need a **v3 qualification suite**, not a single memory benchmark.

| Requirement | Test workload | Primary metrics | Failure gate |
|---|---|---|---|
| No-op | Thousands of trivial/self-contained turns | added tokens, added calls, p50/p95 overhead | Any hidden LLM on declared bypass |
| Retrieval gating | Mixed memory-needed/no-memory tasks | activation precision/recall | False bypass above target |
| Continuity | LongMemEval + internal multi-session cases | update, temporal, abstention accuracy | Regression vs v2 |
| Provenance | Fact questions with seeded evidence | evidence coverage, unsupported claim rate | Untraceable high-impact memory |
| Invalidation | Random source mutations | invalidation completeness/latency | Any affected active claim missed |
| Context Compiler | Replay corpus | success/token, token reduction, p95 | Quality loss outside tolerance |
| Staleness | Version-changing repos/configs | stale-memory-use rate | Safety-critical stale reuse |
| Budget routing | Difficulty-stratified tasks | Pareto frontier: cost vs success | Dominated by fixed policy |
| Worker spawning | Parallel/nonparallel task pairs | spawn precision, net utility | Negative average marginal utility |
| Skills | Held-out and adversarial tasks | success, regression, cost | Unapproved side effect |
| Environment cache | Repository commit sequence | cache hit, refresh cost, stale fact rate | Incorrect command/capability after change |
| Durable execution | Process kills/network failures | exactly-once logical effect, recovery | Duplicate side effect/lost settlement |
| Harness independence | Same episodes via all adapters | semantic output/state equivalence | Harness-dependent memory corruption |
| Security | AgentDojo + custom injection suite | attack success, utility under defense | Unauthorized effect/data flow |

AgentDojo supplies 97 realistic tasks and hundreds of security test cases covering agents operating over untrusted tool data, making it much more appropriate than ordinary prompt-injection string tests. citeturn16search32

LongMemEval should become the external memory regression suite because its categories align unusually closely with v3's continuity requirements. citeturn2academia39

For coding/environment cases, include repository-level tasks modeled on RepoCoder/SWE-agent ideas: change a branch, dependency version, test command, package layout or file while preserving similar natural-language requests, then verify that cached environmental knowledge invalidates correctly. citeturn15academia39turn15academia38

### Core v3 metrics

I would make these visible on a permanent dashboard:

\[
\boxed{
\text{Verified Success Rate}
}
\]

\[
\boxed{
\text{Cost per Verified Success}
}
\]

\[
\boxed{
\text{Tokens per Verified Success}
}
\]

\[
\boxed{
p50/p95/p99\;\text{Wall Latency}
}
\]

\[
\boxed{
\text{Brain Net Token Savings}
=
Tokens_{off}-Tokens_{on,total}
}
\]

where `Tokens_on,total` includes **every** parent, worker, verifier, compressor and routing model.

Also track:

```text
brain_activation_rate
brain_activation_precision
false_bypass_rate

retrieval_recall_at_k
retrieval_precision_at_k
context_tokens_added
context_waste_ratio
provenance_coverage

stale_memory_use_rate
invalidation_completeness
invalidation_p95_ms

exact_reuse_hit_rate
verified_reuse_success_rate

worker_spawn_rate
worker_positive_marginal_utility_rate
worker_duplicate_work_rate

skill_invocation_success_rate
skill_rollback_rate
skill_out_of_scope_invocation_rate

environment_cache_hit_rate
environment_stale_fact_rate

unauthorized_action_rate
prompt_injection_attack_success_rate
duplicate_side_effect_rate
```

The **killer metric** remains:

\[
\boxed{
\Delta CPVS
=
CPVS_{v3}
-
CPVS_{BrainOff}
}
\]

where lower is better and quality must remain at or above the required threshold.

A v3 feature does not qualify merely because its own microbenchmark is faster.

### Concrete implementation stack

For an initial production implementation, I would deliberately keep the stack unglamorous:

| Layer | Recommended first choice | Alternatives / when to change |
|---|---|---|
| System of record | PostgreSQL | Distributed SQL only after scale requires it |
| Semantic index | `pgvector` initially | Qdrant/Milvus when vector scale/latency proves PostgreSQL insufficient |
| Lexical index | PostgreSQL FTS initially | Tantivy/Elasticsearch/OpenSearch for larger search workloads |
| Immutable artifacts | Content-addressed object storage | Local CAS for developer-only deployment |
| Dependency graph | PostgreSQL edge tables + reverse indexes | Dedicated graph DB only after profiling |
| Local hot cache | In-process LRU/TinyLFU-style cache | Redis/Valkey for shared deployments |
| Tracing | OpenTelemetry | Preserve custom cost fields alongside conventions |
| Profiling | semantic-operation aggregation inspired by AgentPProf | `eunomia-bpf/agentsight` as reference implementation citeturn14academia41 |
| Durable jobs | Existing v2 mechanism if sound; otherwise Temporal | LangGraph for agent-centric state machines where its semantics fit; Temporal for stronger general workflow durability |
| Code parsing | Tree-sitter | LSP/SCIP integration for richer semantic indexes citeturn21search3 |
| Router | Rules initially | RouteLLM-style learned router after trace data exists citeturn14academia40turn19view4 |
| Skills | Agent Skills-compatible packaging plus Second Brain metadata | Do not let the external skill spec replace your security manifest citeturn20search16turn20search20 |
| Security eval | AgentDojo | Add your own connector-specific attack corpus citeturn16search32 |
| Agent/tool protocol | MCP adapters | Native adapters where MCP semantics are insufficient citeturn18view0 |
| Agent interoperability | A2A adapter | Internal protocol for in-process workers; A2A for genuine independent systems citeturn18view1 |

### The minimum implementation I would build first

Before attempting “full v3,” the first coherent vertical slice should contain only:

```text
1. Execution/cost ledger
2. Deterministic no-op gate
3. Immutable evidence + derived-claim schema
4. Explicit dependency/reverse-dependency edges
5. Hybrid sparse+dense retrieval
6. Auth/validity filtering
7. Context IR + budgeted compiler
8. Rule-based Brainstem
9. Existing v2 invariant kernel
10. Replay/qualification harness
```

Do **not** initially add autonomous consolidation, learned worker routing, automatic skill rewriting, elaborate graph reasoning, multi-tier semantic caches or an LLM-powered Brainstem.

Once that vertical slice proves that:

```text
Brain ON quality >= Brain OFF quality
Brain ON total tokens < Brain OFF total tokens on reuse workloads
Brain ON ≈ Brain OFF on no-benefit workloads
stale/unauthorized memory does not enter context
worker cost is fully attributable
context is reproducible from provenance
```

then add increasingly adaptive behavior.

### Final design judgment

The v3 vision should remain, but I would sharpen its definition from:

> “Second Brain is a compiler for remembered experience.”

to:

> **Second Brain v3 is an incremental, provenance-preserving cognitive runtime that compiles only the currently valid and useful parts of prior experience into the minimum context needed for a task, while a cheap deterministic governor decides when remembering, reasoning, delegation, or reuse is economically justified.**

That formulation incorporates what the strongest evidence now says.

Long-context research argues against indiscriminately feeding everything back to the model. citeturn3academia40turn3academia41

Selective-retrieval research supports a legitimate “nothing useful to inject” outcome. citeturn3academia42turn15academia40

Modern long-term-memory evaluations emphasize updates, temporal consistency and abstention rather than raw recall alone. citeturn2academia39turn2academia38

Incremental computation provides the right conceptual foundation for deriving and invalidating state rather than periodically rebuilding an undifferentiated memory corpus. citeturn16academia38

Routing research and production multi-agent experience show that intelligence allocation must be treated as an economic decision: additional inference can buy quality, but uncontrolled agents and workers can multiply token consumption dramatically. citeturn14academia39turn14academia40turn19view0

Recent skills work supports reusable, structured procedures, but the newest results point toward attribution, local edits, scoped validation and rollback rather than unconstrained self-modification. citeturn13academia40turn13search36turn20search16

And current agent-security work makes the v2 guarantees more—not less—important: prompt injection, confused-deputy behavior and persistent poisoned memory cannot be solved reliably by prompting alone, so authorization, information flow, provenance and side-effect control must remain outside probabilistic reasoning. citeturn16search32turn13academia41turn21search4

So the answer to whether the v3 choices still stand is **yes, with one major implementation correction**: make v3 less “agentic” internally than the name Second Brain might suggest. The parts that control **what is true, what is valid, what may be accessed, what changed, what may execute, how much may be spent, and whether an operation settled** should be deterministic systems software. The LLM should supply semantic intelligence only at the points where deterministic machinery genuinely runs out.

That architecture gives you the best chance of satisfying the original requirement that matters most: **an agent that accumulates useful experience without continually paying to reread, rediscover, re-reason, or revalidate that experience—and that becomes almost invisible when its memory has nothing useful to contribute.**