# Second Brain v1.0 — Architecture Phase Gap Map

**P0-ARCH-PHASES** • Phase 0 GATE enforcement • 2026-08-18

Assessment of all numbered mechanisms in plan sections 3–10 (Local Token Efficiency Fabric, Phase 1–7).

**Status Breakdown**: 10 EXISTS-PARTIAL, 7 ABSENT, 0 EXISTS-USABLE

**Phase 0 GATE Policy**: No new subsystem approved until audit proves it does not already exist in usable form.

## Mechanism Assessment

| Mechanism | Section | Status | Existing Code (file:line) | What Must Be Built | Duplication Risk |
|---|---|---|---|---|---|
| Local Token Efficiency Fabric — deterministic cascade | §3 | EXISTS-PARTIAL | semantic.py:231 (FTS5 reference); autoinject.py (delivery lo... | Explicit ordered cascade enforcement (metadata→ID→... | None (new orchestration logic) |
| Token Governor — per-host/session/task/agent/feature tracking | §4 | ABSENT | NO EQUIVALENT FOUND (telemetry.py captures input_tokens/outp... | Context peak tracking, brain/worker/driver/compact... | Would reuse/extend telemetry.py event schema |
| Feature attribution & ablation harness | §4 | ABSENT | NO EQUIVALENT FOUND (cli.py has feature config but no system... | Systematic feature ablation harness; switchable ev... | Would extend cli.py config system |
| Token gate semantics — POSITIVE_ROI/NEUTRAL/NEGATIVE_ROI/INSUFFICIENT_EVIDENCE | §4 | ABSENT | NO EQUIVALENT FOUND (no ROI classification system in codebas... | Explicit ROI classification; enforcement that NEGA... | Would extend feature attribution harness |
| Observation Firewall — reducer registry | §5 | EXISTS-PARTIAL | artifacts.py: Distillation/backing store logic; rtd.ts: Dist... | Complete reducer registry for all output types: py... | Would extend rtd.ts + artifacts.py |
| Raw result backing store — SHA-256, dedupe, bounded retention | §5 | EXISTS-PARTIAL | artifacts.py + ledger.py: Basic content-addressed object sto... | Complete backing store with dedupe enforcement, bo... | Would extend artifacts.py + ledger.py |
| Transient Indexed Session Memory — transient session objects | §6 | EXISTS-PARTIAL | working_set.py: Transient session state (findings, decisions... | Formalized schema; guarantee that routine chatter ... | Would extend working_set.py |
| Context residency state — STORED/RESIDENT/EVICTED/FAULTED_IN/SUPERSEDED/PURGED | §6 | ABSENT | NO EQUIVALENT FOUND (working_set.py has evicted/resident tra... | Complete residency state machine with explicit tra... | Would extend working_set.py |
| Context paging — retrieve by ID, fallback: metadata/time/type → FTS5 → semantic | §6 | EXISTS-PARTIAL | jit.py: Context compilation with selective inclusion; workin... | Formalized paging protocol; hot/cold context separ... | Would extend jit.py + semantic.py |
| Admission/eviction policy — scoring (pinned, recency, frequency, verification, size) | §6 | ABSENT | NO EQUIVALENT FOUND (working_set.py has eviction logic but n... | Admission/eviction scoring function; pinned + rece... | Would extend working_set.py |
| Proof-Carrying Action Cache — action identity via hashes | §7 | EXISTS-PARTIAL | autoinject.py: Caching mechanism with request fingerprinting... | Complete action identity schema (action_kind, norm... | Would extend autoinject.py + artifacts.py |
| Action cache validity proof — hash-based invalidation | §7 | EXISTS-PARTIAL | autoinject.py: Hash-based validity checking in request finge... | Proof validation system (dependency check → hash m... | Would extend autoinject.py |
| Delta sync — exact unchanged reuse + changed-file delta | §8 | EXISTS-PARTIAL | scout.py: Git diff logic; working_set.py: Hash tracking; NO ... | Formalized delta sync (read ledger with file hashe... | Would extend working_set.py + scout.py |
| Hybrid retrieval cascade — metadata → IDs → FTS5 → structure → semantic | §9 | EXISTS-PARTIAL | semantic.py:1379 search_memories() implements retrieval casc... | Formalized cascade order enforcement; snippet extr... | Would extend semantic.py |
| Semantic/vector fallback — local CPU-friendly only after exact/lexical/structure | §9 | EXISTS-PARTIAL | semantic.py: Embedding/vector fallback mechanism; local-only... | Formalized semantic fallback (no external API); ab... | Would extend semantic.py |
| Tool Working Set — JIT skill/tool loading | §10 | ABSENT | NO EQUIVALENT FOUND (all skills/tools pre-loaded at session ... | Lazy loading protocol (compact descriptors at sess... | Would extend skillforge.py + router.py |
| Batched local query engine — combine deterministic operations | §10 | ABSENT | NO EQUIVALENT FOUND (no batched query capability; individual... | Batched query engine (project resolution + repo st... | Would extend cli.py + scout.py |

## Detailed Evidence

### Mech-3.1: Local Token Efficiency Fabric — deterministic cascade

**Status**: EXISTS-PARTIAL

**Existing Code**: semantic.py:231 (FTS5 reference); autoinject.py (delivery logic)

**What Must Be Built**: Explicit ordered cascade enforcement (metadata→ID→FTS5→structure→semantic); documented preference order validation

**Duplication Risk**: None (new orchestration logic)

---

### Mech-4.1: Token Governor — per-host/session/task/agent/feature tracking

**Status**: ABSENT

**Existing Code**: NO EQUIVALENT FOUND (telemetry.py captures input_tokens/output_tokens/cache_read/cache_write only; missing context_peak, brain_injected_tokens, worker_tokens, driver_tokens, compaction_tokens)

**What Must Be Built**: Context peak tracking, brain/worker/driver/compaction token attribution; complete feature-by-feature ablation harness

**Duplication Risk**: Would reuse/extend telemetry.py event schema

---

### Mech-4.2: Feature attribution & ablation harness

**Status**: ABSENT

**Existing Code**: NO EQUIVALENT FOUND (cli.py has feature config but no systematic ablation switches)

**What Must Be Built**: Systematic feature ablation harness; switchable evaluation of autoinject, firewall, context paging, action cache, delta sync, retrieval, semantic, tool working set, skill lazy loading

**Duplication Risk**: Would extend cli.py config system

---

### Mech-4.3: Token gate semantics — POSITIVE_ROI/NEUTRAL/NEGATIVE_ROI/INSUFFICIENT_EVIDENCE

**Status**: ABSENT

**Existing Code**: NO EQUIVALENT FOUND (no ROI classification system in codebase)

**What Must Be Built**: Explicit ROI classification; enforcement that NEGATIVE_ROI features cannot be always-on

**Duplication Risk**: Would extend feature attribution harness

---

### Mech-5.1: Observation Firewall — reducer registry

**Status**: EXISTS-PARTIAL

**Existing Code**: artifacts.py: Distillation/backing store logic; rtd.ts: Distillation pipeline; found references to pytest, git, json reduction

**What Must Be Built**: Complete reducer registry for all output types: pytest/test runners, compiler/type checker, git diff/status/log, grep/ripgrep, JSON payloads, process logs, stack traces, package-manager, doctor output

**Duplication Risk**: Would extend rtd.ts + artifacts.py

---

### Mech-5.2: Raw result backing store — SHA-256, dedupe, bounded retention

**Status**: EXISTS-PARTIAL

**Existing Code**: artifacts.py + ledger.py: Basic content-addressed object store; SHA-256 identity used; exact retrieval by ref

**What Must Be Built**: Complete backing store with dedupe enforcement, bounded retention/TTL, compression for large objects, object size caps, safe secret handling, exact retrieval by ref/range

**Duplication Risk**: Would extend artifacts.py + ledger.py

---

### Mech-6.2: Transient Indexed Session Memory — transient session objects

**Status**: EXISTS-PARTIAL

**Existing Code**: working_set.py: Transient session state (findings, decisions, blockers)

**What Must Be Built**: Formalized schema; guarantee that routine chatter is not persisted as permanent memories

**Duplication Risk**: Would extend working_set.py

---

### Mech-6.3: Context residency state — STORED/RESIDENT/EVICTED/FAULTED_IN/SUPERSEDED/PURGED

**Status**: ABSENT

**Existing Code**: NO EQUIVALENT FOUND (working_set.py has evicted/resident tracking but no formal residency state machine)

**What Must Be Built**: Complete residency state machine with explicit tracking by session/branch/segment/recipient

**Duplication Risk**: Would extend working_set.py

---

### Mech-6.4-6.5: Context paging — retrieve by ID, fallback: metadata/time/type → FTS5 → semantic

**Status**: EXISTS-PARTIAL

**Existing Code**: jit.py: Context compilation with selective inclusion; working_set.py: Retrieval logic; semantic.py: FTS5 fallback available

**What Must Be Built**: Formalized paging protocol; hot/cold context separation enforcement; cascading fallback priority validation

**Duplication Risk**: Would extend jit.py + semantic.py

---

### Mech-6.6: Admission/eviction policy — scoring (pinned, recency, frequency, verification, size)

**Status**: ABSENT

**Existing Code**: NO EQUIVALENT FOUND (working_set.py has eviction logic but no deterministic scoring function)

**What Must Be Built**: Admission/eviction scoring function; pinned + recency + frequency + verification_value + size scoring; enforcement of eviction criteria

**Duplication Risk**: Would extend working_set.py

---

### Mech-7.1: Proof-Carrying Action Cache — action identity via hashes

**Status**: EXISTS-PARTIAL

**Existing Code**: autoinject.py: Caching mechanism with request fingerprinting; artifacts.py: Content-addressed storage

**What Must Be Built**: Complete action identity schema (action_kind, normalized_task, input_deps, repo/worktree/file/config/tool hashes, verification_state, hit_count); cross-harness reusability

**Duplication Risk**: Would extend autoinject.py + artifacts.py

---

### Mech-7.3: Action cache validity proof — hash-based invalidation

**Status**: EXISTS-PARTIAL

**Existing Code**: autoinject.py: Hash-based validity checking in request fingerprinting

**What Must Be Built**: Proof validation system (dependency check → hash match → hit valid; hash mismatch → miss/partial invalidate)

**Duplication Risk**: Would extend autoinject.py

---

### Mech-8.1-8.2: Delta sync — exact unchanged reuse + changed-file delta

**Status**: EXISTS-PARTIAL

**Existing Code**: scout.py: Git diff logic; working_set.py: Hash tracking; NO formalized read-ledger protocol

**What Must Be Built**: Formalized delta sync (read ledger with file hashes → unchanged → offer cached understanding; changed → git diff + delta); small-file performance optimization

**Duplication Risk**: Would extend working_set.py + scout.py

---

### Mech-9.1-9.2: Hybrid retrieval cascade — metadata → IDs → FTS5 → structure → semantic

**Status**: EXISTS-PARTIAL

**Existing Code**: semantic.py:1379 search_memories() implements retrieval cascade; FTS5 first-class with BM25 ranking

**What Must Be Built**: Formalized cascade order enforcement; snippet extraction; bounded result limits; structure/symbol fallback (Tree-sitter only if ROI proven)

**Duplication Risk**: Would extend semantic.py

---

### Mech-9.3: Semantic/vector fallback — local CPU-friendly only after exact/lexical/structure

**Status**: EXISTS-PARTIAL

**Existing Code**: semantic.py: Embedding/vector fallback mechanism; local-only configuration

**What Must Be Built**: Formalized semantic fallback (no external API); ablation-tested ROI before default-on; dedupe/diversity scoring; avoid re-embedding unchanged content

**Duplication Risk**: Would extend semantic.py

---

### Mech-10.1-10.2: Tool Working Set — JIT skill/tool loading

**Status**: ABSENT

**Existing Code**: NO EQUIVALENT FOUND (all skills/tools pre-loaded at session start; no JIT mechanism)

**What Must Be Built**: Lazy loading protocol (compact descriptors at session start; full instructions load JIT on selection); task-relevant tool activation only

**Duplication Risk**: Would extend skillforge.py + router.py

---

### Mech-10.3: Batched local query engine — combine deterministic operations

**Status**: ABSENT

**Existing Code**: NO EQUIVALENT FOUND (no batched query capability; individual CLI commands only)

**What Must Be Built**: Batched query engine (project resolution + repo state + FTS + file hash + cache lookup + symbol + action-cache + memory refs in one call); Python API + CLI + MCP transport

**Duplication Risk**: Would extend cli.py + scout.py

---

## Summary

### Status Breakdown

| Status | Count |
|---|---|
| EXISTS-PARTIAL | 10 |
| ABSENT | 7 |
| EXISTS-USABLE | 0 |

### Phase 0 GATE Verdict

**Result**: GATE PASSES (no subsystem is both FULLY EXISTING and USABLE; no duplication blocks)

The audit confirms that new work can proceed without duplicating critical infrastructure:

**Fully Implementable (ABSENT or minimal foundation)**:

- Mech-4.1/4.2/4.3: Token Governor + Feature Attribution + ROI Gate (foundations in telemetry.py; new orchestration required)
- Mech-6.3: Context Residency State Machine (foundations in working_set.py; formal state enum required)
- Mech-6.6: Admission/Eviction Scoring (working_set.py exists; scoring function required)
- Mech-8.1/8.2: Delta Sync Protocol (scout.py has git diff; read-ledger protocol required)
- Mech-10.1/10.2: Tool JIT Loading (skillforge.py exists; lazy-load harness required)
- Mech-10.3: Batched Query Engine (cli.py exists; batch transport required)

**Can Extend Existing (EXISTS-PARTIAL)**:

- Mech-3.1: Cascade Orchestration (FTS5 exists; cascade order enforcement + validation required)
- Mech-5.1/5.2: Observation Firewall (artifacts.py + rtd.ts exist; comprehensive reducer registry + backing store TTL required)
- Mech-6.2: Transient Session Objects (working_set.py; schema formalization required)
- Mech-6.4/6.5: Context Paging (jit.py + semantic.py; formalized paging protocol + fallback priority required)
- Mech-7.1/7.3: Action Cache (autoinject.py + artifacts.py; complete identity schema + validity proof system required)
- Mech-9.1/9.3: Hybrid Retrieval (semantic.py; cascade enforcement + snippet extraction + structure fallback optional)

### Implementation Path

All Phase 1–7 mechanisms are buildable without architectural conflict:

1. **Phase 1 (Mech-4)**: Token Governor must precede optimization (build measurements first)
2. **Phase 2 (Mech-5)**: Observation Firewall extends existing artifacts.py + rtd.ts
3. **Phase 3 (Mech-6)**: Transient Session Memory upgrades existing ledger/working_set without replacement
4. **Phase 4 (Mech-7)**: Action Cache extends autoinject.py caching
5. **Phase 5 (Mech-8)**: Delta Sync uses existing scout.py + working_set.py read ledger
6. **Phase 6 (Mech-9)**: Hybrid Retrieval improves semantic.py without replacing FTS5
7. **Phase 7 (Mech-10)**: Tool Working Set & Batched Query use skillforge.py + cli.py as foundation

### Recommended Next Step

Begin Phase 1 (Token Governor) immediately. All Phase 1 mechanisms are ABSENT or minimal-foundation, unblocked by dependency or duplication.

---

## Appendix: Grep Search Methods

For each mechanism, the following search patterns were used to determine existence:

```
# Cascade/Efficiency (Mech-3.1)
grep -r 'cascade\|deterministic\|fts5' src/second_brain/

# Token Governor (Mech-4.1)
grep -r 'input_tokens\|context_peak\|brain_injected' src/second_brain/telemetry.py

# Feature Attribution (Mech-4.2)
grep -r 'ablat\|feature.*config\|switchable' src/second_brain/cli.py

# Token Gate (Mech-4.3)
grep -r 'roi\|positive_roi\|negative_roi' src/second_brain/

# Reducer Registry (Mech-5.1)
grep -r 'reducer\|pytest\|compiler\|git' src/second_brain/artifacts.py brainstem/prime-extension/src/rtd.ts

# Backing Store (Mech-5.2)
grep -r 'sha256\|content_addr\|dedupe\|retention' src/second_brain/artifacts.py src/second_brain/ledger.py

# Transient Objects (Mech-6.2)
grep -r 'finding\|blocker\|decision\|transient' src/second_brain/working_set.py src/second_brain/episodes.py

# Residency State (Mech-6.3)
grep -r 'resident\|evicted\|faulted\|superseded' src/second_brain/working_set.py

# Context Paging (Mech-6.4/6.5)
grep -r 'paging\|retrieve\|fallback.*fts' src/second_brain/jit.py src/second_brain/semantic.py

# Admission/Eviction (Mech-6.6)
grep -r 'admission\|eviction.*policy\|score' src/second_brain/working_set.py

# Action Cache (Mech-7.1/7.3)
grep -r 'cache.*hash\|action.*cache' src/second_brain/autoinject.py src/second_brain/artifacts.py

# Delta Sync (Mech-8.1/8.2)
grep -r 'unchanged\|read.*ledger\|git.*diff' src/second_brain/scout.py src/second_brain/working_set.py

# Hybrid Retrieval (Mech-9.1/9.3)
grep -r 'cascade\|fts5\|bm25\|semantic.*fallback' src/second_brain/semantic.py

# Tool JIT (Mech-10.1/10.2)
grep -r 'lazy.*load\|jit\|descriptor' src/second_brain/skillforge.py src/second_brain/router.py

# Batched Query (Mech-10.3)
grep -r 'batch.*query\|combined.*call' src/second_brain/cli.py src/second_brain/scout.py
```

**All cited file paths verified to exist on machine** (automated check passed).
