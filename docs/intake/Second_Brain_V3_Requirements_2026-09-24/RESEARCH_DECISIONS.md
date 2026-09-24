# V3 — Research Decisions, 24 September 2026

**Purpose:** Record why the final requirements change without turning research into another infrastructure delay. Source IDs refer to the register in `V3_FINAL_REQUIREMENTS.md`. All recommendations are proposed engineering decisions; no external benchmark was reproduced here.

## New and recent findings

### 22 September 2026 — AkasicMEM [S06]
The paper foregrounds transitive lineage and retrieval-time re-evaluation of source restrictions. Its broader unified database architecture and performance have not been validated for this project.

**Decision:** Add restriction propagation to derived summaries, cached snippets, shared packs and deletion/revocation. Reuse the existing data store and normalized access contracts rather than importing its database. This controls Brain data disclosure, not host agent work.

### 10 September 2026 — Grounding Agent Memory [S05]
The authors add read-only environmental checks during memory curation. Their headline task-agent economics exclude separately tracked curation, so those savings are not automatically total-system savings.

**Decision:** Add scoped source/schema/path verification for reusable claims. Prefer deterministic existing readers. A native harness may execute an explicitly selected research task, but Brain must not create a curator-agent lifecycle. Count both checking and later reuse costs.

### 4 September 2026 — Memory portability study [S04]
The study tests 48 synthetic histories and two small open models. It highlights lossy note construction and incompatible embedding migration; this is useful failure-mode evidence, not proof about every frontier model or every memory system.

**Decision:** Require original-evidence availability metadata, structured exact fields, writer/reader migration cases, and isolated embedding-space versions. A fixed schema is useful without mandating a knowledge-graph server.

### 1 September 2026 — Endogenous authorization laundering [S03]
The paper examines permissions that become falsely represented through memory updates even without an injected external attack.

**Decision:** Extend M00 authority tests across merges, summaries, skill packaging and later recall. Never let repetition, utility, a confident summary or a claimed source origin generate permission. Keep the external issuer off V3's critical path.

### 24 August 2026 — Compaction Cliff [S02]
The author version studies repeated compaction and type-sensitive retention rather than uniform summarization.

**Decision:** Require fidelity classes and multi-round recovery fixtures. Preserve exact active constraints as context data without reinstating Brain's unavailable policy lane, vetoing host compaction or promising control over inaccessible host internals.

### 20 August 2026 — StateMem/StateMemBench [S01]
The paper emphasizes current state rather than merely recalling old statements. Its limitations disclose synthetic short-to-medium scenarios, single runs and roughly 165–600 encoder calls per scenario.

**Decision:** Add explicit supersession and dependency-aware state views; reject the assumption that V3 needs that expensive per-turn extraction pipeline. Test on real development changes as well as constructed cases.

### 7 August 2026 — Agent Memory Distillation [S15]
The abstract describes reusable knowledge at several granularities, including function-level help triggered by tool errors.

**Decision:** Compare small, evidence-backed error corrections against full transcript replay. Do not add a Brain-controlled teacher/student fleet or assume its benchmark improvements transfer to this project.

## Available implementation components

### USearch 2.26.2 — package dated 31 August 2026 [S07, S08]
The maintainer documents exact and approximate search plus serialized/mapped indexes. Benchmark the supported binding and actual end-to-end path. Do not adopt ANN merely because its raw lookup is fast.

**Decision:** Compare exact-vector hybrid first, then USearch HNSW at relevant corpus sizes. Keep the index rebuildable, encoder-independent through a versioned interface and optional under small/default workloads.

### Compact local text encoders — established 2025 releases [S09, S10]
EmbeddingGemma and Qwen3-Embedding-0.6B are practical candidates to evaluate, not newly released September 2026 models. Google describes flexible dimensions for EmbeddingGemma; its vendor latency/RAM figures do not establish the complete working set on the user's laptop.

**Decision:** Compare quality, total inference latency, loading, RAM, licensing/distribution constraints and quantization. Preserve exact/lexical fallback. Do not mandate a GPU or a local generative agent simply to compute embeddings.

### Agent Skills and MCP [S11, S12]
Agent Skills specifies staged loading of metadata, instructions and resources. The current MCP material includes evolving capability surfaces and a Skills-over-MCP working group; discoverability in a specification does not prove implementation by a particular installed host.

**Decision:** Use portable native-compatible skill packages now. Negotiate optional protocol support in adapters. Do not confuse skill discovery with independent approval, zero metadata cost or permission to implement host-work control.

### Native/product memory [S17]
Claude Managed Agents documents versioned memory stores. This is a distinct product/API surface and not evidence about the user's Claude Code cloud credit or eligibility.

**Decision:** Where available, compare V3 with a well-configured native memory/skills baseline. Keep the cross-harness core; do not make provider-specific memory or cloud synchronization mandatory.

## Research that reinforces rather than resets the plan

SimpleMem [S16] supports examining structured representations and selective consolidation. MemoryArena [S13] supports multi-session tests with interdependent experiences. AMA-Bench [S14] supports testing machine-generated tool/environment evidence, not only chat facts. These are earlier publications, not newly discovered reasons to restart development.

## Concrete roadmap decisions

1. Keep the original incremental reuse/context thesis and strict no-op economics.
2. Promote current-state/supersession, provenance across transformations, model/encoder portability and source-aware curation into explicit requirements.
3. Remove Brain-owned workflow execution and worker scheduling from M08/M11; use native execution and Brain-owned resource limits instead.
4. Require semantic capability and comparative experiments, but not USearch, a graph database, a large encoder or a learned selector as predetermined winners.
5. Begin S1 now: measured non-interference, no-op path and the actual query-dilution regression. Add richer retrieval in S2 with the minimum necessary state/provenance contracts.
6. Keep trust-root deployment, Claude cloud, distributed sync and heavyweight multimodal research outside the local V3 start gate.

## Important limitations

This review does not establish current Windows process state, the exact number of indexed chunks, real laptop encoder performance, successful source revalidation, protected OS isolation or the correctness of any new implementation. The requirements explicitly demand those measurements where relevant. Paper author claims remain author claims. No source scanned here justifies replacing Second Brain wholesale.
